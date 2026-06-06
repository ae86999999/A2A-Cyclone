"""
A2A-CyClone Runtime Layer: 租约看门狗 (Lease Watcher)
负责监控 Token_Holder 的续租心跳，超时触发令牌回收。

v0.2.0: 新增主干节点宽限期（Trunk Node Grace Period），
        解决递归架构下的父子总线租约竞争条件。
"""

import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Callable

from ..protocol.bus_topology import compute_grace_period


class LeaseWatcher:
    """租约看门狗：监控活跃总线的租约状态

    核心机制：
      1. 周期性检查总线的 LEASE_HEARTBEAT (202) 是否在宽限期内更新
      2. 对于充当子总线 Master 的主干节点（Trunk Node），给予额外宽限期
      3. 超时后通过回调通知上层执行令牌回收
    """

    def __init__(
        self,
        heartbeat_interval_ms: int = 1000,
        max_missed_heartbeats: int = 3,
        trunk_grace_multiplier: float = 2.0,
    ):
        self.heartbeat_interval_ms = heartbeat_interval_ms
        self.max_missed_heartbeats = max_missed_heartbeats
        self.trunk_grace_multiplier = trunk_grace_multiplier

        # 监控状态: bus_id -> { "last_heartbeat_time": float, "last_lease_value": int }
        self._watch_state: Dict[str, Dict[str, Any]] = {}

    def register(self, bus_id: str) -> None:
        """注册一条总线的租约监控"""
        self._watch_state[bus_id] = {
            "last_heartbeat_time": time.time(),
            "last_lease_value": 0,
            "missed_count": 0,
            "status": "monitoring",
        }

    def unregister(self, bus_id: str) -> None:
        """注销总线的租约监控"""
        self._watch_state.pop(bus_id, None)

    def heartbeat_received(self, bus_id: str, lease_value: int) -> None:
        """记录一次续租心跳

        每次从总线读到 202 状态时调用此方法更新最后心跳时间。
        """
        if bus_id not in self._watch_state:
            self.register(bus_id)

        state = self._watch_state[bus_id]
        state["last_heartbeat_time"] = time.time()
        state["last_lease_value"] = lease_value
        state["missed_count"] = 0
        state["status"] = "healthy"

    def check_lease(
        self,
        bus_id: str,
        is_trunk_node: bool = False,
        current_time: Optional[float] = None,
    ) -> bool:
        """检查指定总线的租约是否仍然有效

        Args:
            bus_id: 总线 ID
            is_trunk_node: 该节点是否为主干节点（同时作为子总线的 Master）
            current_time: 当前时间戳（用于测试注入）

        Returns:
            True 若租约有效，False 若租约已过期
        """
        if bus_id not in self._watch_state:
            return True  # 未注册的视为有效（尚未开始监控）

        state = self._watch_state[bus_id]
        now = current_time if current_time is not None else time.time()

        # 计算宽限期
        grace_period_ms = compute_grace_period(
            heartbeat_interval_ms=self.heartbeat_interval_ms,
            max_missed=self.max_missed_heartbeats,
            is_trunk_node=is_trunk_node,
            grace_multiplier=self.trunk_grace_multiplier,
        )
        grace_period_s = grace_period_ms / 1000.0

        elapsed = now - state["last_heartbeat_time"]

        if elapsed > grace_period_s:
            state["missed_count"] += 1
            state["status"] = "expired"
            return False

        return True

    def is_expired(self, bus_id: str) -> bool:
        """简化的租约过期查询"""
        if bus_id not in self._watch_state:
            return False
        return self._watch_state[bus_id].get("status") == "expired"

    def get_missed_count(self, bus_id: str) -> int:
        """获取丢失心跳计数"""
        if bus_id not in self._watch_state:
            return 0
        return self._watch_state[bus_id].get("missed_count", 0)

    def reset(self, bus_id: str) -> None:
        """重置总线监控状态"""
        self._watch_state.pop(bus_id, None)
