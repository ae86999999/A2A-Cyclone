"""
A2A-Cyclone Protocol Layer: 多主控协调 (Multi-Master Coordination)
绝对纯净：不包含任何文件 I/O、网络通讯或业务逻辑。

定义多主控环境下的注册、选举、冲突仲裁与独占保证规则。
核心原则：同一物理总线同一时刻只能有一个 Active Master (102 状态)。
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List


class MasterRole(str, Enum):
    """主控节点在协调拓扑中的角色"""
    PRIMARY = "PRIMARY"        # 主 Master：持有令牌，可发号施令
    STANDBY = "STANDBY"       # 备 Master：注册在案，等待令牌释放
    CANDIDATE = "CANDIDATE"   # 候选 Master：竞选令牌中
    DEPOSED = "DEPOSED"       # 被罢免：因异常被强制剥夺候选资格


class MasterState(str, Enum):
    """主控节点内部状态"""
    IDLE = "IDLE"                      # 空闲，未注册
    REGISTERED = "REGISTERED"          # 已注册到主控注册表
    CAMPAIGNING = "CAMPAIGNING"        # 竞选中（已发起 PROBE）
    ACTIVE = "ACTIVE"                  # 已获得令牌，可发号施令
    SUPERVISING = "SUPERVISING"        # 监督中（监控其他 Master 的心跳）
    SUSPENDED = "SUSPENDED"            # 被暂停（因冲突被仲裁降级）


@dataclass(frozen=True)
class MasterNode:
    """主控节点注册信息"""
    master_id: str
    role: MasterRole = MasterRole.CANDIDATE
    state: MasterState = MasterState.IDLE
    priority: int = 0                  # 优先级（数值越大越优先）
    registered_at_clock: int = 0       # 注册时的逻辑时钟
    last_heartbeat_clock: int = 0      # 最后一次心跳的逻辑时钟
    managed_bus_ids: List[str] = field(default_factory=list)  # 该 Master 管理的总线列表


# ---- 主控选举规则 ----

def elect_primary(
    candidates: List[MasterNode],
    max_heartbeat_gap: int = 3,
) -> Optional[MasterNode]:
    """主控选举算法：从候选列表中选出 PRIMARY Master

    选举规则（按优先级降序）：
      1. 排除心跳超时的候选者（last_heartbeat_clock 差距 > max_heartbeat_gap）
      2. 剩余候选者中选 priority 最高者
      3. 若 priority 相同，选 registered_at_clock 最早者（先到先得）
      4. 若都相同，按 master_id 字典序（确定性 tie-breaker）

    纯函数：无 I/O，无副作用。
    """
    # Filter out candidates with stale heartbeats
    max_clock = max((c.last_heartbeat_clock for c in candidates), default=0)
    active_candidates = [
        c for c in candidates
        if (max_clock - c.last_heartbeat_clock) <= max_heartbeat_gap
    ]

    if not active_candidates:
        return None

    # Sort by: priority DESC, registered_at_clock ASC, master_id ASC
    active_candidates.sort(key=lambda c: (-c.priority, c.registered_at_clock, c.master_id))
    return active_candidates[0]


def validate_master_exclusivity(
    bus_status: str,
    current_token_holder: Optional[str],
    requesting_master_id: str,
) -> bool:
    """总线独占验证：确保同一总线只有一个 Active Master

    规则：
      1. 若总线处于 102/202 状态且 Token_Holder 非请求者 → 拒绝
      2. 若总线处于 101 状态（Slave 已锁定）且请求者非 Token_Holder → 拒绝
      3. 否则允许

    纯函数：无 I/O。
    """
    if bus_status in ("102", "202"):
        if current_token_holder != requesting_master_id:
            return False
    if bus_status == "101":
        if current_token_holder is not None and current_token_holder != requesting_master_id:
            return False
    return True


def resolve_master_conflict(
    master_a: MasterNode,
    master_b: MasterNode,
    current_vector_clock: int,
) -> MasterNode:
    """多主控冲突仲裁

    当两个 Master 同时尝试对同一总线写入 001 (PROBE) 时：
      1. 高 priority 者胜出
      2. 同 priority 时，先注册者（smaller registered_at_clock）胜出
      3. 完全相同时，master_id 字典序小者胜出

    失败者应被降级为 DEPOSED 并重新注册。

    纯函数：无 I/O。
    """
    if master_a.priority != master_b.priority:
        return master_a if master_a.priority > master_b.priority else master_b
    if master_a.registered_at_clock != master_b.registered_at_clock:
        return master_a if master_a.registered_at_clock < master_b.registered_at_clock else master_b
    return master_a if master_a.master_id < master_b.master_id else master_b


def is_master_alive(
    master: MasterNode,
    current_vector_clock: int,
    max_heartbeat_gap: int = 3,
) -> bool:
    """判定主控是否存活

    若 Master 的最后心跳与当前时钟差距超过阈值，判定为失活。
    纯函数：无 I/O。
    """
    return (current_vector_clock - master.last_heartbeat_clock) <= max_heartbeat_gap
