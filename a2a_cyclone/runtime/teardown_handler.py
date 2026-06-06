"""
A2A-CyClone Runtime Layer: 级联销毁处理器 (Cascading Teardown Handler)

负责在检测到 Agent 死亡或 GLOBAL_FATAL 级联异常时，
强制回收该 Agent 管理的所有子总线，防止"僵尸子总线"资源泄漏。

核心流程：
  1. 父总线 LeaseWatcher 检测到 Agent 租约过期
  2. TeardownHandler 根据拓扑关系计算受影响的子总线列表
  3. 对每个受影响的子总线强制执行 force_transition(103/000)
  4. 记录级联销毁事件到全局账本
"""

import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Set

from ..protocol.enums import BusState
from ..protocol.failure_propagation import (
    FailureSignal,
    FailureCategory,
    CriticalityMask,
    compute_cascading_impact,
)
from ..protocol.bus_topology import (
    compute_teardown_targets,
    should_trigger_teardown,
)


class TeardownHandler:
    """级联销毁处理器

    职责：
      1. 接收父总线的 Agent 死亡信号
      2. 计算需要被销毁的子总线列表
      3. 依次对每个子总线执行强制状态回退
      4. 生成级联销毁信号向更上层传播（若需要）
    """

    def __init__(self):
        # 已执行销毁的总线集合（防止重复销毁）
        self._teardown_log: List[Dict[str, Any]] = []
        self._pending_signals: List[FailureSignal] = []

    def handle_agent_lost(
        self,
        lost_agent_id: str,
        parent_bus_data: Dict[str, Any],
        child_bus_managers: Dict[str, Any],  # bus_id -> BusManager
        bus_topology: Dict[str, Any],         # bus_id -> topology info
    ) -> List[Dict[str, Any]]:
        """处理 Agent 丢失事件的主入口

        当父总线检测到某 Agent 租约过期/节点不可达时调用此方法。

        Args:
            lost_agent_id: 被判死亡的 Agent ID
            parent_bus_data: 父总线的当前数据
            child_bus_managers: 所有子总线的 BusManager 实例映射
            bus_topology: 总线拓扑关系映射

        Returns:
            执行销毁的总线列表及结果
        """
        results = []

        # Step 1: 找出该 Agent 管理的所有子总线
        managed_buses = self._find_managed_buses(lost_agent_id, bus_topology)

        # Step 2: 计算级联销毁目标
        parent_bus_id = parent_bus_data.get("bus_id", "")
        parent_child_buses = parent_bus_data.get("Child_Buses", [])

        target_bus_ids = compute_teardown_targets(
            bus_id=parent_bus_id,
            child_bus_ids=parent_child_buses,
            agent_managed_buses=managed_buses,
        )

        # Step 3: 对每个目标总线执行强制销毁
        for bus_id in target_bus_ids:
            if bus_id not in child_bus_managers:
                continue

            manager = child_bus_managers[bus_id]
            try:
                new_data = manager.force_transition(
                    next_state=BusState.RELEASE_FAILED,
                    actor_aid=parent_bus_data.get("Token_Holder", "root-001"),
                    reason=f"Cascading teardown: Agent '{lost_agent_id}' lost",
                )
                results.append({
                    "bus_id": bus_id,
                    "status": "teardown_success",
                    "new_status": new_data.get("status"),
                    "error": None,
                })
            except Exception as exc:
                results.append({
                    "bus_id": bus_id,
                    "status": "teardown_failed",
                    "new_status": None,
                    "error": str(exc),
                })

        # Step 4: 记录
        self._teardown_log.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "lost_agent": lost_agent_id,
            "parent_bus": parent_bus_id,
            "targets": target_bus_ids,
            "results": results,
        })

        return results

    def handle_cascading_failure(
        self,
        signal: FailureSignal,
        parent_bus_data: Dict[str, Any],
        child_bus_managers: Dict[str, Any],
        bus_topology: Dict[str, Any],
    ) -> Optional[FailureSignal]:
        """处理级联异常信号

        接收子总线抛出的 FailureSignal，根据 criticality 决定：
          - LOCAL_RETRYABLE: 阻断，不向上传播
          - GLOBAL_FATAL: 执行子总线销毁，并向上生成新的 FailureSignal

        Returns:
            若应向上传播，返回新的 FailureSignal；否则返回 None
        """
        parent_bus_id = parent_bus_data.get("bus_id", "")

        # 若不需要向上传播，异常被局部阻断
        cascaded = compute_cascading_impact(signal, parent_bus_id)
        if cascaded is None:
            return None

        # GLOBAL_FATAL：执行子总线销毁
        self.handle_agent_lost(
            lost_agent_id=signal.source_agent_id,
            parent_bus_data=parent_bus_data,
            child_bus_managers=child_bus_managers,
            bus_topology=bus_topology,
        )

        # 向上传播
        self._pending_signals.append(cascaded)
        return cascaded

    def get_teardown_log(self) -> List[Dict[str, Any]]:
        """返回销毁日志（审计用）"""
        return list(self._teardown_log)

    def get_pending_signals(self) -> List[FailureSignal]:
        """返回尚未处理的传播信号"""
        return list(self._pending_signals)

    def clear_pending_signals(self) -> None:
        """清空待处理信号"""
        self._pending_signals.clear()

    # ---- 内部方法 ----

    @staticmethod
    def _find_managed_buses(
        agent_id: str,
        bus_topology: Dict[str, Any],
    ) -> List[str]:
        """找出指定 Agent 管理的所有总线

        一个 Agent 可能同时是多个子总线的 Token_Holder。
        """
        managed = []
        for bus_id, info in bus_topology.items():
            if isinstance(info, dict):
                if info.get("token_holder") == agent_id:
                    managed.append(bus_id)
            elif hasattr(info, 'token_holder'):
                if info.token_holder == agent_id:
                    managed.append(bus_id)
        return managed
