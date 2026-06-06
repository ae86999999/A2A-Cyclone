"""
A2A-Cyclone Protocol Layer: 全局账本事件定义 (Global Ledger)
绝对纯净：不包含任何文件 I/O、网络通讯或业务逻辑。

定义账本事件类型、事件结构与不可变性规则。
账本采用 append-only 模式，所有状态流转均作为不可变事件记录。
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Any, Dict
import uuid as _uuid_module  # 仅用于生成事件 ID 的 UUID 格式定义，非 I/O


class LedgerEventType(str, Enum):
    """账本事件类型：覆盖总线生命周期的完整事件谱系"""
    # 生命周期事件
    BUS_INITIALIZED = "BUS_INITIALIZED"            # 总线物理文件创建
    BUS_DESTROYED = "BUS_DESTROYED"                # 总线物理文件销毁

    # 状态流转事件
    STATE_TRANSITION = "STATE_TRANSITION"           # 状态机跃迁
    STATE_TRANSITION_REJECTED = "STATE_TRANSITION_REJECTED"  # 状态跃迁被拒绝（ACL/不变量阻断）

    # 令牌事件
    TOKEN_CLAIMED = "TOKEN_CLAIMED"                # 令牌被申领
    TOKEN_RELEASED = "TOKEN_RELEASED"              # 令牌被释放
    TOKEN_EXPIRED = "TOKEN_EXPIRED"                # 令牌租约过期被回收

    # 握手事件
    HANDSHAKE_INITIATED = "HANDSHAKE_INITIATED"    # 主控发起握手 (001)
    HANDSHAKE_ACKED = "HANDSHAKE_ACKED"            # 从控确认握手 (002)
    HANDSHAKE_CONFIRMED = "HANDSHAKE_CONFIRMED"    # 主控锁定角色 (101)
    HANDSHAKE_TIMEOUT = "HANDSHAKE_TIMEOUT"        # 握手超时

    # 租约事件
    LEASE_HEARTBEAT_SENT = "LEASE_HEARTBEAT_SENT"   # 续租心跳发出
    LEASE_HEARTBEAT_RECEIVED = "LEASE_HEARTBEAT_RECEIVED"  # 续租心跳被父总线收到
    LEASE_EXPIRED = "LEASE_EXPIRED"                # 租约过期

    # 异常事件
    FAILURE_ESCALATED = "FAILURE_ESCALATED"         # 异常向上级联击穿
    FAILURE_CONTAINED = "FAILURE_CONTAINED"         # 异常被局部阻断
    AGENT_LOST = "AGENT_LOST"                      # Agent 被判为不可达
    CASCADING_TEARDOWN = "CASCADING_TEARDOWN"      # 级联销毁信标触发

    # 拓扑事件
    SUB_BUS_CREATED = "SUB_BUS_CREATED"            # 子总线创建
    SUB_BUS_DETACHED = "SUB_BUS_DETACHED"          # 子总线解除挂载
    ORPHAN_DETECTED = "ORPHAN_DETECTED"            # 孤儿总线被检测到

    # 多主控事件
    MASTER_ELECTION = "MASTER_ELECTION"            # 主控选举
    MASTER_DEPOSED = "MASTER_DEPOSED"              # 主控被罢免
    MASTER_REGISTERED = "MASTER_REGISTERED"        # 主控注册
    MASTER_DEREGISTERED = "MASTER_DEREGISTERED"    # 主控注销

    # AID 事件
    AID_ALLOCATED = "AID_ALLOCATED"                # AID 分配
    AID_RELEASED = "AID_RELEASED"                  # AID 回收
    AID_CONFLICT = "AID_CONFLICT"                  # AID 冲突检测


@dataclass(frozen=True)
class LedgerEntry:
    """不可变账本条目

    一旦写入账本，任何字段不得修改。这是分布式审计的唯一可信记录。
    """
    event_id: str                                  # 全局唯一事件 ID (UUID v4 格式)
    event_type: LedgerEventType                    # 事件分类
    bus_id: str                                   # 事件来源总线
    agent_id: str                                 # 触发事件的 Agent
    timestamp_iso: str                            # ISO 8601 时间戳（由 Runtime 层注入）
    vector_clock: int                             # 事件发生时的逻辑时钟
    payload: Dict[str, Any] = field(default_factory=dict)  # 事件负载（可序列化字典）
    parent_event_id: Optional[str] = None          # 因果链：触发此事件的上游事件 ID
    correlation_id: Optional[str] = None           # 分布式追踪：贯穿多总线的关联 ID

    def is_causal_child_of(self, other: "LedgerEntry") -> bool:
        """判定本事件是否为 other 的因果后继"""
        return self.parent_event_id == other.event_id

    def same_trace(self, other: "LedgerEntry") -> bool:
        """判定两事件是否属于同一分布式追踪链"""
        if self.correlation_id is None or other.correlation_id is None:
            return False
        return self.correlation_id == other.correlation_id


# ---- 账本不变量 ----

def assert_ledger_invariants(entries: list) -> bool:
    """全局账本不变量校验

    规则：
      1. 事件 ID 必须全局唯一（无重复 event_id）
      2. 因果时钟单调性：同一总线上的事件，vector_clock 必须严格递增
      3. 因果完整性：若 parent_event_id 非空，引用的父事件必须存在

    纯函数：无 I/O。
    """
    seen_ids = set()
    bus_clocks: dict = {}  # bus_id -> max vector_clock seen

    # Build index of event_ids for parent validation
    all_event_ids = {e.event_id for e in entries if hasattr(e, 'event_id')}

    for entry in entries:
        # Rule 1: 事件 ID 唯一
        if entry.event_id in seen_ids:
            raise AssertionError(
                f"账本不变量违背: 重复的事件 ID '{entry.event_id}'"
            )
        seen_ids.add(entry.event_id)

        # Rule 2: 因果时钟单调性
        prev_clock = bus_clocks.get(entry.bus_id, -1)
        if entry.vector_clock <= prev_clock:
            raise AssertionError(
                f"账本不变量违背: 总线 '{entry.bus_id}' 上 vector_clock "
                f"非严格递增 ({prev_clock} -> {entry.vector_clock})"
            )
        bus_clocks[entry.bus_id] = entry.vector_clock

        # Rule 3: 因果完整性
        if entry.parent_event_id is not None and entry.parent_event_id not in all_event_ids:
            raise AssertionError(
                f"账本不变量违背: 事件 '{entry.event_id}' 引用了不存在的"
                f"父事件 '{entry.parent_event_id}'"
            )

    return True


def generate_event_id() -> str:
    """生成符合 UUID v4 格式的事件 ID 字符串

    纯函数：仅生成格式约定，不依赖系统随机源。
    Runtime 层调用时将替换为实际 UUID。
    """
    return f"evt_{_uuid_module.uuid4().hex}"
