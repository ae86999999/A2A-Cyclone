"""
A2A-cyClone Protocol Layer: ACL 权限边界
绝对纯净：不包含任何文件 I/O、网络通讯或业务逻辑。
"""

from .enums import BusState


def can_transition(actor_aid: str, bus_data: dict, next_state: BusState) -> bool:
    """
    权限验证方程：谁有资格在当前上下文触发目标状态
    """
    token_holder = bus_data.get("Token_Holder")

    # 限制 1：释放与续租动作必须由 Token_Holder 本人发起
    restricted_states = [
        BusState.LEASE_HEARTBEAT,
        BusState.RELEASE_SUCCESS,
        BusState.RELEASE_FAILED
    ]
    if next_state in restricted_states:
        if actor_aid != token_holder:
            raise PermissionError(f"越权: {actor_aid} 试图劫持 {token_holder} 的令牌")

    # 限制 2：非 Root 或具备授权的 Master 不得发起全局寻呼
    if next_state == BusState.PROBE:
        if not actor_aid.startswith("root-") and not actor_aid.startswith("master-"):
            raise PermissionError("越权: 仅主控节点可发起 PROBE 寻呼")

    return True
