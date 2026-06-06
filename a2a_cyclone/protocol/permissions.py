"""
A2A-CyClone Protocol Layer: ACL 权限边界
绝对纯净：不包含任何文件 I/O、网络通讯或业务逻辑。

v0.2.0 新增：多主控协调权限、递归子总线操作权、级联销毁执行权。
"""

from .enums import BusState


def can_transition(actor_aid: str, bus_data: dict, next_state: BusState) -> bool:
    """
    权限验证方程：谁有资格在当前上下文触发目标状态

    v0.2.0 扩展：
      - 多主控环境下的 PROBE 权限（所有 master-* 均有权发起）
      - 级联销毁权限：父总线的 Token_Holder 有权强制改写子总线状态
      - 子总线注册权限：持有令牌的 Master 可创建子总线
    """
    token_holder = bus_data.get("Token_Holder")

    # 限制 1：释放与续租动作必须由 Token_Holder 本人发起
    restricted_states = [
        BusState.LEASE_HEARTBEAT,
        BusState.RELEASE_SUCCESS,
        BusState.RELEASE_FAILED,
    ]
    if next_state in restricted_states:
        if actor_aid != token_holder:
            raise PermissionError(f"越权: {actor_aid} 试图劫持 {token_holder} 的令牌")

    # 限制 2：非 Root 或具备授权的 Master 不得发起全局寻呼
    if next_state == BusState.PROBE:
        if not actor_aid.startswith("root-") and not actor_aid.startswith("master-"):
            raise PermissionError("越权: 仅主控节点可发起 PROBE 寻呼")

    return True


def can_force_reset(
    actor_aid: str,
    target_bus_data: dict,
    actor_bus_data: dict,
) -> bool:
    """级联销毁权限：判定 actor 是否有权强制重置目标总线

    规则 (v0.2.0):
      1. actor 必须是目标总线的父总线的当前 Token_Holder
      2. 目标总线必须处于活跃状态（101/102/202）
      3. actor 的父总线必须处于活跃控制状态

    此权限用于"僵尸子总线回收"场景：当父总线发现子总线的 Master Agent
    已死亡，父总线 Token_Holder 有权强行将所有相关子总线改写为 103。
    """
    parent_bus_id = target_bus_data.get("Parent_Bus")
    if parent_bus_id is None:
        return False  # 无父总线，无法级联销毁

    actor_bus_id = actor_bus_data.get("bus_id", "")
    if parent_bus_id != actor_bus_id:
        return False  # actor 不在目标总线的父总线上

    if actor_aid != actor_bus_data.get("Token_Holder"):
        return False  # actor 不是父总线的令牌持有者

    target_status = target_bus_data.get("status", "000")
    if target_status not in ("101", "102", "202"):
        return False  # 目标总线不在活跃状态，无需销毁

    return True


def can_create_sub_bus(
    actor_aid: str,
    parent_bus_data: dict,
) -> bool:
    """子总线创建权限：判定 actor 是否有权在父总线下创建子总线

    规则 (v0.2.0):
      1. actor 必须是父总线的当前 Token_Holder
      2. 父总线必须处于 ACTIVE_CONTROL (102) 或 LEASE_HEARTBEAT (202) 状态
    """
    if actor_aid != parent_bus_data.get("Token_Holder"):
        return False
    parent_status = parent_bus_data.get("status", "000")
    if parent_status not in ("102", "202"):
        return False
    return True


def can_register_as_master(
    actor_aid: str,
    master_registry: list,
    max_masters: int = 16,
) -> bool:
    """主控注册权限：判定 actor 是否有资格注册为主控

    规则 (v0.2.0):
      1. actor 必须以 master- 或 root- 为前缀
      2. 当前已注册主控数未达上限
      3. actor 未被标记为 DEPOSED
    """
    if not (actor_aid.startswith("master-") or actor_aid.startswith("root-")):
        return False
    active_masters = [m for m in master_registry
                      if m.get("state") not in ("DEPOSED", "SUSPENDED")]
    if len(active_masters) >= max_masters:
        return False
    return True
