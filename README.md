# A2A-Cyclone

A deterministic, lease-based token ring protocol for multi-agent system orchestration.  
面向多智能体系统编排的、基于租约的确定性令牌环协议。

---

## 1. Licensing & Legal Notices / 协议与法律声明

A2A-Cyclone is an open-source project managed under a dual-licensing strategy to minimize adoption friction while preserving architecture integrity:
A2A-Cyclone 采用双重授权策略，在降低业界采用摩擦力的同时，确保架构设计的确定性：

- **Core SDK & Source Code / 核心驱动与源码**: Distributed under the **Apache License 2.0**. Commercial use, modification, and private derivation are fully permitted. See [LICENSE](./LICENSE) for details. (遵循 Apache License 2.0，允许自由商业闭源使用)。
- **Protocol Specification / 协议规范标准**: Documented under the **Creative Commons Attribution 4.0 International License (CC-BY-4.0)**. Anyone is free to re-implement this protocol format in any language/system. See [docs/SPECIFICATION.md](./docs/SPECIFICATION.md) for details. (技术规范采用 CC-BY-4.0 许可，自由实现，仅保留商标权)。

*Note: The English text of the licenses and specifications shall be the sole legally binding version. Chinese translations are for reference only.* *注：本协议及技术规范的英文文本为唯一具备法律效力的版本，中文翻译仅供技术参考。*

---

## 2. Core Features / 核心特性

- 🔒 **Deterministic Execution / 确定性收敛** Eliminates ambiguity in multi-agent collaboration via a rigid token-ring state machine, ensuring single-writer consistency on the physical bus.  
  基于刚性令牌环状态机，消除多智能体协同的时序歧义，确保物理总线上单写者的一致性。

- ⏱️ **Lease-Based Watchdog / 看门狗租约** Prevents system gridlock during long-running physical tasks (e.g., Keil compilation, MCU flashing) through dynamically extendable token leases (`status: 202`).  
  通过可动态续租的令牌租约机制（status: 202），彻底防止长耗时物理任务（如 Keil 编译、芯片烧录）导致的系统死锁。

- 🤝 **Decentralized IPC / 去中心化进程通信** Operates on an atomic file-renaming mechanism, achieving robust cross-process communication (IPC) without exposing network ports or RPC services.  
  基于文件系统的原子重命名机制，在无需开放任何网络端口或 RPC 服务的前提下，实现跨进程、跨虚拟机的强健通信。

- 🛡️ **Self-Healing Topology / 拓扑自愈** Automatically bypasses failed nodes and reclaims expired leases, isolating single-point failures from the execution chain.  
  自动绕行故障节点并强制回收超期租约，实现物理执行链条的单点故障隔离。

- 📐 **Three-Layer Architecture / 三层隔离架构 (v0.1.0)** Strictly decouples Protocol (宪法层), Runtime (执行层), and Adapter (适配层). The Protocol layer defines pure state machine topology, invariants, and ACL rules — zero file I/O, zero business logic.  
  严格解耦为 Protocol、Runtime、Adapter 三层。协议层仅定义纯状态机拓扑、不变量与 ACL 权限边界，不含任何文件 I/O 或业务逻辑。

- 🧬 **SSOT & Inferred State / 唯一事实来源 (v0.1.0)** The physical bus file (`a2a_bus.json`) is the Single Source of Truth. Agent state and token state are never stored on the bus — they are mathematically derived at runtime, eliminating state-splitting inconsistencies.  
  总线物理文件是系统唯一事实来源。禁止存储 Agent/Token 衍生状态，所有主观状态必须在运行时通过数学推导得出，从根本上杜绝状态分裂不一致。

---

## 3. Quick Start / 快速开始

### 3.1 Environment Prerequisites / 环境准备
- Python 3.8+ (No external dependencies required / 无外部第三方库依赖)
- Operating System with atomic file system operations (Windows/Linux/macOS)

### 3.2 Running the MVP Verification / 运行最小可行性验证
To experience the physical state-machine convergence (001 -> 002 -> 101 -> 102 -> 202 -> 100), execute the following nodes in separate terminal sessions:  
为了观察状态机从握手到释放的完整物理闭环，请在独立的终端视窗中分别拉起主从控：

```bash
# Terminal 1: Initialize the Slave Emulator / 终端 1：拉起从控仿真器
python slave_node.py

# Terminal 2: Trigger the Master Controller / 终端 2：启动主控调度器
python master_node.py

**Expected Output / 预期输出**:
You will see the complete state transition sequence printed in both terminals, including handshake confirmation, periodic lease heartbeats, and final task completion.  
你将在两个终端中看到完整的状态流转序列，包括握手确认、周期性租约心跳和最终任务完成提示。

![MVP Demo](./assets/mvp_demo.png)

---

## 4. Repository Structure / 仓库架构

```text
├── docs/
│   └── SPECIFICATION.md       # CACP Protocol Spec (CC-BY-4.0)
├── a2a_cyclone/
│   └── protocol/
│       ├── __init__.py        # Protocol Layer Package
│       ├── enums.py           # BusState Enum (8 status codes)
│       ├── state_machine.py   # Pure State Transition Topology (FSM)
│       ├── permissions.py     # ACL Role-Based Access Control
│       └── invariants.py      # System Invariants Assertions
├── master_node.py              # Deterministic Master Scheduler Reference Impl
├── slave_node.py               # Slave Agent Watchdog & Lease Emulator
├── cacp_bus.json               # Physical File-Bus Layout (Generated at Runtime)
├── LICENSE                     # Apache License 2.0 (Core SDK & Source Code)
└── NOTICE                      # Copyright & Dual-Licensing Attribution Notice

## 5. Originator / 发起人
Zhenyu Shi (石振禹) - Initial Protocol Architecture & Physical Verification (GitHub: @ae86999999)

## 6. 贡献 / Contribution
本项目采用 DCO 贡献声明与 GPG 签名机制。
This project adopts DCO sign-off and GPG signature requirements.

如需参与代码、文档开发与维护，请阅读完整贡献规范：
To contribute code or documentation, please refer to the full guidelines:
[CONTRIBUTING.md](./CONTRIBUTING.md)