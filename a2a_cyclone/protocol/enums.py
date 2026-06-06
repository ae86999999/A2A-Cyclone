"""
A2A-Cyclone Protocol Layer: 常量与状态枚举
绝对纯净：不包含任何文件 I/O、网络通讯或业务逻辑。

v0.2.0 新增：AgentRole, MasterRole, MasterState, FailureCategory,
           CriticalityMask, TopologyRole, TeardownBeaconState, LedgerEventType
"""

from enum import Enum


class BusState(str, Enum):
    """总线状态字典，摒弃魔术数字，保障语意透明"""
    UNINITIALIZED = "000"
    PROBE = "001"
    HANDSHAKE_ACK = "002"
    SLAVE_PASSIVE = "101"
    ACTIVE_CONTROL = "102"
    LEASE_HEARTBEAT = "202"
    RELEASE_SUCCESS = "100"
    RELEASE_FAILED = "103"
