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

- 🔥 **Failure Propagation / 失败传播协议 (v0.2.0)** Cascading circuit-breaker with criticality mask: `E_parent = E_child × M_criticality`. LOCAL_RETRYABLE errors are contained; GLOBAL_FATAL errors pierce through the parent bus state pool.  
  级联熔断机制——局部可重试异常被阻断在子总线内，全局致命异常直接击穿父总线状态池。

- 🌲 **Recursive Sub-Bus / 递归子总线拓扑 (v0.2.0)** Multi-level bus tree (ROOT → TRUNK → LEAF) with cascading tear-down beacons. Orphan detection and zombie sub-bus recovery prevent permanent resource leaks.  
  多级总线树（根→主干→叶），配备级联销毁信标。孤儿检测与僵尸子总线回收彻底杜绝资源永久泄漏。

- 📋 **Global Ledger / 全局账本 (v0.2.0)** Append-only immutable event ledger (JSONL). Every state transition, token operation, and failure event is permanently recorded for distributed audit and causal tracing.  
  Append-only 不可变事件账本。所有状态流转、令牌操作与异常事件被永久记录，支持分布式审计与因果追踪。

- 🗳️ **Multi-Master Coordination / 多主控协调 (v0.2.0)** Master registry with deterministic election algorithm. PRIMARY/STANDBY/CANDIDATE/DEPOSED role model with priority-based, first-come-first-served, lexicographic three-tier tie-breaker.  
  主控注册表与确定性选举算法。四态角色模型（主/备/候选/罢免），基于优先级→先到先得→字典序的三层随机平局打破机制。

- 🏷️ **Dynamic AID Allocation / 动态 AID 分配 (v0.2.0)** Pool-based Agent ID management with role-prefix derivation (`root-`/`master-`/`slave-`/`adapter-`), capacity capping, and conflict detection.  
  池化 AID 分配管理，前缀式角色推导，容量上限控制与冲突检测。

- 🔌 **Adapter Layer / 适配器层 (v0.3.0)** Standardized `SlaveAdapter` ABC for pluggable executors. Ships with `ShellAdapter` (subprocess) and `ClaudeCodeAdapter` (Claude Code CLI). Thread-safe `AdapterRegistry` with capability-based routing and capacity management.  
  标准化的 `SlaveAdapter` 抽象接口实现可插拔执行器。内置 Shell 命令执行器与 Claude Code 封装器。线程安全适配器注册表，支持按能力查询路由与容量管理。

- ❤️ **Triple Heartbeat Detection / 三重心跳检测 (v0.3.0)** Real-time stdout monitoring + embedded `[HEARTBEAT]` protocol markers in prompts + OS-level process health check. Three signals ensure lease renewal without requiring any special API from the executor.  
  实时 stdout 监控 + Prompt 内嵌 `[HEARTBEAT]` 协议标记 + OS 级进程存活检测，三重信号保障续租。执行器无需任何软件层面的回调配合。

- ⏳ **Non-Recoverable Error Gating / 非可恢复错误短路 (v0.3.0)** Automatic retry loop that skips retry on timeouts, missing binaries, and user-cancelled tasks. Only transient failures (e.g., compile errors) trigger retries, preventing wasted cycles on guaranteed-to-fail attempts.  
  自动重试循环配备智能短路门：超时、二进制不存在、用户取消的任务跳过重试。仅瞬态失败（如编译报错）触发重试，不在注定失败的任务上浪费算力。

---

## 3. Quick Start / 快速开始

### 3.1 Environment Prerequisites / 环境准备
- Python 3.8+ (No external dependencies required / 无外部第三方库依赖)
- Operating System with atomic file system operations (Windows/Linux/macOS)

### 3.2 Running the MVP Verification / 运行最小可行性验证
To experience the physical state-machine convergence (001 -> 002 -> 101 -> 102 -> 202 -> 100), execute the following nodes in separate terminal sessions:  
为了观察状态机从握手到释放的完整物理闭环，请在独立的终端视窗中分别拉起主从控：

```bash
# Terminal 1: Initialize the Slave Node / 终端 1：拉起从控节点
python slave_node.py

# Terminal 2: Trigger the Master Node / 终端 2：启动主控节点
python master_node.py

# (v0.2.0) With recursive sub-bus simulation / 启用递归子总线模拟
# Terminal 1:
python slave_node.py --aid slave-002 --sub-bus-file cacp_sub_bus.json
# Terminal 2:
python master_node.py --aid master-001 --sub-bus
```

**Expected Output / 预期输出**:
You will see the complete state transition sequence printed in both terminals, including handshake confirmation, periodic lease heartbeats, and final task completion.  
你将在两个终端中看到完整的状态流转序列，包括握手确认、周期性租约心跳和最终任务完成提示。

With `--sub-bus` flag, you will additionally observe:
- Recursive sub-bus creation and teardown
- Trunk node grace period activation
- Global ledger event audit summary

启用 `--sub-bus` 参数后，还将观察到递归子总线的创建与销毁、主干节点宽限期生效、全局账本事件审计摘要。

![MVP Demo](./assets/mvp_demo.png)

---

## 4. Repository Structure / 仓库架构

```text
├── docs/
│   └── SPECIFICATION.md            # CACP Protocol Spec (CC-BY-4.0) v0.2.0
├── a2a_cyclone/
│   ├── __init__.py                 # Top-level Package
│   ├── protocol/                   # Protocol Layer (宪法层) — Pure, Zero I/O
│   │   ├── __init__.py             # Protocol Layer Exports
│   │   ├── enums.py                # BusState Enum (8 status codes)
│   │   ├── state_machine.py        # Pure State Transition Topology (FSM)
│   │   ├── permissions.py          # ACL Role-Based Access Control
│   │   ├── invariants.py           # System Invariants Assertions
│   │   ├── failure_propagation.py  # [v0.2.0] Failure Escalation Engine
│   │   ├── bus_topology.py         # [v0.2.0] Recursive Bus Tree Rules
│   │   ├── ledger.py               # [v0.2.0] Event Ledger Definitions
│   │   ├── master_coordination.py  # [v0.2.0] Multi-Master Election Rules
│   │   └── aid_pool.py             # [v0.2.0] Dynamic AID Pool Rules
│   └── runtime/                    # Runtime Layer (执行层) — I/O & Validation
│       ├── __init__.py             # Runtime Layer Exports
│       ├── bus_manager.py          # [v0.2.0] Atomic Bus I/O + Transition
│       ├── lease_watcher.py        # [v0.2.0] Lease Monitoring & Grace Period
│       ├── teardown_handler.py     # [v0.2.0] Cascading Teardown Executor
│       └── ledger_writer.py        # [v0.2.0] Append-Only Ledger Persistence
│   └── adapter/                    # ★ Adapter Layer (适配层) — Pluggable Executors
│       ├── __init__.py             # Adapter Layer Exports
│       ├── base.py                 # SlaveAdapter ABC + TaskPackage / TaskResult
│       ├── registry.py             # Thread-Safe AdapterRegistry
│       ├── shell_adapter.py        # [v0.3.0] Shell Command Executor
│       └── claude_code_adapter.py  # [v0.3.0] Claude Code CLI Executor
├── master_node.py                  # Deterministic Master Scheduler Ref Impl (v0.2.0)
├── slave_node.py                   # Slave Agent Watchdog & Lease Emulator (v0.2.0)
├── cacp_bus.json                   # Physical File-Bus Layout (Generated at Runtime)
├── cacp_ledger.jsonl               # [v0.2.0] Global Event Ledger (Append-Only JSONL)
├── cacp_sub_bus.json               # [v0.2.0] Recursive Sub-Bus (Generated at Runtime)
├── tests/                          # Unit Tests (91 tests across 4 test modules)
├── LICENSE                         # Apache License 2.0 (Core SDK & Source Code)
└── NOTICE                          # Copyright & Dual-Licensing Attribution Notice

## 5. Version History / 版本历史

| Version | Date | Key Features |
| :--- | :--- | :--- |
| **v0.3.0** | 2026-06 | Adapter Layer — SlaveAdapter interface, ShellAdapter, ClaudeCodeAdapter, Triple Heartbeat Detection, Non-Recoverable Error Gating |
| | | 适配器层 — 标准化执行器接口、Shell 命令封装、Claude Code 封装、三重心跳检测、非可恢复错误短路 |
| **v0.2.0** | 2026-06 | Failure Propagation, Recursive Sub-Bus, Global Ledger, Multi-Master, Dynamic AID |
| **v0.1.0** | 2026-05 | Three-Layer Architecture, SSOT, Invariants + ACL |
| **v0.0.2** | 2026-05 | MVP: Single Master-Slave, 3-way Handshake, Lease Mechanism |

## 6. Originator / 发起人
Zhenyu Shi (石振禹) — Initial Protocol Architecture & Physical Verification (GitHub: @ae86999999)

## 7. 贡献 / Contribution
本项目采用 DCO 贡献声明与 GPG 签名机制。
This project adopts DCO sign-off and GPG signature requirements.

如需参与代码、文档开发与维护，请阅读完整贡献规范：
To contribute code or documentation, please refer to the full guidelines:
[CONTRIBUTING.md](./CONTRIBUTING.md)
