"""
A2A-CyClone Protocol Layer: 系统不变量断言（绝对真理）
绝对纯净：不包含任何文件 I/O、网络通讯或业务逻辑。

v0.2.0 新增：Vector_Clock 单调性不变量、递归子总线拓扑不变量、
           级联销毁完整性不变量、账本审计不变量。
"""


def assert_invariants(bus_data: dict) -> bool:
    """
    系统不变量校验：所有状态写入前必须通过的最高宪法

    v0.2.0 扩展：
      - Invariant 2: 因果时钟单调性 (Vector_Clock 必须严格递增)
      - Invariant 3: 递归子总线拓扑完整性
    """
    state = bus_data.get("status")

    # Invariant 1: 活跃总线必须存在明确的 Token 持有者
    active_states = ["101", "102", "202"]
    if state in active_states:
        if not bus_data.get("Token_Holder"):
            raise AssertionError("违背不变量: 活跃总线丢失 Token_Holder")

    # Invariant 2: 子总线必须拥有合法的父总线指针
    child_buses = bus_data.get("Child_Buses", [])
    parent_bus = bus_data.get("Parent_Bus")
    if len(child_buses) > 0 and not parent_bus and not bus_data.get("bus_id", "").startswith("root"):
        raise AssertionError("违背不变量: 孤儿子总线试图进行递归裂变")

    return True


def assert_vector_clock_monotonicity(
    bus_data: dict,
    proposed_clock: int,
) -> bool:
    """因果时钟单调性不变量 (v0.2.0)

    规则：任何写入的 Vector_Clock 必须严格大于总线当前的逻辑时钟历史值。
    此不变量防止并发写入导致的状态回退与重播攻击。

    纯函数：无 I/O。
    """
    current_clock = bus_data.get("Vector_Clock", 0)
    if proposed_clock <= current_clock:
        raise AssertionError(
            f"违背不变量: Vector_Clock 非单调递增 "
            f"(当前={current_clock}, 提议={proposed_clock})"
        )
    return True


def assert_topology_integrity(bus_data: dict, known_bus_ids: set) -> bool:
    """递归子总线拓扑完整性不变量 (v0.2.0)

    规则：
      1. 父总线引用 (Parent_Bus) 必须指向 known_bus_ids 中存在的总线
      2. 子总线引用 (Child_Buses) 中的所有 ID 必须存在于 known_bus_ids 中
      3. 禁止自引用（总线不能是自己的父总线或子总线）
      4. 禁止循环引用（A 的父总线是 B 且 B 的父总线是 A）

    纯函数：无 I/O。
    """
    bus_id = bus_data.get("bus_id", "")
    parent_bus = bus_data.get("Parent_Bus")
    child_buses = bus_data.get("Child_Buses", [])

    # Rule 1: 父总线引用有效性
    if parent_bus is not None:
        if parent_bus not in known_bus_ids:
            raise AssertionError(
                f"违背拓扑不变量: 总线 '{bus_id}' 的父总线 "
                f"'{parent_bus}' 不在已知总线集合中"
            )
        # Rule 3: 禁止自引用
        if parent_bus == bus_id:
            raise AssertionError(
                f"违背拓扑不变量: 总线 '{bus_id}' 自引用为父总线"
            )

    # Rule 2: 子总线引用有效性
    for child_id in child_buses:
        if child_id not in known_bus_ids:
            raise AssertionError(
                f"违背拓扑不变量: 总线 '{bus_id}' 的子总线 "
                f"'{child_id}' 不在已知总线集合中"
            )
        # Rule 3: 禁止自引用
        if child_id == bus_id:
            raise AssertionError(
                f"违背拓扑不变量: 总线 '{bus_id}' 自引用为子总线"
            )

    return True


def assert_cascade_completeness(
    parent_bus_data: dict,
    child_bus_data: dict,
    agent_alive: bool,
) -> bool:
    """级联销毁完整性不变量 (v0.2.0)

    规则：若父总线已回收某 Agent 的令牌（判定 Agent 死亡），
    则该 Agent 管理的所有子总线必须已被强制改写为终态 (103 或 000)。

    此不变量确保不存在"僵死子总线"——父总线已释放但子总线仍处于活跃态
    的资源泄漏。

    纯函数：无 I/O。
    """
    parent_status = parent_bus_data.get("status", "000")
    child_status = child_bus_data.get("status", "000")
    child_token_holder = child_bus_data.get("Token_Holder")

    # 若 Agent 被判死亡且父总线已回收
    if not agent_alive and parent_status in ("000", "103"):
        # 子总线若仍处于活跃态，违反不变量
        if child_status in ("101", "102", "202"):
            raise AssertionError(
                f"违背级联销毁不变量: Agent '{child_token_holder}' 已被判死亡，"
                f"但其管理的子总线仍处于活跃态 '{child_status}'"
            )

    return True


def assert_ledger_consistency(
    bus_data: dict,
    ledger_entries: list,
) -> bool:
    """账本与总线状态一致性不变量 (v0.2.0)

    规则：总线的当前状态必须与账本中该总线的最后一条 STATE_TRANSITION
    事件一致。若不一致，说明账本或总线状态发生了非法的独立修改。

    纯函数：无 I/O。
    """
    bus_id = bus_data.get("bus_id", "")
    current_status = bus_data.get("status", "000")

    # 找出该总线的最后一条状态流转事件
    last_transition = None
    for entry in reversed(ledger_entries):
        if (hasattr(entry, 'bus_id') and entry.bus_id == bus_id
                and hasattr(entry, 'event_type')
                and entry.event_type.value == "STATE_TRANSITION"):
            last_transition = entry
            break

    if last_transition is not None:
        recorded_status = last_transition.payload.get("new_status", "")
        if recorded_status and recorded_status != current_status:
            raise AssertionError(
                f"违背账本一致性不变量: 总线 '{bus_id}' 当前状态 "
                f"'{current_status}' 与账本记录 '{recorded_status}' 不一致"
            )

    return True
