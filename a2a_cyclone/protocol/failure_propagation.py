"""
A2A-Cyclone Protocol Layer: 失败传播协议 (Failure Propagation Protocol)
绝对纯净：不包含任何文件 I/O、网络通讯或业务逻辑。

核心模型：
  E_parent = E_child × M_criticality

  其中:
    E_parent  — 父总线接收到的异常状态矩阵
    E_child   — 子总线抛出的异常特征（如 103 Failed 状态码及错误信息）
    M_criticality — 致命性系数掩码：0 = 局部可重试，异常被阻断；1 = 全局致命，击穿父总线状态池
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


class CriticalityMask(int, Enum):
    """致命性系数掩码：决定异常是局部消化还是向上级联击穿"""
    LOCAL_RETRYABLE = 0   # 局部可重试，异常被阻断在子总线内
    GLOBAL_FATAL = 1      # 全局致命，异常直接击穿父总线状态池


class FailureCategory(str, Enum):
    """异常分类：用于指导 Runtime 层的恢复策略"""
    TRANSIENT_TIMEOUT = "TRANSIENT_TIMEOUT"        # 瞬时超时（可重试）
    LEASE_EXPIRED = "LEASE_EXPIRED"               # 租约过期
    PERMISSION_DENIED = "PERMISSION_DENIED"        # 权限越界
    INVARIANT_VIOLATION = "INVARIANT_VIOLATION"    # 不变量违背
    AGENT_UNREACHABLE = "AGENT_UNREACHABLE"        # 节点不可达（物理断电/网络隔离）
    CORRUPTED_BUS = "CORRUPTED_BUS"               # 总线文件损坏
    CASCADING_FAILURE = "CASCADING_FAILURE"        # 级联故障（子总线异常向上传播）


@dataclass(frozen=True)
class FailureSignal:
    """异常信号：子总线向父总线传播的失败特征

    遵循 E_parent = E_child × M_criticality 方程：
      若 M_criticality == 0 (LOCAL_RETRYABLE): 异常被阻断，父总线不受影响
      若 M_criticality == 1 (GLOBAL_FATAL):     异常击穿，父总线状态池被感染
    """
    category: FailureCategory
    source_bus_id: str                           # 抛出异常的总线 ID
    source_agent_id: str                         # 抛出异常的 Agent ID
    error_code: str                              # 原始错误码（如 "103"）
    error_message: str                           # 人类可读的错误描述
    criticality: CriticalityMask = CriticalityMask.LOCAL_RETRYABLE
    parent_bus_id: Optional[str] = None          # 目标父总线 ID（用于级联路由）

    def should_escalate(self) -> bool:
        """判定是否应向父总线传播：仅 GLOBAL_FATAL 级别击穿"""
        return self.criticality == CriticalityMask.GLOBAL_FATAL

    def escalate(self) -> Optional["FailureSignal"]:
        """生成父总线级别的异常信号（级联传播方程）

        若不应传播，返回 None 表示异常已被子总线局部消化。
        """
        if not self.should_escalate():
            return None
        return FailureSignal(
            category=FailureCategory.CASCADING_FAILURE,
            source_bus_id=self.source_bus_id,
            source_agent_id=self.source_agent_id,
            error_code="103",
            error_message=(
                f"[Cascading] Child bus '{self.source_bus_id}' "
                f"reported fatal error: {self.error_message}"
            ),
            criticality=CriticalityMask.GLOBAL_FATAL,
            parent_bus_id=self.parent_bus_id,
        )


def classify_failure(
    status_code: str,
    lease_expired: bool = False,
    permission_error: bool = False,
    invariant_broken: bool = False,
    agent_lost: bool = False,
) -> FailureCategory:
    """根据运行时上下文，将原始状态码归类为结构化异常类型

    纯函数：输入状态码与运行时标志，输出异常分类。
    不包含任何 I/O 或状态写入。
    """
    if agent_lost:
        return FailureCategory.AGENT_UNREACHABLE
    if invariant_broken:
        return FailureCategory.INVARIANT_VIOLATION
    if permission_error:
        return FailureCategory.PERMISSION_DENIED
    if lease_expired:
        return FailureCategory.LEASE_EXPIRED
    if status_code == "103":
        return FailureCategory.TRANSIENT_TIMEOUT
    return FailureCategory.CORRUPTED_BUS


def determine_criticality(
    category: FailureCategory,
    is_root_bus: bool = False,
) -> CriticalityMask:
    """根据异常类型与总线层级，决定致命性掩码

    规则：
      - AGENT_UNREACHABLE / INVARIANT_VIOLATION: 全局致命（必须级联击穿）
      - LEASE_EXPIRED: 子总线可局部重试，根总线则为致命
      - 其余：默认局部可重试
    """
    if category in (FailureCategory.AGENT_UNREACHABLE,
                    FailureCategory.INVARIANT_VIOLATION):
        return CriticalityMask.GLOBAL_FATAL
    if category == FailureCategory.LEASE_EXPIRED and is_root_bus:
        return CriticalityMask.GLOBAL_FATAL
    return CriticalityMask.LOCAL_RETRYABLE


def compute_cascading_impact(
    child_signal: FailureSignal,
    parent_bus_id: str,
) -> Optional[FailureSignal]:
    """级联影响计算：将子总线异常信号通过致命性掩码投射到父总线

    这是 E_parent = E_child × M_criticality 方程的完整实现。
    返回 None 表示异常被阻断（局部可消化）。
    """
    if not child_signal.should_escalate():
        return None
    escalated = child_signal.escalate()
    if escalated is not None:
        # 将 parent_bus_id 显式绑定为传入的父总线 ID
        object.__setattr__(escalated, 'parent_bus_id', parent_bus_id)
    return escalated
