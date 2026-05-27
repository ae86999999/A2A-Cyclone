# A2A-Cyclone Protocol Specification / A2A-Cyclone 协议核心规范

**Originator / 原案**: Zhenyu Shi | **Version / 版本**: 1.0.0 | **License / 协议**: CC-BY-4.0

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

---

## 2. Core Data Frame Schema / 核心数据帧结构

### 2.1 Frame Definition / 帧定义
```json
{
  "status": "002",
  "Aid": "ai-slave-002",
  "Target_Aid": "ai-master-001",
  "Vector_Clock": 1,
  "Request": "Connect/ctrl/",
  "content": "Handshake_Ack",
  "Lease_Extension": 0
}