# Taskline

本文件用于记录 LabArchive 的实际开发进度。它记录“已经完成并验证的事实”，不代替 `Line.md` 的总体需求和阶段计划。

## 更新规则

每个可交付任务或阶段完成后、提交或交付前，必须在本文件追加一条记录，至少包含：

- 日期、Phase 或任务名称、当前状态；
- 本次实际完成的内容；
- 执行过的测试、检查和结果；
- 相关分支、提交、PR 或主要文件；
- 尚未完成、依赖后续阶段或未验证的事项；
- 建议的下一步。

不得把“代码已实现”“本地已验证”“远端 CI 已通过”“跨模块验收完成”混写为同一种完成状态。历史记录原则上只追加；如结论发生变化，应新增更正记录并说明原因。

## 当前进度总览

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| Phase 0 | 工程基础完成，保留验证项 | 本机 Conda + PostgreSQL 路径通过；Docker 路径尚未验证 |
| Phase 1 | 核心范围完成，跨阶段验收待办 | 账号、认证、系统角色和审计已完成；依赖项目/报销模型的联合权限验收保留到 Phase 2/4 |
| Phase 2 | 未开始 | 下一步先商议项目模型、成员角色、可见性和访问申请 |

## 进展记录

### 2026-08-10 — Phase 1：账号、认证与审计基础

- 状态：**Phase 1 可独立实现的功能与本地/远端验证已完成；严格按全部验收条目计算，仍有跨阶段联合权限验收未闭环。**
- 分支：`agent/phase-1-auth`
- 提交：
  - `3cbdeee feat(auth): complete phase one authentication`
  - `6f5d609 ci: enable PostgreSQL data checksums`
- 草稿 PR：[GitHub PR #1](https://github.com/ACM-player/Document_filing_reimbursemment_system/pull/1)

本次完成：

- 增加 `ACTIVE`、`DISABLED`、`DEPARTED`、`ARCHIVED` 账号生命周期及数据库一致性约束；
- 增加 Profile 和 `LAB_MEMBER`、`REIMBURSEMENT_ADMIN`、`SYSTEM_ADMIN` 固定系统角色；
- 实现登录、POST-only 退出、首次强制改密、个人改密和管理员一次性临时密码；
- 实现 12 位密码下限、12 小时 Session、关闭浏览器失效和旧 Session 失效；
- 实现用户名 HMAC 指纹 + 来源 IP 的五次失败/十五分钟登录限制；
- 实现登录、退出、密码、账号状态、角色和资料变更的脱敏 append-only 审计；
- 增加管理后台、基础页面、数据库迁移和 Phase 1 执行报告；
- 修正 GitHub Actions 的 PostgreSQL 初始化参数，使 CI 同样启用数据页校验和。

验证结果：

- `scripts/check.zsh`：通过；
- pytest：29 项通过；
- 总覆盖率：89%；
- Django system check：0 issues；
- migration drift：No changes detected；
- Ruff check / format：通过；
- 本机 PostgreSQL 17：`accounts.0002` 和 `audit.0001` 已应用；
- GitHub Actions：通过，耗时 41 秒。

未闭环事项：

- `INTERNAL` / `RESTRICTED` 项目访问依赖 Phase 2 的项目、成员和访问申请模型；
- “报销管理员不能因角色访问受限项目档案”需要 Phase 2 项目权限与 Phase 4 报销权限联合测试；
- Docker、管理员 MFA、反向代理真实来源 IP 和服务器部署仍按计划保留到后续阶段。

下一步：商议并冻结 Phase 2 的项目字段、项目内角色、可见性、访问申请状态机和权限矩阵，再开始项目系统实现。

### 2026-08-10 — 建立本地进度追踪机制

- 状态：完成；
- 本次完成：建立根目录 `taskline.md`，定义每个任务完成后的记录字段，并把该步骤写入总体开发流程和 README 目录说明；
- 验证：核对 Phase 1 本地测试、远端 CI、提交和 PR 证据后写入首条完整记录；
- 未完成：本次进度文档修改尚未提交或推送；
- 下一步：后续每个可交付任务在交付前先更新本文件。
