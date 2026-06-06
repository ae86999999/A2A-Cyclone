"""
A2A-Cyclone Protocol Layer: 动态 AID 分配 (Dynamic AID Pool)
绝对纯净：不包含任何文件 I/O、网络通讯或业务逻辑。

定义 Agent ID 的命名规范、池化分配规则、回收策略与冲突检测。
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Set


class AgentRole(str, Enum):
    """Agent 角色分类（由 AID 前缀决定）"""
    ROOT = "root"         # 系统根节点（全局唯一）
    MASTER = "master"     # 主控调度节点
    SLAVE = "slave"       # 从控执行节点
    ADAPTER = "adapter"   # 适配器节点（被动监听）


# AID 命名规范常量
AID_SEPARATOR = "-"
AID_PREFIX_MAP = {
    AgentRole.ROOT: "root",
    AgentRole.MASTER: "master",
    AgentRole.SLAVE: "slave",
    AgentRole.ADAPTER: "adapter",
}

# AID 池容量限制
MAX_AID_PER_ROLE: dict = {
    AgentRole.ROOT: 1,        # 全系统只有一个 root
    AgentRole.MASTER: 16,     # 最多 16 个主控
    AgentRole.SLAVE: 256,     # 最多 256 个从控
    AgentRole.ADAPTER: 64,    # 最多 64 个适配器
}


@dataclass(frozen=True)
class AidAllocation:
    """AID 分配记录"""
    aid: str
    role: AgentRole
    sequence_number: int             # 递增序号（同角色内唯一）
    allocated_at_clock: int          # 分配时的逻辑时钟
    released: bool = False           # 是否已回收
    released_at_clock: int = 0       # 回收时的逻辑时钟


# ---- AID 命名与解析 ----

def build_aid(role: AgentRole, unique_id: str) -> str:
    """构造符合规范的 AID 字符串

    格式: {prefix}-{unique_id}
    示例: master-001, slave-keil-armcc, adapter-llm-gpt

    纯函数：无 I/O。
    """
    prefix = AID_PREFIX_MAP[role]
    return f"{prefix}{AID_SEPARATOR}{unique_id}"


def parse_aid(aid: str) -> Optional[AgentRole]:
    """从 AID 字符串推导 Agent 角色

    纯函数：无 I/O。
    """
    for role, prefix in AID_PREFIX_MAP.items():
        if aid.startswith(f"{prefix}{AID_SEPARATOR}"):
            return role
    return None


def is_master_aid(aid: str) -> bool:
    """判定 AID 是否属于主控节点"""
    return aid.startswith(f"{AID_PREFIX_MAP[AgentRole.MASTER]}{AID_SEPARATOR}")


def is_root_aid(aid: str) -> bool:
    """判定 AID 是否为根节点"""
    return aid.startswith(f"{AID_PREFIX_MAP[AgentRole.ROOT]}{AID_SEPARATOR}")


def is_slave_aid(aid: str) -> bool:
    """判定 AID 是否为从控节点"""
    return aid.startswith(f"{AID_PREFIX_MAP[AgentRole.SLAVE]}{AID_SEPARATOR}")


# ---- AID 池管理规则 ----

def can_allocate(
    role: AgentRole,
    current_allocations: int,
    max_capacity: Optional[int] = None,
) -> bool:
    """判定是否可以为指定角色分配新的 AID

    纯函数：无 I/O。
    """
    cap = max_capacity if max_capacity is not None else MAX_AID_PER_ROLE[role]
    return current_allocations < cap


def generate_sequence_number(
    role: AgentRole,
    existing_aids: Set[str],
    preferred: Optional[int] = None,
) -> int:
    """为指定角色生成下一个可用的序号

    策略：取最小未被占用的非负整数序号。
    若指定 preferred 且未被占用，优先使用。

    纯函数：无 I/O。
    """
    # 收集该角色已占用的序号
    prefix = f"{AID_PREFIX_MAP[role]}{AID_SEPARATOR}"
    used_numbers: Set[int] = set()
    for aid in existing_aids:
        if aid.startswith(prefix):
            try:
                seq_str = aid[len(prefix):]
                # 仅处理纯数字后缀的 AID
                num = int(seq_str)
                used_numbers.add(num)
            except ValueError:
                pass  # 非纯数字后缀（如 adapter-llm-gpt），不参与序号竞争

    # 若 preferred 可用，直接返回
    if preferred is not None and preferred not in used_numbers:
        return preferred

    # 找最小可用序号
    seq = 0
    while seq in used_numbers:
        seq += 1
    return seq


def validate_aid_uniqueness(
    aid: str,
    existing_aids: Set[str],
) -> bool:
    """AID 唯一性校验

    全局范围内，AID 必须唯一。重复 AID 会导致令牌归属歧义。

    纯函数：无 I/O。
    """
    if aid in existing_aids:
        raise ValueError(f"AID 冲突: '{aid}' 已被分配，禁止重复使用")
    return True


def validate_aid_format(aid: str) -> bool:
    """AID 格式校验

    规则：
      1. 必须包含 AID_SEPARATOR ("-")
      2. 前缀必须是合法的 AgentRole 前缀
      3. 后缀不能为空
      4. 总长度不超过 128 字符
      5. 仅允许 ASCII 字母、数字、连字符、下划线

    纯函数：无 I/O。
    """
    if AID_SEPARATOR not in aid:
        raise ValueError(f"AID 格式非法: '{aid}' 缺少分隔符 '{AID_SEPARATOR}'")
    if len(aid) > 128:
        raise ValueError(f"AID 格式非法: '{aid}' 超过 128 字符上限")

    role = parse_aid(aid)
    if role is None:
        raise ValueError(
            f"AID 格式非法: '{aid}' 的前缀不在合法角色前缀列表 "
            f"{list(AID_PREFIX_MAP.values())} 中"
        )

    suffix = aid[len(AID_PREFIX_MAP[role]) + len(AID_SEPARATOR):]
    if not suffix:
        raise ValueError(f"AID 格式非法: '{aid}' 的后缀为空")

    # 仅允许安全字符
    allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    for ch in aid:
        if ch not in allowed_chars:
            raise ValueError(f"AID 格式非法: '{aid}' 包含非法字符 '{ch}'")

    return True
