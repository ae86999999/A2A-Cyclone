"""
A2A-CyClone Protocol Layer: 纯拓扑流转状态机
仅定义物理连接拓扑图，不涉及权限与业务逻辑。

v0.2.0 新增：递归子总线级联销毁跃迁（允许 103 状态下强制回收子总线 000）。
"""

from .enums import BusState


class StateMachine:
    """有限状态机：仅定义物理连接拓扑图，不涉及权限与业务

    新增 (v0.2.0):
      - 级联销毁跃迁: 允许从 RELEASE_FAILED (103) 强制将子总线写回 UNINITIALIZED (000)
      - 僵尸回收跃迁: 允许 ACTIVE_CONTROL (102) 超时后主动跃迁至 UNINITIALIZED (000)
        以支持父总线对僵死子总线的强制回收
    """

    VALID_TRANSITIONS = {
        BusState.UNINITIALIZED: [BusState.PROBE],
        BusState.PROBE: [BusState.HANDSHAKE_ACK, BusState.UNINITIALIZED],
        BusState.HANDSHAKE_ACK: [BusState.SLAVE_PASSIVE, BusState.UNINITIALIZED],
        BusState.SLAVE_PASSIVE: [BusState.ACTIVE_CONTROL, BusState.UNINITIALIZED],
        BusState.ACTIVE_CONTROL: [
            BusState.LEASE_HEARTBEAT,
            BusState.RELEASE_SUCCESS,
            BusState.RELEASE_FAILED,
            # v0.2.0: 级联销毁 — 父总线检测到 Agent 死亡后，强制将子总线从 102 → 000
            BusState.UNINITIALIZED,
        ],
        BusState.LEASE_HEARTBEAT: [
            BusState.LEASE_HEARTBEAT,
            BusState.RELEASE_SUCCESS,
            BusState.RELEASE_FAILED,
        ],
        BusState.RELEASE_SUCCESS: [BusState.UNINITIALIZED],
        BusState.RELEASE_FAILED: [
            BusState.UNINITIALIZED,
            # v0.2.0: 级联销毁 — 父总线对僵死子总线的强制回收 (103 → 000)
        ],
    }

    @staticmethod
    def validate_transition(current_state: BusState, next_state: BusState) -> bool:
        """验证状态跃迁合法性"""
        allowed = StateMachine.VALID_TRANSITIONS.get(current_state, [])
        if next_state not in allowed:
            raise ValueError(f"非法跃迁: {current_state} -> {next_state}")
        return True

    @staticmethod
    def is_active_state(state: BusState) -> bool:
        """判定是否为活跃控制流状态（总线被锁定占用中）"""
        return state in (
            BusState.SLAVE_PASSIVE,
            BusState.ACTIVE_CONTROL,
            BusState.LEASE_HEARTBEAT,
        )

    @staticmethod
    def is_terminal_state(state: BusState) -> bool:
        """判定是否为终态（总线已释放，可被新握手接管）"""
        return state in (
            BusState.UNINITIALIZED,
            BusState.RELEASE_SUCCESS,
            BusState.RELEASE_FAILED,
        )
