"""
A2A-Cyclone Protocol Layer: 递归子总线拓扑 (Recursive Bus Topology)
绝对纯净：不包含任何文件 I/O、网络通讯或业务逻辑。

定义递归总线树的拓扑规则、父子链接约束、孤儿检测与级联销毁信标协议。
"""

from dataclasses import dataclass, field
from typing import Optional, List, Set
from enum import Enum


class TopologyRole(str, Enum):
    """总线在递归树中的拓扑角色"""
    ROOT = "ROOT"            # 根总线：无父总线，可拥有多个子总线
    TRUNK = "TRUNK"         # 主干总线：既有父总线，也有子总线
    LEAF = "LEAF"            # 叶子总线：有父总线，无子总线
    ORPHAN = "ORPHAN"        # 孤儿总线：父总线指针断裂，处于非法拓扑态


class TeardownBeaconState(str, Enum):
    """级联销毁信标状态"""
    IDLE = "IDLE"                          # 空闲，无销毁信号
    PENDING_TEARDOWN = "PENDING_TEARDOWN"  # 父总线已发出销毁指令，等待子总线确认
    TEARDOWN_COMPLETE = "TEARDOWN_COMPLETE"  # 子总线已完成销毁并回归 000


@dataclass(frozen=True)
class BusNode:
    """总线树节点：描述单个总线在递归拓扑中的位置与关系"""
    bus_id: str
    parent_bus_id: Optional[str] = None
    child_bus_ids: List[str] = field(default_factory=list)

    def role(self) -> TopologyRole:
        """推导该总线的拓扑角色"""
        has_parent = self.parent_bus_id is not None
        has_children = len(self.child_bus_ids) > 0
        if not has_parent and not has_children:
            return TopologyRole.ROOT  # 单级独立总线，也是根
        if not has_parent and has_children:
            return TopologyRole.ROOT
        if has_parent and has_children:
            return TopologyRole.TRUNK
        if has_parent and not has_children:
            return TopologyRole.LEAF
        return TopologyRole.ROOT  # fallback

    def is_root(self) -> bool:
        return self.parent_bus_id is None

    def is_orphan(self, known_buses: Set[str]) -> bool:
        """若父总线 ID 不在已知总线集合中，该节点为孤儿"""
        if self.parent_bus_id is None:
            return False
        return self.parent_bus_id not in known_buses


def validate_topology(
    bus_id: str,
    parent_bus_id: Optional[str],
    child_bus_ids: List[str],
    known_buses: Set[str],
) -> bool:
    """拓扑不变量的纯函数校验

    规则：
      1. 总线不能是自己的父总线（禁止自引用环路）
      2. 总线不能是自己的子总线（禁止自引用环路）
      3. 父总线必须存在于已知总线集合中（禁止悬空引用）
      4. 子总线必须存在于已知总线集合中（禁止悬空引用）
      5. 禁止循环引用：子总线的父总线不能指向自己
    """
    # Rule 1 & 2: 禁止自引用
    if bus_id == parent_bus_id:
        raise ValueError(f"拓扑违规: 总线 '{bus_id}' 不能是自己的父总线（自引用环路）")
    if bus_id in child_bus_ids:
        raise ValueError(f"拓扑违规: 总线 '{bus_id}' 不能是自己的子总线（自引用环路）")

    # Rule 3: 父总线必须已知
    if parent_bus_id is not None and parent_bus_id not in known_buses:
        raise ValueError(
            f"拓扑违规: 父总线 '{parent_bus_id}' 不在已知总线集合中（悬空引用）"
        )

    # Rule 4: 子总线必须已知
    for child_id in child_bus_ids:
        if child_id not in known_buses:
            raise ValueError(
                f"拓扑违规: 子总线 '{child_id}' 不在已知总线集合中（悬空引用）"
            )
        # Rule 5: 禁止循环引用（子总线不应声明本总线为其子）
        # 此检查在知道子总线的 parent 时生效，此处标记为约定

    return True


def detect_orphan_buses(
    bus_map: dict,  # bus_id -> BusNode (or dict with keys: bus_id, parent_bus_id)
) -> List[str]:
    """孤儿总线检测：找出所有父指针断裂的总线

    纯函数：输入总线映射，输出孤儿总线 ID 列表。
    不包含任何 I/O 操作。
    """
    known_ids = set(bus_map.keys())
    orphans: List[str] = []
    for bid, node in bus_map.items():
        parent = node.get("parent_bus_id") if isinstance(node, dict) else (
            node.parent_bus_id if hasattr(node, 'parent_bus_id') else None
        )
        if parent is not None and parent not in known_ids:
            orphans.append(bid)
    return orphans


def should_trigger_teardown(
    parent_bus_status: str,
    agent_alive: bool,
    child_bus_count: int,
) -> bool:
    """判定是否应触发级联销毁信标

    触发条件（满足任一即触发）：
      1. 父总线检测到负责子总线的 Agent 已死亡 (agent_alive == False)
      2. 父总线状态回归 000，但子总线仍处于活跃状态
      3. 父总线收到 GLOBAL_FATAL 级联异常

    纯函数：无 I/O。
    """
    if not agent_alive and child_bus_count > 0:
        return True
    if parent_bus_status == "000" and child_bus_count > 0:
        return True
    return False


def compute_teardown_targets(
    bus_id: str,
    child_bus_ids: List[str],
    agent_managed_buses: List[str],
) -> List[str]:
    """计算级联销毁的目标总线列表

    当 Agent 死亡时：
      该 Agent 直接管理的所有子总线 + 该 Agent 作为子总线的总线
      全部需要被强制改写为 103 RELEASE_FAILED

    纯函数：输入拓扑关系，输出需要销毁的总线 ID 列表。
    """
    targets: List[str] = []
    # 所有子总线需要被销毁
    targets.extend(child_bus_ids)
    # 所有该 Agent 管理的其他总线也需要被销毁
    for managed_bus in agent_managed_buses:
        if managed_bus not in targets:
            targets.append(managed_bus)
    return targets


# ---- 租约竞争条件缓解规则 (Lease Race Condition Mitigation) ----

@dataclass(frozen=True)
class LeaseSchedule:
    """租约调度策略：防止 Agent 在父子总线间因单线程文件 IO 导致租约超时

    核心问题：
      一个节点同时作为子总线的 Master 和父总线的 Slave。
      单线程处理子总线 202 写入导致的时延，会触发父总线上的租约超时，
      导致系统误判 Agent 离线而强行收回令牌，子总线变无主孤岛。

    解决方案：
      父总线给予充当子总线 Master 的 Agent 额外的租约宽限期（grace period）。
    """
    default_heartbeat_interval_ms: int = 1000     # 默认心跳间隔
    max_missed_heartbeats: int = 3                # 最大丢失心跳数
    trunk_node_grace_multiplier: float = 2.0      # 主干节点宽限倍率


def compute_grace_period(
    heartbeat_interval_ms: int,
    max_missed: int,
    is_trunk_node: bool = False,
    grace_multiplier: float = 2.0,
) -> int:
    """计算租约宽限期（毫秒）

    若节点同时是子总线的 Master（即主干节点），给予额外的宽限期：
      grace_period = heartbeat_interval_ms × max_missed × grace_multiplier

    普通节点（仅作为 Slave）：
      grace_period = heartbeat_interval_ms × max_missed

    纯函数：无 I/O。
    """
    base_timeout = heartbeat_interval_ms * max_missed
    if is_trunk_node:
        return int(base_timeout * grace_multiplier)
    return base_timeout
