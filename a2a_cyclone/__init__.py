# A2A-Cyclone
# Licensed under Apache License 2.0
#
# v0.2.0: 新增失败传播协议、递归子总线拓扑、全局账本、
#         多主控协调、动态 AID 分配五大子系统。
#         引入 Runtime Layer (BusManager, LeaseWatcher,
#         TeardownHandler, LedgerWriter)。
#
# v0.3.0: 新增 Adapter Layer (SlaveAdapter 接口契约、
#         ShellAdapter、ClaudeCodeAdapter、AdapterRegistry)。

from .protocol import (
    # enums
    BusState,
    # state_machine
    StateMachine,
    # permissions
    can_transition,
    can_force_reset,
    can_create_sub_bus,
    can_register_as_master,
    # invariants
    assert_invariants,
    assert_vector_clock_monotonicity,
    assert_topology_integrity,
    assert_cascade_completeness,
    assert_ledger_consistency,
)

from .adapter import (
    SlaveStatus,
    SlaveAdapter,
    TaskPackage,
    TaskResult,
    AdapterRegistry,
    ShellAdapter,
    ClaudeCodeAdapter,
)

__all__ = [
    # protocol
    "BusState",
    "StateMachine",
    "can_transition",
    "can_force_reset",
    "can_create_sub_bus",
    "can_register_as_master",
    "assert_invariants",
    "assert_vector_clock_monotonicity",
    "assert_topology_integrity",
    "assert_cascade_completeness",
    "assert_ledger_consistency",
    # adapter
    "SlaveStatus",
    "SlaveAdapter",
    "TaskPackage",
    "TaskResult",
    "AdapterRegistry",
    "ShellAdapter",
    "ClaudeCodeAdapter",
]
