# A2A-Cyclone Protocol Specification / A2A-Cyclone 协议核心规范

**Originator / 原案**: Zhenyu Shi | **Version / 版本**: 0.2.0 | **License / 协议**: CC-BY-4.0

### Changelog

#### v0.1.0 -> v0.2.0
- **Feature (Failure Propagation / 失败传播协议)**: 引入 `E_parent = E_child × M_criticality` 级联熔断方程。定义致命性系数掩码（LOCAL_RETRYABLE=0, GLOBAL_FATAL=1），实现异常在递归总线树中的可控击穿或局部阻断。
- **Feature (Recursive Sub-Bus / 递归子总线拓扑)**: 建立递归总线树模型（ROOT → TRUNK → LEAF），定义父子链接约束、孤儿检测与级联销毁信标（Cascading Tear-down Beacon）协议。
- **Feature (Global Ledger / 全局账本)**: 定义 append-only 不可变事件账本。所有状态流转作为 LedgerEntry 事件持久化，支持分布式审计与因果追踪。
- **Feature (Multi-Master Coordination / 多主控协调)**: 引入主控注册表与选举算法。支持 PRIMARY/STANDBY/CANDIDATE 角色模型，基于优先级、先到先得、字典序三层 tie-breaker 的确定性选举。
- **Feature (Dynamic AID / 动态 AID 分配)**: AID 池化管理，前缀式角色推导（root-/master-/slave-/adapter-），容量上限控制与冲突检测。
- **Refactor (Runtime Layer / 执行层重构)**: 新增 BusManager（总线管理器）、LeaseWatcher（租约看门狗）、TeardownHandler（级联销毁处理器）、LedgerWriter（账本写入器）四大 Runtime 组件。
- **Protocol Hardening**: ACL 扩展至多主控与级联销毁场景。不变量新增 Vector_Clock 单调性、递归拓扑完整性与级联销毁完整性检查。状态机新增僵尸回收跃迁（102→000, 103→000）。

#### v0.0.2 -> v0.1.0
- **Refactor**: 确立 Protocol, Runtime, Adapter 三层隔离架构。
- **Feature**: 引入 SSOT（唯一事实来源）原则，规范 Agent/Token 衍生状态的推导。
- **Feature**: 新增 Invariants（不变量）与 ACL（访问控制）协议层定义。

> **Core Philosophy / 核心设计理念**: Control right is determined by node role. Implements deterministic multi-agent orchestration via 3-way handshake and lease mechanism.  
> 角色决定节点控制权，基于三段式握手与租约机制实现多智能体确定性编排。

---

## 1. Role-Based State Machine / 基于角色的状态机定义

A2A-Cyclone 的核心哲学是：**角色通过三段式握手动态确认**。

### 1.1 State Code Definitions / 状态码定义
状态码统一采用 **3 位字符串格式**，以确保机器解析的一致性。

| State / 状态码 | Name / 状态名称 | Description / 说明 |
| :--- | :--- | :--- |
| **000** | Uninitialized | 总线未启动，节点处于空闲初始状态，无主从关系。 |
| **001** | Probe / Handshake | 主控节点发起连接探测，尝试建立通信链路。 |
| **002** | Handshake Ack | 从控确认回应，表明已收到握手请求。 |
| **101** | Passive / Slave | 从控角色锁定，锚定控制者 ID，进入被控态。 |
| **102** | Control / Master | 主控发号施令，确立物理执行动作。 |
| **202** | Lease / Heartbeat | 从控续租心跳，防止物理任务超时导致死锁。 |
| **100** | Success / Release | 任务完成，状态机释放，总线归还空闲。 |
| **103** | Failed / Error | 任务执行失败，主动释放总线并携带错误信息。 |

### 1.2 3-Way Handshake Flow / 三段式握手流转
为保证多 Agent 环境下的连接确定性，必须严格遵循以下握手序列：

1. **Master Initiation (001)**: Master writes `001` with `Request="Connect/ctrl/"`. (主控写入 `001` 发起寻呼)
2. **Slave Acknowledgment (002)**: Slave detects `001`, writes `002` to confirm receipt. (从控监听到 `001`，写入 `002` 发送 ACK)
3. **Master Confirmation (101)**: Master detects `002`, writes `101` to finalize the Slave role. (主控监测到 `002`，写入 `101` 完成角色锚定)
4. **Active Control (102)**: Master proceeds to write `102` with command payload. (主控跳转至 `102` 发送业务指令)

### 1.3 Handshake Exception Handling / 握手异常处理
1. **Master Timeout**: 若在 `T_HANDSHAKE_TIMEOUT` (默认3s) 内未收到 002 回应，重试3次；失败则回归 000。
2. **Slave Timeout**: 若发送 002 后在 `T_HANDSHAKE_TIMEOUT` 内未收到 101，自动回归 000。
3. **Duplicate Requests**: 从控在 101/102/202 状态下，忽略所有来自其他主控的 001 请求。

### 1.4 Lease Mechanism Rules / 租约机制规则
1. **Heartbeat**: 从控进入 101 后，每 `T_HEARTBEAT` (默认1s) 发送一次 202 心跳。
2. **Threshold**: 主控若连续 `MAX_MISSED_HEARTBEATS` (默认3次) 未收到心跳，判定租约失效。
3. **Reset**: 租约超时后，主控/从控自动回归 000 状态。

### 1.5 Bus Exclusivity / 总线独占规则
1. 同一物理总线上，同一时间只能存在一个主控节点（102状态）。
2. 当总线处于占用状态（101/102/202）时，所有 001 握手请求将被忽略。

### 1.6 Zombie Sub-Bus Recovery / 僵尸子总线回收 (v0.2.0)
针对递归架构下的僵死子总线资源泄漏，引入两条新合法跃迁：
- **ACTIVE_CONTROL (102) → UNINITIALIZED (000)**: 父总线检测到子总线 Master Agent 死亡后，强制将子总线回退至空闲态。
- **RELEASE_FAILED (103) → UNINITIALIZED (000)**: 父总线对僵死子总线的强制回收（级联销毁信标）。

---

## 2. Core Data Frame Schema / 核心数据帧结构

### 2.1 Frame Definition / 帧定义
```json
{
  "status": "002",
  "bus_id": "root-bus-0",
  "Aid": "slave-002",
  "Target_Aid": "master-001",
  "Vector_Clock": 1,
  "Request": "Connect/ctrl/",
  "content": "Handshake_Ack",
  "Lease_Extension": 0,
  "Token_Holder": "master-001",
  "Parent_Bus": null,
  "Child_Buses": [],
  "force_reset": false,
  "force_reset_by": "",
  "force_reset_reason": ""
}
```

### 2.2 Field Extensions (v0.2.0) / 字段扩展
| Field / 字段 | Type / 类型 | Description / 说明 |
| :--- | :--- | :--- |
| **bus_id** | string | 总线唯一标识符。根总线通常为 `root-bus-0`，子总线为 `sub-bus-N`。 |
| **Parent_Bus** | string\|null | 父总线 `bus_id`。若为根总线则为 `null`。 |
| **Child_Buses** | string[] | 子总线 `bus_id` 列表。叶节点总线为空数组。 |
| **force_reset** | bool | 级联销毁标记。`true` 表示此状态改写来自父总线的强制回收。 |
| **force_reset_by** | string | 执行强制回收的 Agent ID。 |
| **force_reset_reason** | string | 强制回收原因（如 `"Agent 'slave-002' lost"`）。 |

---

## 3. Protocol Architecture Boundary / 协议架构边界

A2A-Cyclone 严格遵循"协议定义秩序，Runtime 实现机制"的解耦原则，系统划分为三个绝对隔离的层级：

1. **Protocol Layer (宪法层)**：定义总线状态字典（Enums）、状态流转拓扑（State Machine）、不变量（Invariants）与访问控制（ACL）。**本层绝对不包含任何文件 I/O、网络通讯或 AI 业务逻辑。**
2. **Runtime Layer (执行层)**：定义总线管理器（Bus Manager）与租约看门狗（Lease Watcher）。负责在执行物理写入（如 `atomic_write`）前，强制调用 Protocol 层的校验机制。
3. **Adapter Layer (适配层)**：定义具体的业务执行体（如 Keil Compiler Adapter, AI LLM Adapter）。适配器仅被动监听 Runtime 抛出的状态事件，禁止直接操作总线文件。

---

## 4. Single Source of Truth (SSOT) / 唯一事实来源原则

为消除分布式环境下的复合状态不一致灾难，总线物理文件 (`a2a_bus.json`) 是系统的 **唯一事实来源 (SSOT)**。

* **禁止存储衍生状态**：总线文件仅允许存储 `BusState` (如 102) 与 `Token_Holder` 等核心原语。严禁在总线上存储或维护 `AgentState`、`TokenState`。
* **状态投影推导**：各节点（Agent）的主观状态，必须基于总线状态进行实时数学推导。
    * 当 `BusState` ∈ `{102, 202}` 且 `Token_Holder` == 自身 `Aid` 时，Agent 推导自身为 **ACTIVE** 态。
    * 其余所有情况，Agent 推导自身为 **PASSIVE**（监听被控）态。

### 4.1 Derived State Function / 衍生状态函数 (v0.2.0 形式化)

$$S_{agent} = \begin{cases} ACTIVE, & \text{if } S_{bus} \in \{102, 202\} \land Aid = Token\_Holder \\ PASSIVE, & \text{otherwise} \end{cases}$$

**变量注释**：
- `S_agent`: 智能体在本地内存中推导出的主观运行状态（衍生量，绝对禁止落盘）。
- `S_bus`: 从 `a2a_bus.json` 中原子读取的物理总线客观状态（唯一事实来源，SSOT）。
- `Aid`: 参与计算的当前智能体唯一身份标识。
- `Token_Holder`: 总线文件中记录的当前持有物理控制权的节点标识。

---

## 5. Invariants & ACL (Access Control List) / 不变量与访问控制

在任何状态流转物理生效前，必须通过以下核心校验：

### 5.1 System Invariants / 系统绝对不变量

1.  **令牌守恒定律**：在任何活跃的控制流状态下（101, 102, 202），总线上必须存在且仅存在一个明确的 `Token_Holder`。
2.  **因果时钟单调性**：`Vector_Clock` 的写入值必须严格大于总线当前的逻辑时钟历史值。
3.  **递归拓扑完整性 (v0.2.0)**: 父/子总线引用必须指向已知总线集合中存在的总线。禁止自引用与循环引用。
4.  **级联销毁完整性 (v0.2.0)**: 若父总线已判定 Agent 死亡并回收令牌，该 Agent 管理的所有子总线必须已被强制改写为终态（103 或 000）。

### 5.2 ACL Rules / 访问控制边界

1.  **探针寻呼权**：只有具备主控权限标识（如 `root-` 或 `master-` 前缀）的节点，才允许向空闲总线写入 `001` (PROBE) 状态。
2.  **令牌专有权**：针对处于 `102` 与 `202` 状态的总线，**只有当前的 `Token_Holder` 本人**具备发起续租（202）或释放（100, 103）的操作权限。任何非 `Token_Holder` 发起的越权篡改，必须在 Runtime 层被硬性阻断。
3.  **级联销毁权 (v0.2.0)**: 父总线的 `Token_Holder` 有权对其子总线执行强制状态跃迁（级联销毁）。此权限用于僵尸子总线回收场景。
4.  **子总线创建权 (v0.2.0)**: 只有持有父总线令牌的 Master 可在其下创建递归子总线。

---

## 6. Failure Propagation Protocol / 失败传播协议 (v0.2.0)

### 6.1 Core Equation / 核心方程

$$E_{parent} = E_{child} \times M_{criticality}$$

**变量注释**：
- `E_parent`: 父总线接收到的异常状态矩阵。
- `E_child`: 子总线抛出的异常特征（如 103 Failed 状态码及错误信息）。
- `M_criticality`: 致命性系数掩码。`0` = 局部可重试（异常被阻断在子总线内）；`1` = 全局致命（异常直接击穿父总线状态池）。

### 6.2 Failure Categories / 异常分类

| Category / 分类 | Criticality Default / 默认致命性 | Description / 说明 |
| :--- | :--- | :--- |
| `TRANSIENT_TIMEOUT` | LOCAL_RETRYABLE (0) | 瞬时超时，可局部重试 |
| `LEASE_EXPIRED` | LOCAL_RETRYABLE (0) | 租约过期，子总线可重试；根总线则为 FATAL |
| `PERMISSION_DENIED` | LOCAL_RETRYABLE (0) | 权限越界，记录审计后阻断 |
| `INVARIANT_VIOLATION` | GLOBAL_FATAL (1) | 不变量违背，必须级联击穿 |
| `AGENT_UNREACHABLE` | GLOBAL_FATAL (1) | 节点物理不可达，触发级联销毁 |
| `CORRUPTED_BUS` | LOCAL_RETRYABLE (0) | 总线文件损坏，可重建恢复 |
| `CASCADING_FAILURE` | GLOBAL_FATAL (1) | 已由子总线级联而来的异常，继续向上传播 |

### 6.3 Cascading Tear-down Beacon / 级联销毁信标

当父总线探测到负责管理子总线的 Agent 死亡时：
1. 父总线在回收令牌前，通过 `TeardownHandler` 强行改写所有相关 `sub_bus_x.json` 的状态为 `103 RELEASE_FAILED`。
2. 利用状态机的 `validate_transition` 通知底层 Agent 主动解除挂载。
3. 销毁事件写入全局账本，确保审计链路完整。

---

## 7. Recursive Sub-Bus Topology / 递归子总线拓扑 (v0.2.0)

### 7.1 Topology Roles / 拓扑角色

| Role / 角色 | Parent Bus / 父总线 | Child Buses / 子总线 | Description / 说明 |
| :--- | :--- | :--- | :--- |
| **ROOT** | 无 | 可有可无 | 系统根总线，全局唯一 |
| **TRUNK** | 有 | 有 | 主干总线，中间层转发节点 |
| **LEAF** | 有 | 无 | 叶子总线，执行终结点 |
| **ORPHAN** | 断裂/悬空 | 任意 | 非法拓扑态，需被修复或回收 |

### 7.2 Lease Race Condition Mitigation / 租约竞争条件缓解

主干节点（Trunk Node）同时作为父总线的 Slave 和子总线的 Master。该节点必须同时维护两份心跳：
- **向子节点收集 202 续租**（作为子总线的 Master）
- **向父节点发送 202 续租**（作为父总线的 Slave）

若单线程按序处理文件 I/O，子节点 202 写入导致的时延极易触发主干节点在父总线上的租约超时。

**缓解策略**：父总线给予主干节点额外的租约宽限期（Grace Period）：
- 普通节点：`timeout = heartbeat_interval × max_missed`
- 主干节点：`timeout = heartbeat_interval × max_missed × grace_multiplier (默认 2.0)`

---

## 8. Multi-Master Coordination / 多主控协调 (v0.2.0)

### 8.1 Master Roles / 主控角色

| Role / 角色 | Description / 说明 |
| :--- | :--- |
| **PRIMARY** | 主 Master，持有令牌，可发号施令 |
| **STANDBY** | 备 Master，注册在案，等待令牌释放 |
| **CANDIDATE** | 候选 Master，竞选令牌中 |
| **DEPOSED** | 被罢免，因异常被强制剥夺候选资格 |

### 8.2 Election Algorithm / 选举算法

多 Master 竞选 PRIMARY 时，按以下优先级确定胜者：
1. **高 priority 者胜出**（数值越大越优先）
2. **先注册者胜出**（`registered_at_clock` 更小）
3. **字典序小者胜出**（`master_id` 确定性 tie-breaker）

---

## 9. Global Ledger / 全局账本 (v0.2.0)

### 9.1 Format / 格式

全局账本采用 **append-only JSONL** 格式（每行一个完整 JSON 对象），永久不可篡改。

### 9.2 Event Types / 事件类型（部分枚举）

| Event Type / 事件类型 | Description / 说明 |
| :--- | :--- |
| `STATE_TRANSITION` | 状态机跃迁成功 |
| `STATE_TRANSITION_REJECTED` | 状态跃迁被 ACL/不变量阻断 |
| `TOKEN_CLAIMED` / `TOKEN_RELEASED` / `TOKEN_EXPIRED` | 令牌生命周期事件 |
| `HANDSHAKE_*` | 握手各阶段事件 |
| `LEASE_HEARTBEAT_*` / `LEASE_EXPIRED` | 租约事件 |
| `FAILURE_ESCALATED` / `FAILURE_CONTAINED` | 失败传播事件 |
| `AGENT_LOST` / `CASCADING_TEARDOWN` | 级联销毁事件 |
| `SUB_BUS_CREATED` / `SUB_BUS_DETACHED` / `ORPHAN_DETECTED` | 拓扑变更事件 |
| `MASTER_*` | 多主控选举/注册事件 |
| `AID_ALLOCATED` / `AID_RELEASED` / `AID_CONFLICT` | 动态 AID 事件 |

### 9.3 Ledger Invariants / 账本不变量
1. **事件 ID 全局唯一**：无重复 `event_id`。
2. **因果时钟单调性**：同一总线上的事件，`vector_clock` 严格递增。
3. **因果完整性**：若 `parent_event_id` 非空，引用的父事件必须存在于账本中。
4. **状态一致性**：总线的当前物理状态必须与账本中该总线的最后一条 `STATE_TRANSITION` 事件一致。

---

## 10. Dynamic AID Allocation / 动态 AID 分配 (v0.2.0)

### 10.1 AID Format / 格式

```
{prefix}-{unique_id}
```

| Prefix / 前缀 | Role / 角色 | Max Capacity / 最大容量 |
| :--- | :--- | :--- |
| `root` | 系统根节点 | 1（全局唯一） |
| `master` | 主控调度节点 | 16 |
| `slave` | 从控执行节点 | 256 |
| `adapter` | 适配器节点 | 64 |

### 10.2 Allocation Rules / 分配规则
1. AID 全局唯一，重复分配触发 `AID_CONFLICT` 事件。
2. 角色前缀决定操作权限（见 ACL 规则）。
3. 仅允许 ASCII 字母、数字、连字符、下划线。
4. 总长度不超过 128 字符。
