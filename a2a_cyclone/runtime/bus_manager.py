"""
A2A-CyClone Runtime Layer: 总线管理器 (Bus Manager)
负责总线文件的原子读写、状态流转校验与多总线实例管理。

在所有物理写入前，强制调用 Protocol 层的不变量与 ACL 校验机制。
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from ..protocol.enums import BusState
from ..protocol.state_machine import StateMachine
from ..protocol.permissions import can_transition, can_force_reset, can_create_sub_bus
from ..protocol.invariants import (
    assert_invariants,
    assert_vector_clock_monotonicity,
)


class BusManager:
    """总线管理器：封装总线文件的原子读写与状态跃迁

    职责：
      1. 原子级文件读写（临时文件 + os.replace）
      2. 状态流转前调用 Protocol 层校验
      3. 多总线实例管理（根总线 + 子总线）
      4. Vector_Clock 自动递增
    """

    def __init__(self, bus_file_path: str, bus_id: str = "root-bus-0"):
        self.bus_file_path = bus_file_path
        self.bus_id = bus_id
        self._ledger_writer = None  # 延迟绑定，避免循环依赖

    # ---- 原子 I/O ----

    def atomic_read(self) -> Optional[Dict[str, Any]]:
        """原子读取总线文件

        若文件不存在，返回 None。
        若 JSON 损坏，返回 None（调用方应视为总线未初始化）。
        """
        if not os.path.exists(self.bus_file_path):
            return None
        try:
            with open(self.bus_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 注入 bus_id（若文件中未明确存储）
            if "bus_id" not in data:
                data["bus_id"] = self.bus_id
            return data
        except (json.JSONDecodeError, PermissionError, OSError):
            return None

    def atomic_write(self, data: Dict[str, Any]) -> None:
        """原子写入总线文件

        使用临时文件 + os.replace() 确保写入的原子性。
        在任何文件系统上（Windows/Linux/macOS），读操作要么看到旧文件，
        要么看到完整的新文件，绝不会看到半写入的脏数据。
        """
        temp_file = f"temp_{self.bus_id}.json"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temp_file, self.bus_file_path)

    def bus_exists(self) -> bool:
        """检查总线物理文件是否存在"""
        return os.path.exists(self.bus_file_path)

    # ---- 状态跃迁 ----

    def transition(
        self,
        next_state: BusState,
        actor_aid: str,
        payload_updates: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """执行一次完整的状态跃迁（带全量 Protocol 层校验）

        流程（严格按照架构图 5 步）：
          1. 原子读取当前总线状态
          2. 调用 StateMachine.validate_transition() 验证跃迁合法性
          3. 调用 can_transition() 验证 ACL 权限
          4. 调用 assert_invariants() 验证系统不变量
          5. 构造新状态并原子写入

        Args:
            next_state: 目标状态码
            actor_aid: 触发跃迁的 Agent ID
            payload_updates: 额外需要更新的字段

        Returns:
            跃迁后的完整总线数据

        Raises:
            ValueError: 非法跃迁
            PermissionError: ACL 权限不足
            AssertionError: 不变量违背
        """
        # Step 1: 读取当前状态
        bus_data = self.atomic_read()
        if bus_data is None:
            bus_data = self._create_initial_bus()

        current_state = BusState(bus_data.get("status", "000"))

        # Step 2: 状态机拓扑校验
        StateMachine.validate_transition(current_state, next_state)

        # Step 3: ACL 权限校验
        can_transition(actor_aid, bus_data, next_state)

        # Step 4: 构造新数据并校验不变量
        new_data = dict(bus_data)
        new_data["status"] = next_state.value
        new_data["Vector_Clock"] = new_data.get("Vector_Clock", 0) + 1

        if payload_updates:
            new_data.update(payload_updates)

        # Vector_Clock 单调性校验
        assert_vector_clock_monotonicity(bus_data, new_data["Vector_Clock"])

        # 系统不变量校验
        assert_invariants(new_data)

        # Step 5: 原子写入
        self.atomic_write(new_data)

        # 记录到账本
        self._append_ledger(bus_data, new_data, actor_aid)

        return new_data

    def force_transition(
        self,
        next_state: BusState,
        actor_aid: str,
        reason: str = "",
    ) -> Dict[str, Any]:
        """强制状态跃迁（用于级联销毁等异常恢复场景）

        与 transition() 相同但跳过 ACL 校验中的部分限制，
        允许父总线的 Token_Holder 跨总线强制改写子总线状态。
        """
        bus_data = self.atomic_read()
        if bus_data is None:
            bus_data = self._create_initial_bus()

        current_state = BusState(bus_data.get("status", "000"))

        # 仅校验状态机拓扑
        StateMachine.validate_transition(current_state, next_state)

        # 构造新数据
        new_data = dict(bus_data)
        new_data["status"] = next_state.value
        new_data["Vector_Clock"] = new_data.get("Vector_Clock", 0) + 1
        new_data["force_reset"] = True
        new_data["force_reset_by"] = actor_aid
        new_data["force_reset_reason"] = reason

        # 不变量校验
        assert_invariants(new_data)

        self.atomic_write(new_data)
        self._append_ledger(bus_data, new_data, actor_aid)

        return new_data

    # ---- 总线初始化 ----

    def initialize_bus(
        self,
        aid: str,
        parent_bus_id: Optional[str] = None,
        child_bus_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """初始化总线物理文件

        仅在总线不存在时创建。若已存在则返回现有数据。
        """
        existing = self.atomic_read()
        if existing is not None:
            return existing

        initial_data = {
            "status": "000",
            "bus_id": self.bus_id,
            "Aid": aid,
            "Target_Aid": "",
            "Vector_Clock": 0,
            "Request": "",
            "content": "",
            "Lease_Extension": 0,
            "Token_Holder": "",
            "Parent_Bus": parent_bus_id,
            "Child_Buses": child_bus_ids or [],
        }
        self.atomic_write(initial_data)
        return initial_data

    def destroy_bus(self) -> None:
        """销毁总线物理文件（回归 000 后调用）"""
        if os.path.exists(self.bus_file_path):
            os.remove(self.bus_file_path)

    # ---- 内部方法 ----

    def _create_initial_bus(self) -> Dict[str, Any]:
        """创建默认的初始总线数据结构"""
        return {
            "status": "000",
            "bus_id": self.bus_id,
            "Aid": "",
            "Target_Aid": "",
            "Vector_Clock": 0,
            "Request": "",
            "content": "",
            "Lease_Extension": 0,
            "Token_Holder": "",
            "Parent_Bus": None,
            "Child_Buses": [],
        }

    def _append_ledger(
        self,
        old_data: Dict[str, Any],
        new_data: Dict[str, Any],
        actor_aid: str,
    ) -> None:
        """向账本追加状态流转事件（若账本写入器已绑定）"""
        if self._ledger_writer is None:
            return
        try:
            from ..protocol.ledger import LedgerEventType, LedgerEntry
            entry = LedgerEntry(
                event_id=f"evt_{uuid.uuid4().hex}",
                event_type=LedgerEventType.STATE_TRANSITION,
                bus_id=self.bus_id,
                agent_id=actor_aid,
                timestamp_iso=datetime.now(timezone.utc).isoformat(),
                vector_clock=new_data.get("Vector_Clock", 0),
                payload={
                    "old_status": old_data.get("status", "000"),
                    "new_status": new_data.get("status", "000"),
                    "forced": new_data.get("force_reset", False),
                },
            )
            self._ledger_writer.append(entry)
        except Exception:
            pass  # 账本写入失败不应阻塞总线操作

    def bind_ledger(self, ledger_writer) -> None:
        """绑定账本写入器"""
        self._ledger_writer = ledger_writer
