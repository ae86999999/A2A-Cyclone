"""
A2A-cyClone Protocol Layer: 纯拓扑流转状态机
仅定义物理连接拓扑图，不涉及权限与业务逻辑。
"""

from .enums import BusState


class StateMachine:
    """有限状态机：仅定义物理连接拓扑图，不涉及权限与业务"""

    VALID_TRANSITIONS = {
        BusState.UNINITIALIZED: [BusState.PROBE],
        BusState.PROBE: [BusState.HANDSHAKE_ACK, BusState.UNINITIALIZED],
        BusState.HANDSHAKE_ACK: [BusState.SLAVE_PASSIVE, BusState.UNINITIALIZED],
        BusState.SLAVE_PASSIVE: [BusState.ACTIVE_CONTROL, BusState.UNINITIALIZED],
        BusState.ACTIVE_CONTROL: [
            BusState.LEASE_HEARTBEAT,
            BusState.RELEASE_SUCCESS,
            BusState.RELEASE_FAILED
        ],
        BusState.LEASE_HEARTBEAT: [
            BusState.LEASE_HEARTBEAT,
            BusState.RELEASE_SUCCESS,
            BusState.RELEASE_FAILED
        ],
        BusState.RELEASE_SUCCESS: [BusState.UNINITIALIZED],
        BusState.RELEASE_FAILED: [BusState.UNINITIALIZED]
    }

    @staticmethod
    def validate_transition(current_state: BusState, next_state: BusState) -> bool:
        allowed = StateMachine.VALID_TRANSITIONS.get(current_state, [])
        if next_state not in allowed:
            raise ValueError(f"非法跃迁: {current_state} -> {next_state}")
        return True
