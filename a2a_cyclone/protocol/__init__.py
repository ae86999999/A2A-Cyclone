# A2A-Cyclone Protocol Layer - Pure Definitions
# Licensed under Apache License 2.0
#
# v0.2.0: 新增失败传播协议、递归子总线拓扑、全局账本、
#         多主控协调、动态 AID 分配五大子系统。
#
# 本层绝对不包含任何文件 I/O、网络通讯或业务逻辑。
# 所有模块均为纯函数与数据结构定义。

from .enums import BusState
from .state_machine import StateMachine
from .permissions import (
    can_transition,
    can_force_reset,
    can_create_sub_bus,
    can_register_as_master,
)
from .invariants import (
    assert_invariants,
    assert_vector_clock_monotonicity,
    assert_topology_integrity,
    assert_cascade_completeness,
    assert_ledger_consistency,
)

__all__ = [
    # enums
    "BusState",
    # state_machine
    "StateMachine",
    # permissions
    "can_transition",
    "can_force_reset",
    "can_create_sub_bus",
    "can_register_as_master",
    # invariants
    "assert_invariants",
    "assert_vector_clock_monotonicity",
    "assert_topology_integrity",
    "assert_cascade_completeness",
    "assert_ledger_consistency",
]
