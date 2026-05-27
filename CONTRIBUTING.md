# CONTRIBUTING.md / 贡献指南

**A2A-Cyclone Contribution Guide**

欢迎参与 A2A-Cyclone 项目的开发与维护。所有贡献均需遵守本指南规则，确保项目的一致性、合规性与可维护性。  
Welcome to contribute to the development and maintenance of A2A-Cyclone. All contributions must comply with the rules in this guide.

---

## 1. Open Source License / 开源协议说明

本项目采用 **双重授权策略**，所有贡献默认遵循对应协议：  
This project adopts a **dual-licensing strategy**:

- **核心代码与 SDK**: **Apache License 2.0**
- **协议规范文档 (`docs/SPECIFICATION.md`)**: **CC-BY-4.0**

---

## 2. DCO Sign-off Requirement / DCO 贡献声明（强制）

本项目启用 **DCO (Developer Certificate of Origin)** 机制。  
All commits must be signed off via `git commit -s` (lowercase s).

```bash
# 全局自动签署设置 / Global Auto Sign-off
git config --global commit.signoff true
```

---

## 3. GPG Digital Signature / GPG 数字签名（强制）

所有提交必须附带 GPG 签名。  
All commits must include a valid GPG digital signature.

### 日常提交组合命令 / Daily Commit Command
```bash
git commit -Ss -m "type(scope): description"
```

---

## 4. File Permission Rules / 文件权限与修改规则

以下文件仅允许项目原作者修改，外部 PR 将被直接拒绝：  
The following files may only be modified by the project originator:

| 文件路径 | 说明 |
| :--- | :--- |
| `/LICENSE` | Apache 2.0 协议正文 |
| `/NOTICE` | 项目版权公示文件 |
| `/CONTRIBUTING.md` | 本贡献指南 |
| `/docs/SPECIFICATION.md` | 协议核心规范（仅可提交勘误） |
| `/.github/` | 自动化工作流与仓库配置 |

---

## 5. Commit Message Specification / 提交信息规范

采用 **约定式提交** 格式：  
Adopt the **Conventional Commits** format:

```text
<type>(<scope>): <description>

[optional body]
```

| 类型 | 说明 |
| :--- | :--- |
| `feat` | 新增功能 |
| `fix` | 修复 Bug |
| `docs` | 文档修改 |
| `refactor` | 代码重构 |
| `chore` | 构建工具、工程化修改 |

---

## 6. Pull Request Workflow / 提交流程

1. **Fork** 本仓库至个人账号。
2. **新建分支**: `git checkout -b type/description`。
3. **提交**: 确保符合 DCO 与 GPG 签名要求。
4. **提交 PR**: 提交至 `main` 分支，并填写 PR 模板。

---

## 7. Code & Documentation Standards / 代码与文档规范

- **代码**: 遵循 PEP 8，保留头部 Apache 2.0 声明。
- **文档**: 所有对外文档必须采用 **中英双语对照**。
- **协议修改**: 必须先提交 Issue 讨论，获得原作者确认后方可提交 PR。

---

## 8. Code of Conduct / 行为准则
- 保持尊重与专业的沟通态度。
- 欢迎不同观点的建设性讨论。
- 禁止任何形式的人身攻击与骚扰。

---

**感谢你的贡献！/ Thank you for your contribution!**