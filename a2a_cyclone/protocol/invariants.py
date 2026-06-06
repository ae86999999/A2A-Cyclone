"""
A2A-cyClone Protocol Layer: 系统不变量断言（绝对真理）
绝对纯净：不包含任何文件 I/O、网络通讯或业务逻辑。
"""


def assert_invariants(bus_data: dict) -> bool:
    """
    系统不变量校验：所有状态写入前必须通过的最高宪法
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
