# Taskline

本文件记录项目的实际开发进度、已验证事实、遗留问题和线程交接信息。
`Line.md` 是需求、架构、Phase 规划和验收基线。
实际代码、Git 状态和实际测试结果是判断实现状态的最终事实来源。

## 1. 当前状态快照

### 1.1 当前开发阶段

- 当前 Phase：Phase 1 / Phase 2 交付收口完成；Phase 3 的 CP0–CP5 均已完成；下一 checkpoint 为 CP6 并发、一致性与 reconciliation；
- 当前状态：**Phase 1 / Phase 2 已合并并完成独立范围本地验收及远端 CI；Phase 3 的 CP0–CP5 已实现并通过当前 252 项 PostgreSQL 全量回归；CP6–CP7 尚未开始。**
- 当前 Git 分支：`agent/phase-3-files`，基线为最新 `main` `a203107c44ef9870161a49893de85959af4d77e2`；
- Phase 2 实现 commit：`5c68b403 feat(projects): complete phase two project system`，父提交为 Phase 1 的 `119e209`；
- 工作树：CP5 实现已提交为 `9050e6c feat(documents): add document lifecycle services`；本条 CP5 交接记录将作为独立 docs checkpoint 提交；
- 远端状态：Phase 1 / Phase 2 分支提交及两个 merge commit 均已进入 `origin/main`；`main`、`origin/main` 与 Phase 3 分支起点均为 `a203107`；Phase 3 分支尚未推送；
- PR：[PR #1](https://github.com/ACM-player/Document_filing_reimbursemment_system/pull/1) 已以 merge commit `ad3181c` 合并；[PR #2](https://github.com/ACM-player/Document_filing_reimbursemment_system/pull/2) 已在 base 调整为 `main` 后以 merge commit `0fccbb8` 合并；
- GitHub Actions：PR #1 head CI `31371151159`、PR #2 head CI `32256185247`、Phase 1 merge 后 main CI `32257435132`、Phase 2 merge 后 main CI `32257797190`、最新 main 收口 CI `32258148559` 均为 success；
- 拓扑整理：未 rebase、未 squash；Phase 1 采用 merge commit 后，`119e209` 同时是 `main` 与 Phase 2 head 的祖先，因此 PR #2 只需从 `agent/phase-1-auth` retarget 到 `main`。

### 1.2 各阶段状态

| Phase | 状态 | 说明 |
| --- | --- | --- |
| Phase 0 | 本地验证完成；跨环境验收待办 | 本机 Conda + PostgreSQL 工程路径已验证；Docker 和第二套完整环境仍未闭环，不能标记为全部完成。 |
| Phase 1 | 本地验证、CI、最终 review 与 PR 合并完成；项目文件跨阶段验收已本地完成 | 账号、认证、系统角色和审计核心范围已进入 `main`；Phase 2 项目级权限联动及 Phase 3 真实项目文件下载已本地验收，报销附件联动待 Phase 4；PR #1 已合并。 |
| Phase 2 | 可独立实现范围本地验收、CI、最终 review 与 PR 合并完成；真实文件下载联合权限已在 Phase 3 本地完成 | 项目元数据、可见性、成员、访问申请及项目级权限决策已通过 132 项 PostgreSQL 综合测试、五条真实事务并发链、migration、多角色浏览器流程及 PR/main CI；PR #2 已合并。真实 Document / FileAsset 下载边界已由 CP4 的真实字节联合回归补齐。 |
| Phase 3 | CP0–CP5 已完成并通过当前完整门禁 | 已冻结架构，实现模型/权限/迁移、安全文件基础设施、可恢复上传 saga、鉴权下载、软删除、回收站查询和安全恢复；CP5 13 项定向测试、252 项 PostgreSQL 全量回归和 89% coverage 通过。档案页面和 reconciliation 保留到后续 checkpoint。 |
| Phase 4–10 | 未开始 | 报销附件、导出、备份恢复和生产部署仍保留到对应后续 Phase。 |

### 1.3 当前正在处理

1. 已从最新 clean `main` 创建 `agent/phase-3-files`，没有在 main 上开发。
2. 已修正 README 和本文件中的 Phase 1 / Phase 2 远端交付状态漂移。
3. 已用 ADR-0006 冻结 Phase 3 文件格式、分类、版本骨架、ZIP、扫描、可恢复 saga、状态机、幂等、权限、下载完整性、软删除/恢复和锁序。
4. CP1 已实现 FileAsset 状态/扫描事实、分类范围、Document 版本骨架和一对一生命周期，并用 PostgreSQL 约束及触发器保护关键不变量。
5. CP1 已实现文件权限决策和审计动作；当时没有实现物理存储、上传、下载、删除/恢复服务或页面。
6. CP2 已实现受控 staging/最终 key、流式大小与 SHA256、类型检测、ZIP/OOXML 安全校验和生产扫描 fail-closed 配置。
7. CP3 已实现持久化 TEMPORARY 意图、两次锁后鉴权、安全门禁、原子发布、隔离/失败审计、幂等 replay 和中断恢复。
8. CP4 已实现受控鉴权下载、安全响应头、物理存在性/元数据异常 fail-closed、MISSING 转换和真实文件权限/IDOR 联合验收。
9. CP5 已实现权限对称的软删除、回收站查询和安全恢复；恢复复核物理存在、大小、SHA256、服务端类型、扫描、当前权限和文档组冲突，失败安全转为 MISSING 或 QUARANTINED。
10. staged 校验后同大小字节变化的竞态已通过最终提交前重新计算 SHA256 修复并新增回归；CP5 完整门禁通过，下一步进入 CP6。

### 1.4 高优先级问题闭环状态

当前没有阻止 Phase 2 本地验收的已知 P0/P1 功能缺陷。下表保留接管时的高风险问题及最终闭环证据；外部调度和未来业务并发的边界不能被误写为已完成。

| 问题 | 风险 | 当前处理状态 |
| --- | --- | --- |
| 账号离组未持久终止授权 | 用户变为 `DEPARTED` / `ARCHIVED` 后，活动 Membership 和 PENDING/APPROVED 申请没有关闭；账号重新激活时旧受限项目权限可能复活。 | **已本地解决并验证**；统一账号服务区分 DISABLED 暂停与不可逆离组，事务性关闭项目关系并阻断未转移 PI；真实 Admin POST、服务和离组/授权并发用例通过。 |
| Membership 未绑定具体访问申请 | 多轮申请后，撤销旧 APPROVED 申请可能误删后来申请产生的当前 VIEWER 授权。 | **已本地解决**；新增 `source_access_request` 一对一 `PROTECT` 血缘，撤销和到期只操作精确授权，多轮撤销/到期回归通过。 |
| 普通成员移除与访问撤销分叉 | 从成员页移除申请获批的 VIEWER 时，只结束 Membership，不同步申请状态，也不产生正确的撤销审计。 | **已本地解决并通过顺序与并发 PG 回归**；申请型 VIEWER 的成员移除复用精确撤销路径，DIRECT 才走普通成员结束；并发移除/撤销只产生一次终态审计。 |
| 到期状态和审计不能保证落库 | 到期只在显式调用清理函数时写入；无人访问时记录可能长期保持 APPROVED，管理页还可能把已到期授权误记为主动撤销。 | **Phase 2 边界已解决并验证**；权限查询即时失效、项目管理页面执行项目级归一化，并新增幂等 `expire_project_access` 命令；移除/到期竞态只落一个终态。生产无人访问时持续归一化依赖部署阶段的外部调度器，不作为本地 Phase 2 完成声明。 |
| 审批未复核最新申请人和项目状态 | 离组用户仍可能获批；项目已归档、删除或不再是 RESTRICTED 时可能批准过时申请。 | **已本地解决并通过顺序与并发 PG 回归**；审批锁后复核申请人、项目和关联关系；离组先持有 User 锁时审批不会创建授权，申请被安全取消。 |
| 缺少统一并发锁顺序 | 成员管理、审批、归档和软删除存在 TOCTOU、陈旧对象授权和唯一约束异常转为 500 的风险。 | **首批高风险路径已实现并通过真实 PG 并发回归**；主要授权入口采用 User → Project → Request → Membership，插入唯一约束冲突转换为业务错误。5 个确定性线程事务用例覆盖离组/直接授权、离组/审批、PI 转移/旧 PI 离组、移除/撤销、移除/到期，连续三轮无死锁且终态正确。更广页面提交与未来业务并发仍需对应阶段持续验证。 |
| PI 存在双事实源且组合约束不足 | `Project.principal_investigator` 与 PI Membership 可能不一致；数据库未保证 PI 为 DIRECT 且永不过期，也未保证 APPROVED_REQUEST 只能产生 VIEWER。 | **已本地解决并验证**；Project FK 为规范事实，权限不一致时安全失败，数据库约束授权形状；未转移的正常或 ARCHIVED 项目 PI 不能永久离组，DISABLED 保留 PI；PI 转移与旧 PI 离组的真实并发回归通过。 |
| 服务层依赖 HTML 表单过滤 | 直接调用服务可能创建 ARCHIVED 项目，或把项目切换到已停用类型。 | **已本地解决并通过当前树 PG 回归**；创建禁止 ARCHIVED 和停用类型，更新禁止切换到停用类型但允许保留当前已停用类型，审批也独立复核项目与申请人状态。 |

### 1.5 当前验证状态

以下区分当前 Phase 3 工作树证据与已收口 Phase 1 / Phase 2 证据。历史 132 项结果不能作为当前
Phase 3 文档工作树的新测试结果。

| 验证项 | 最近结果 | 当前结论 |
| --- | --- | --- |
| Phase 3 CP1 定向 PostgreSQL 测试 | 32 项通过，0.50s | 覆盖模型约束、PostgreSQL 触发器、分类范围、版本骨架、审计动作和权限矩阵。 |
| Phase 3 CP1 `scripts/check.zsh` | 通过；164 项 pytest，4.09s，88% coverage | Ruff、79 文件 format、Django check、migration drift 和全量 PostgreSQL 回归全部通过。 |
| Phase 3 CP2 定向测试 | 48 项通过，0.09s | 无数据库测试；覆盖 staging、受控 key、摘要、格式、ZIP/OOXML、扫描 adapter、production fail-closed 和配置边界。 |
| Phase 3 CP2 `scripts/check.zsh` | 通过；210 项 pytest，4.23s，89% coverage | Ruff、85 文件 format、Django check、migration drift 和完整 PostgreSQL 回归全部通过。 |
| Phase 3 CP3 定向 PostgreSQL 测试 | 16 项通过，0.61s | 覆盖成功、幂等、重复 SHA、越权、隔离、扫描、移动/文件缺失、权限变化、审计回滚和 TEMPORARY 恢复。 |
| Phase 3 CP3 `scripts/check.zsh` | 通过；226 项 pytest，4.56s，88% coverage | Ruff、87 文件 format、Django check、migration drift 和完整 PostgreSQL 回归全部通过。 |
| Phase 3 CP4 定向 PostgreSQL 测试 | 51 项通过，1.25s | 覆盖鉴权下载、真实字节、中文 Content-Disposition、缺失/篡改/软链接、提交失败清理及既有存储/校验回归。 |
| Phase 3 CP4 `scripts/check.zsh` | 通过；239 项 pytest，5.66s，89% coverage | Ruff、90 文件 format、Django check、migration drift 和完整 PostgreSQL 回归全部通过。 |
| Phase 3 CP5 定向 PostgreSQL 测试 | 13 项通过，0.72s | 覆盖软删除权限、回收站范围、恢复成功、缺失/篡改/扫描失败、审计回滚、状态变化、版本冲突及校验后同大小篡改。 |
| Phase 3 CP5 `scripts/check.zsh` | 通过；252 项 pytest，6.46s，89% coverage | Ruff、91 文件 format、Django check、migration drift 和完整 PostgreSQL 回归全部通过。 |
| Phase 1 / Phase 2 `scripts/check.zsh` | 通过 | 已收口历史证据；项目专属 `labarchive` Conda 环境、PostgreSQL 测试数据库；Ruff、格式、Django check、migration drift、pytest 和 coverage 全部通过。 |
| Phase 1 / Phase 2 完整 pytest | 132 项通过，3.65s | 已收口历史证据；PR #2 最终 review 时在整合树复跑。 |
| Phase 1 / Phase 2 覆盖率 | 88% | 已收口历史证据；1715 statements、398 branches。 |
| Ruff format / check | `ruff check .` 通过；90 个 Python 文件 format check 通过 | 当前 Phase 3 CP4 完整结果。 |
| Django system check | 0 issues | 当前整合树通过。 |
| migration drift | `No changes detected` | 当前模型与 migration 一致。 |
| 本机 migration | `audit.0003 [X]`、`documents.0001 [X]` | 迁移前 custom-format 快照已创建并由 `pg_restore -l` 校验；迁移应用和 `No changes detected` 复核通过。 |
| 真实事务并发 | 5 项连续三轮通过（0.87s / 0.79s / 0.78s） | 覆盖离组/直接授权、离组/审批、PI 转移/旧 PI 离组、移除/撤销、移除/到期；没有死锁或授权复活。 |
| 页面安全定向 pytest | 34 项通过，0.96s | 覆盖 SYSTEM_ADMIN 非 LAB_MEMBER、普通非门户 403、IDOR、软删除、CSRF、失败回显、INTERNAL 成员信息边界和只读 Admin。 |
| UI / 浏览器流程 | 通过 | 实际登录并覆盖申请、失败回显、批准、撤销、INTERNAL 信息边界、SYSTEM_ADMIN 全局 CRUD/软删除、非门户 403；桌面与 390px 移动视口正常，控制台 0 warning/error；临时数据已清理。 |
| `git diff --check` | 通过 | 最终文档更新后复核通过。 |
| GitHub Actions | PR #1 head `31371151159`、PR #2 head `32256185247`、Phase 1 merge main `32257435132`、Phase 2 merge main `32257797190`、最新 main `32258148559` 均通过 | Phase 1 / Phase 2 及 main 收口远端证据；Phase 3 分支尚无 CI。 |

### 1.6 下一步执行顺序

1. 进入 CP6，实现 ADR-0006 规定的 reconciliation：stale staging、DB 引用缺失文件、无 DB 最终文件、TEMPORARY 中断恢复和明确审计/报告；不得静默删除未知字节。
2. 补真实 PostgreSQL 并发测试，覆盖重复上传、上传/删除/恢复与项目归档、账号状态变化、move/DB/audit 失败及统一锁序。
3. CP6 完成定向和完整门禁后形成独立 checkpoint，再进入 CP7 页面、真实样本和 Phase 3 最终验收。
4. 部署阶段仍需配置外部 `expire_project_access` 调度；本地即时失效与人工命令不替代生产调度。

### 1.7 Phase 3 当前 checkpoint

- CP0：**完成并完成文档验证**；新增 ADR-0006，冻结分类范围、版本骨架、格式白名单、纯 Python
  真实类型检测、ZIP 阈值、扫描事实、可恢复 saga、FileAsset 状态机、幂等 token、权限、下载完整性、
  软删除/恢复和文件锁序。
- CP1：**完成并完成 PostgreSQL 验证**；实现 FileAsset、DocumentCategory、Document、文件审计动作、
  数据库约束/触发器、权限函数、`audit.0003`、`documents.0001` 和 32 项定向测试。
- CP2：**完成并完成文件系统与完整 PostgreSQL 验证**；实现受控 staging/最终 key、流式大小和 SHA256、
  PDF/PNG/JPEG 签名、ZIP 路径/类型/阈值/CRC、DOCX/XLSX 结构和无宏检查、扫描 adapter 及 production
  fail-closed 配置。
- CP3：**完成并完成 PostgreSQL 验证**；实现持久化上传意图、幂等 token replay、staging/校验/扫描、
  发布前后两次 User → Project → Document → FileAsset 锁后鉴权、原子发布、QUARANTINED/失败审计、
  audit/DB 中断后的 TEMPORARY 重新校验续跑。
- CP4：**完成并完成 PostgreSQL 验证**；实现受控 Django 下载 endpoint/service、每次锁后重新鉴权、
  安全 Content-Disposition、服务器生成路径隔离、物理文件/软链接/元数据异常 fail-closed、MISSING
  转换、下载审计和 INTERNAL / RESTRICTED / VIEWER / SYSTEM_ADMIN / 无权限 / UUID IDOR 真实字节验收。
- CP5：**完成并完成 PostgreSQL 验证**；实现权限对称的文档软删除、回收站查询和安全恢复，保留物理字节；恢复重新校验大小、SHA256、真实类型、扫描、权限和版本冲突，缺失/完整性失败转 MISSING，安全失败转 QUARANTINED，并写成功/失败审计。
- CP6–CP7：**尚未开始**；没有实现或验证证据。
- CP0 验证：`git diff --check`、Markdown fence、ADR 相对链接和当前状态关键词检查通过。
- CP1 验证：32 项定向测试通过；完整门禁为 Ruff、79 文件 format、Django check、migration drift、
  164 项 PostgreSQL pytest（4.09s）和 88% coverage 全部通过；本机迁移已应用。
- CP2 验证：48 项非数据库定向测试通过；完整门禁为 Ruff、85 文件 format、Django check、migration
  drift、210 项 PostgreSQL pytest（4.23s）和 89% coverage 全部通过。
- CP3 验证：16 项 PostgreSQL 定向测试通过；完整门禁为 Ruff、87 文件 format、Django check、
  migration drift、226 项 PostgreSQL pytest（4.56s）和 88% coverage 全部通过。
- CP4 验证：51 项 PostgreSQL 定向测试通过；完整门禁为 Ruff、90 文件 format、Django check、
  migration drift、239 项 PostgreSQL pytest（5.66s）和 89% coverage 全部通过。
- CP5 验证：13 项定向 PostgreSQL 测试通过；完整门禁为 Ruff、91 文件 format、Django check、migration drift、252 项 PostgreSQL pytest（6.46s）和 89% coverage 全部通过；没有 model 变化或新 migration。

## 2. 当前 Phase 工作区详情

### 2.1 已完成并验证

这里的“完成并验证”表示 Phase 2 可独立实现范围已有本地实现、验收及实现 commit 远端 CI 证据；不表示真实文件下载联合权限验收、PR 评审或后续 Phase 已完成。

- 已建立 Phase 2 的 PostgreSQL 自动化测试基础；当前工作树综合门禁 132 项通过、覆盖率 88%，包含 Phase 1 回归及现有全部 Phase 2 自动化用例。
- 已验证现有权限函数不会因为 `REIMBURSEMENT_ADMIN` 系统角色而自动授予 RESTRICTED 项目访问权。
- 已验证申请授权与具体申请一对一绑定；旧申请撤销或到期不会关闭后来申请产生的授权。
- 已验证申请授权直接晋升和 PI 转移会结束旧授权行并新建 DIRECT 行，不改写来源历史。
- 已验证 Project PI 为规范事实，活动 PI Membership 不匹配时 PI 权限安全失败；授权来源、角色和到期组合受数据库约束。
- 已验证统一账号状态服务区分 DISABLED 暂停与不可逆离组：恢复只保留仍有效授权，DEPARTED / ARCHIVED 关闭活动项目关系且旧 RESTRICTED 权限不复活。
- 已验证未转移的正常或 ARCHIVED 项目 PI 不能永久离组，DISABLED PI 的规范关系保留，项目审计失败会回滚整笔账号离组。
- 已验证当前模型定义与首版 migration 文件之间没有检测到漂移。
- 已验证服务边界禁止创建 ARCHIVED 项目、使用停用项目类型及审批陈旧申请；重复成员设置、移除、取消和撤销按授权边界幂等。
- 已验证真实 Admin POST、普通移除、页面到期归一化和管理命令写库/幂等用例；页面测试曾因全局时间 mock 误使 Session 到期，收窄 mock 后定向与全量回归均通过。
- 已验证所有项目页面和 POST 端点在对象解析前执行门户资格判断；SYSTEM_ADMIN 非 LAB_MEMBER、普通非门户 403、跨项目 IDOR、软删除对象、CSRF、审批失败回显和 INTERNAL 成员信息边界均有回归。
- 已验证五条真实 PostgreSQL 线程事务竞态，连续三轮通过；锁序、终态、审计单次性和无死锁均得到证据。
- 已应用本机 `audit.0002` 与 `projects.0001`；迁移前快照已校验，模型 drift 为 `No changes detected`。
- 已完成多角色真实浏览器流程、桌面/移动视口和控制台验收；所有固定前缀的临时数据与测试审计已精确清理。
- Phase 1 回归已包含在 132 项完整 PostgreSQL pytest 中并重新通过。
- 最终文档与页面展示修改后，完整 Ruff、格式、Django check、migration drift、132 项 pytest、coverage 和 `git diff --check` 均已再次通过。

### 2.2 已提交并通过实现 commit 远端 CI

- `ProjectType`、`Project`、`ProjectMembership`、`ProjectAccessRequest` 模型、精确授权血缘和首版约束；
- INTERNAL / RESTRICTED 可见性和 PLANNING / ACTIVE / PAUSED / COMPLETED / ARCHIVED 状态；
- PI / MANAGER / MEMBER / VIEWER 项目角色；
- 项目创建、编辑、软删除、负责人转移、成员管理、访问申请、审批、撤销和到期服务；
- 统一账号状态服务及 Django Admin 接入、账号永久离组的项目授权清理；
- 项目级到期页面归一化和幂等 `expire_project_access` 管理命令；
- 项目权限查询函数、表单、URL、视图、模板和导航；
- 项目管理后台只读入口、项目类型配置入口及样式；
- 项目相关审计动作以及已在本机应用的 `audit.0002`、`projects.0001` migration；
- 模型、权限、服务、页面、Admin、命令、生命周期和并发自动化测试。

### 2.3 保留边界与非阻塞增强

- 到期权限即时失效、管理页归一化和人工命令已实现并通过顺序/并发回归；无人访问时持续自动落库仍需部署外部调度器。
- 当前详情页只展示活动或已批准的申请，不提供完整拒绝/撤销/到期历史时间线；历史保留在数据库和审计中，完整业务历史 UI 可作为后续增强。
- 移除、撤销和软删除均为 CSRF 保护的 POST 操作，但当前没有额外确认页；`Line.md` 只强制永久删除二次确认，Phase 2 不提供永久删除，因此该项不是本地验收阻塞。
- 账号永久终止保留其系统 Group；受支持状态机禁止终态恢复。任何未来的恢复或角色清理政策必须另行设计和审计。
- 项目文件与报销附件模型尚不存在；Phase 2 可以验证用户是否具有项目档案读取资格及统一的项目级权限决策，不能宣称真实文件或附件下载链路已验收。

### 2.4 尚未执行

- Phase 3 文件档案系统及真实下载鉴权；
- Phase 4 报销业务和附件联合权限；
- 生产环境外部到期调度器配置与执行验证；
- Docker、第二套全新环境和服务器恢复演练。

### 2.5 已知缺陷

- 当前没有经自动化、浏览器和最终差距复核确认的 Phase 2 可独立实现范围内 P0/P1 功能缺陷。
- 申请人页面没有完整展示最近一次拒绝、撤销或到期历史；数据与审计均保留，属于后续可用性增强。
- 移除、撤销和软删除没有额外确认页；均为 CSRF 保护的 POST，且当前不提供永久删除。若未来增加永久删除，必须按 `Line.md` 二次确认。
- 账号永久终止不会移除 `SYSTEM_ADMIN` / `REIMBURSEMENT_ADMIN` Group；受支持状态机禁止终态重新激活，未来若改变恢复政策必须单独设计和审计。

### 2.6 验证边界

- 当前页面角色/资源矩阵、写端点越权、跨项目 UUID / IDOR、软删除、CSRF 和审批失败回显已有自动化回归。
- 同一用户多轮申请、撤销旧申请、旧申请到期、直接晋升、普通移除、账号离组、Admin POST、到期命令和五条并发链均有 PostgreSQL 证据。
- 浏览器已覆盖 Phase 2 核心多角色流程，但不是穷举所有表单字段组合；自动化测试承担完整边界回归。
- Phase 2 实现 commit 已通过远端 CI，但仍未验证 Docker 或第二套全新环境。
- Phase 3 已用真实 Document/FileAsset 和受控 URL 完成下载鉴权、文件类型、物理缺失/异常、非门户账号、
  过期授权与直接 UUID/IDOR 回归；旧 Session 依赖每次请求重新读取当前账号及授权状态，不缓存权限决策。

### 2.7 当前新增 / 修改的重要文件

Phase 3 CP0 commit `b079cb6`、CP1 commit `ccf191f`、CP2 commit `69a0055`、CP3 commit `b4038fa`、
CP4 commit `432f753` 与 CP5 commit `9050e6c`：

- `README.md`
- `taskline.md`
- `docs/ARCHITECTURE.md`
- `docs/DATABASE.md`
- `docs/adr/0006-phase3-file-storage-security.md`
- `apps/audit/models.py`
- `apps/audit/migrations/0003_alter_auditlog_action.py`
- `apps/documents/models.py`
- `apps/documents/migrations/0001_initial.py`
- `apps/documents/permissions.py`
- `apps/documents/scanning.py`
- `apps/documents/services.py`
- `apps/documents/storage.py`
- `apps/documents/urls.py`
- `apps/documents/validation.py`
- `apps/documents/views.py`
- `config/urls.py`
- `config/settings/base.py`
- `config/settings/production.py`
- `config/settings/test.py`
- `tests/document_factories.py`
- `tests/test_document_permissions.py`
- `tests/test_document_downloads.py`
- `tests/test_document_lifecycle_services.py`
- `tests/test_document_scanning.py`
- `tests/test_document_storage.py`
- `tests/test_document_upload_services.py`
- `tests/test_document_validation.py`
- `tests/test_documents_models.py`
- `tests/test_settings.py`

Phase 2 实现 commit `5c68b403` 中修改：

- `Line.md`
- `README.md`
- `apps/accounts/admin.py`
- `apps/accounts/forms.py`
- `apps/accounts/services.py`
- `apps/accounts/signals.py`
- `apps/audit/models.py`
- `apps/projects/admin.py`
- `apps/projects/models.py`
- `config/urls.py`
- `docs/ARCHITECTURE.md`
- `docs/DATABASE.md`
- `static/styles.css`
- `templates/base.html`
- `templates/core/home.html`
- `tests/test_accounts.py`
- `tests/test_accounts_admin.py`
- `taskline.md`

Phase 2 实现 commit `5c68b403` 中新增：

- `apps/audit/migrations/0002_alter_auditlog_action.py`
- `apps/projects/forms.py`
- `apps/projects/management/__init__.py`
- `apps/projects/management/commands/__init__.py`
- `apps/projects/management/commands/expire_project_access.py`
- `apps/projects/migrations/0001_initial.py`
- `apps/projects/permissions.py`
- `apps/projects/services.py`
- `apps/projects/urls.py`
- `apps/projects/views.py`
- `docs/adr/0004-project-authorization-lineage.md`
- `docs/adr/0005-account-project-access-lifecycle.md`
- `docs/PHASE2_REPORT.md`
- `templates/projects/project_detail.html`
- `templates/projects/project_form.html`
- `templates/projects/project_list.html`
- `templates/projects/project_members.html`
- `tests/project_factories.py`
- `tests/test_account_project_lifecycle.py`
- `tests/test_expire_project_access_command.py`
- `tests/test_project_permissions.py`
- `tests/test_project_service_boundaries.py`
- `tests/test_project_service_concurrency.py`
- `tests/test_project_service_idempotency.py`
- `tests/test_project_services.py`
- `tests/test_project_views.py`
- `tests/test_projects_admin.py`
- `tests/test_projects_models.py`

### 2.8 Migration、分支、远端和 PR 状态

- `projects.0001` 包含授权血缘与组合约束，`audit.0002` 扩展项目审计动作；migration drift 检查未发现差异；
- 本机开发库已应用 `audit.0002` 与 `projects.0001`。迁移前快照为 `.local/backups/pre-phase2-20260812-migration.dump`，SHA-256 为 `30d9469b5183cbbc7ad92c4e389f704b3a8237fe4155ba9afe9fbcdf3f9f8b8e`，已由 `pg_restore -l` 校验；
- Phase 3 本机开发库已应用 `audit.0003` 与 `documents.0001`。迁移前快照为 `.local/backups/pre-phase3-cp1-20260819.dump`，SHA-256 为 `84032884b4938045cecdc1dad97cbc6d919458416350af41bf4877738e624b55`，已由 `pg_restore -l` 校验；
- 当前分支为 `agent/phase-3-files`，CP0 commit 为 `b079cb6`，CP1 commit 为 `ccf191f`，CP2 commit 为 `69a0055`，CP3 commit 为 `b4038fa`，CP4 commit 为 `432f753`，CP5 commit 为 `9050e6c`，基线为 `main` / `origin/main` 的 `a203107`；Phase 1 head `119e209`、Phase 2 head `1bef3ce` 及对应实现提交均已成为 `origin/main` 祖先；
- [PR #1](https://github.com/ACM-player/Document_filing_reimbursemment_system/pull/1) 已合并，merge commit=`ad3181c`；[PR #2](https://github.com/ACM-player/Document_filing_reimbursemment_system/pull/2) 已在 base 从 `agent/phase-1-auth` 调整为 `main` 后合并，merge commit=`0fccbb8`；
- PR #2 整理未 rebase、未 squash；Phase 1 merge commit 保留了 `119e209` 祖先关系，retarget 后三点 diff 仍仅包含原 46 个 Phase 2 文件；
- Phase 3 CP4 已完成；鉴权 Download 和物理文件下载完整性/权限联合验收已闭环，删除/恢复仍待后续 Phase 3 checkpoint。

## 3. 未闭环的跨 Phase 事项

- Phase 1 → Phase 2：**项目级联动已本地完成**。真实 Project、Membership 和访问申请上的 INTERNAL / RESTRICTED 项目元数据与授权决策已进入 132 项综合回归和浏览器流程；该结论不包含真实文件下载。
- Phase 1 / Phase 3 / Phase 4：**项目档案真实文件联合权限已在 Phase 3 CP4 本地完成**；报销管理员不会因为系统角色获得 RESTRICTED 项目档案读取资格，报销附件模型与联合权限待 Phase 4。
- Phase 0 / 后续交付：Docker 路径和第二套完整环境仍未验证，不能用本机 Conda 路径代替该验收。
- Phase 2 → Phase 3：真实文件上传与鉴权下载已本地完成，并以真实字节复核 INTERNAL、RESTRICTED、VIEWER、SYSTEM_ADMIN、无权限用户及直接 URL / IDOR 边界。软删除/恢复、完整档案 UI、配额及版本管理仍按后续 Phase 3 checkpoint 推进，不能据此声明整个 Phase 3 已完成。
- Phase 4：报销业务和附件联合权限尚未开始。
- MFA：管理员 MFA 按 `Line.md` 计划在远程部署前闭环，本地 Phase 2 不提前实现。
- 反向代理真实来源 IP：依赖服务器和代理拓扑，保留到部署阶段验证。
- 服务器部署、TLS、生产配置、备份与恢复演练：当前明确延后，不属于本地 Phase 2 完成条件。

## 4. 工作历史

### 2026-08-20 — Phase 3 CP5：软删除、回收站查询与安全恢复

- 状态：**CP5 实现和本地验证完成；CP6 尚未开始。**
- 分支：`agent/phase-3-files`，恢复基线 checkpoint `ac49929`；
- 提交 / PR：`9050e6c feat(documents): add document lifecycle services`；分支尚未推送，无 Phase 3 PR。

#### 完成内容

- 软删除按 User → Project → Document → FileAsset 锁序重新鉴权，同事务同步写 Document 删除时间和 FileAsset DELETED 状态，物理字节保留；MEMBER 只能删除本人上传，PI/MANAGER 管理项目文件，SYSTEM_ADMIN 支持全局恢复边界；
- 回收站查询仅返回当前账号有恢复权限、项目未软删除且未归档的文档；普通成员和 VIEWER 不能恢复；
- 恢复先持久锁后鉴权，再将最终文件复制到受控 staging，完整复核大小、SHA256、真实类型和扫描，最终事务再次锁后鉴权并检查文档组当前版本冲突；
- 缺失、不可安全读取、大小/SHA256 异常或最终文件变化转 MISSING；类型或扫描安全失败转 QUARANTINED；Document 保留在回收站并写文件状态及恢复失败审计；
- 修复 staged 校验后到最终提交前的同大小篡改窗口：最终提交前重新读取受控最终文件并计算 SHA256；新增确定性回归；
- 审计失败回滚删除/恢复数据库状态；临时校验副本在成功、失败和权限变化路径均清理；CP5 不实现永久物理删除、档案页面、reconciliation 或 Phase 4 内容。

#### 验证结果

- CP5 PostgreSQL 定向测试：13 项通过，0.72s；
- `scripts/check.zsh`：Ruff、91 文件 format、Django check、migration drift、252 项 PostgreSQL pytest（6.46s）和 89% coverage 全部通过；
- `git diff --check`：通过；没有 model 变化或新 migration。

#### 下一步

进入 CP6，实现 reconciliation、幂等与真实 PostgreSQL 并发/故障测试；未知 orphan 只报告或隔离，不静默删除，随后再进入 CP7 页面和最终验收。

### 2026-08-20 — Phase 3 中断现场独立核验与 CP5 恢复点更正

- 按 Git → 实际代码/migrations/tests → `Line.md` / ADR → `taskline.md` 的证据顺序重新核验；当前分支为 `agent/phase-3-files`，HEAD=`6721aa6`，无 upstream，index clean，working tree 只有未暂存 `apps/documents/services.py` 和未跟踪 `tests/test_document_lifecycle_services.py`。
- CP0–CP4 的实现提交、交接提交和线性祖先关系均真实存在；各 passed 数字只作为对应 checkpoint 的历史记录，不作为当前 dirty tree 结果。
- CP5 草稿实现软删除、回收站查询和恢复核心服务，未发现临时调试代码或需要丢弃的残缺块；当前两文件 Ruff/format check 通过。
- 首次定向测试因受限执行环境禁止访问 `127.0.0.1:5432` 而在数据库 setup 阶段报 `Operation not permitted`，不是代码失败；获准访问本机 PostgreSQL 后，当前草稿 12 项定向测试通过（0.67s）。
- 代码复核发现 staged 副本完成 SHA256/类型/扫描校验后，最终提交前只再次比较最终文件大小；同大小字节若在该窗口变化可能被错误恢复为 AVAILABLE。CP5 仍为部分实现，下一恢复点是补该竞态及回归后运行完整门禁。
- 旧记录中“需用户决定保留或丢弃”及 `HEAD=5d65906` 已不再反映当前事实；保留旧历史，本条追加更正并明确继续有效草稿。

### 2026-08-19 — Goal 异常清除后的现场恢复

- 用户报告 CP3 后设置的长时间 Goal 疑似未正常启动并已人工清除；该事件是任务编排状态异常，**不是代码失败或测试失败**。
- 现场 Git 事实为：分支 `agent/phase-3-files`，HEAD=`5d65906`，无 upstream；CP3 的 `b4038fa` / `e21f739` 均为当前 HEAD 祖先，CP4 的 `432f753` / `5d65906` 也已真实提交。
- CP3 交接提交中的 16 项定向 PostgreSQL 测试和 226 项全量回归记录与 Git 中的 `taskline.md` 一致；本次恢复未为形式重复运行它们。
- 当前 index clean，但 working tree 不 clean：`apps/documents/services.py` 有未暂存 CP5 修改，`tests/test_document_lifecycle_services.py` 是未跟踪 CP5 测试草稿；没有 staged 文件。
- CP5 草稿在较早状态曾运行 12 项定向 PostgreSQL 测试并通过，之后 `apps/documents/services.py` 又发生修改；本次恢复未运行当前树测试、Ruff、format、Django check、migration drift 或完整回归，因此 CP5 仍为未验证、未提交、未完成状态。
- 本次只更新交接事实，不继续 CP5，不提交或丢弃残留代码；下一线程必须先审计残留并取得用户对“保留续做或丢弃”的明确决定。

### 2026-08-19 — Phase 3 CP4：受控鉴权下载

- 状态：**CP4 实现和本地验证完成；CP5 尚未开始。**
- 分支：`agent/phase-3-files`，父 checkpoint `e21f739`；
- 提交 / PR：`432f753 feat(documents): add authorized file downloads`；分支尚未推送，无 Phase 3 PR。

#### 完成内容

- 新增受控 Django 下载 endpoint/service；每次请求按 User → Project → Document → FileAsset 锁序重新读取当前账号、项目、成员资格、文档和资产状态，不公开 MEDIA URL 或真实 storage path；
- 仅允许未软删除 Document + AVAILABLE FileAsset；非门户账号在对象查询前 403，项目内无权、随机 UUID、过期 VIEWER 和不可用资产统一安全失败；
- 使用 `FileResponse` attachment 响应和 Django 标准中文文件名编码，Content-Type 来自服务端检测结果，Content-Length 来自已核验元数据；
- 最终文件通过受控相对 key 打开，拒绝路径穿越、软链接和非普通文件；物理缺失/不可读转 MISSING 并写缺失与下载失败审计；大小异常时重新计算 SHA256、转 MISSING 并写完整性失败审计，不继续返回字节；
- 下载成功审计与数据库事务先完成，再返回已打开文件；审计失败或数据库最终提交失败均不产生响应，并关闭文件句柄；
- 使用真实上传文件补齐 INTERNAL、RESTRICTED、PI、MEMBER、获批及过期 VIEWER、SYSTEM_ADMIN（不依赖 LAB_MEMBER）、REIMBURSEMENT_ADMIN、外部账号、非门户账号和直接 UUID/IDOR 联合验收；
- 文件名校验同步拒绝 CR/LF、双向覆盖字符及其他 Unicode control/format 字符，避免响应头混淆；
- CP4 未实现软删除/恢复、回收站页面、完整档案 UI 或 Phase 4 内容。

#### 验证结果

- CP4 PostgreSQL 定向测试：51 项通过，1.25s；
- `scripts/check.zsh`：Ruff、90 文件 format、Django check、migration drift、239 项 PostgreSQL pytest（5.66s）和 89% coverage 全部通过；
- `git diff --check`：通过；没有 model 变化或新 migration；
- 初轮完整门禁的唯一失败来自测试夹具把 `expires_at` 设置到 `joined_at` 之前，正确触发 PostgreSQL 约束；改为合法的已过期时间窗后，定向和完整回归通过。

#### 下一步

进入 CP5，实现权限对称的文档软删除、回收站查询和恢复服务；恢复必须重新鉴权并复核项目状态、物理字节、完整性和安全检查，普通页面仍不提供永久物理删除。

### 2026-08-19 — Phase 3 CP3：可恢复上传 saga

- 状态：**CP3 实现和本地验证完成；CP4 尚未开始。**
- 分支：`agent/phase-3-files`，父 checkpoint `eaeadca`；
- 提交 / PR：`b4038fa feat(documents): add recoverable upload saga`；分支尚未推送，无 Phase 3 PR。

#### 完成内容

- 实现上传服务：锁定 User/Project 后创建持久化 TEMPORARY FileAsset/Document 意图，再在事务外执行 staging、流式摘要、真实类型/ZIP/OOXML 和扫描门禁；
- 发布前与原子移动后均按 User → Project → Document → FileAsset 重新锁定和鉴权，项目归档、账号/成员权限变化或最终文件缺失均 fail closed 到 QUARANTINED；
- 一次性 token 重复提交返回同一 Document，不重复消费上传流或产生第二资产/审计；不同 token 即使名称和 SHA256 相同仍创建独立 FileAsset；
- 安全失败、大小超限、扫描不可发布、move 失败和权限变化写入确定隔离状态、`quarantined_at`、非敏感原因及 FILE_QUARANTINED/FILE_UPLOAD_FAILED 审计；
- 成功只有在最终文件存在、全部元数据完整且成功审计与状态更新同事务提交后才进入 AVAILABLE；audit/DB 失败会保留 TEMPORARY 与最终文件，不伪装成功；
- 新增 TEMPORARY 恢复入口，重新校验大小/SHA256、类型、扫描、当前权限和物理位置后安全续跑；字节缺失则隔离，审计失败后续跑已有 PostgreSQL 回归；
- CP3 未实现下载、删除/恢复、页面、Admin 或 Phase 4 内容。

#### 验证结果

- CP3 PostgreSQL 定向测试：16 项通过，0.61s；
- `scripts/check.zsh`：Ruff、87 文件 format、Django check、migration drift、226 项 PostgreSQL pytest（4.56s）和 88% coverage 全部通过；
- `git diff --check`：通过；没有 model 变化或新 migration；
- 初轮测试真实暴露未保存的一对一 FK 验证顺序和 QUARANTINED 必须写 `quarantined_at` 两个不变量，修正后定向与两次完整门禁均通过。

#### 下一步

进入 CP4，实现受控鉴权下载、Content-Disposition、文件存在性/MISSING 转换、下载审计及 Phase 2 → Phase 3 真实文件权限/IDOR 联合验收；回收站和 UI 继续保留到后续 checkpoint。

### 2026-08-19 — Phase 3 CP2：受控存储与文件安全校验

- 状态：**CP2 实现和本地验证完成；CP3 尚未开始。**
- 分支：`agent/phase-3-files`，父 checkpoint `b57e427`；
- 提交 / PR：`69a0055 feat(documents): add secure file validation primitives`；分支尚未推送，无 Phase 3 PR。

#### 完成内容

- 新增受控存储原语：按 asset UUID 独占 staging、流式大小/SHA256、同文件系统检查、项目 UUID 最终 key、拒绝覆盖的原子发布和范围受限清理；
- 新增 PDF/PNG/JPEG 签名与终止结构检查，以及 DOCX/XLSX 的 ZIP 安全、必要 XML、主内容类型和无宏检查；
- ZIP 不落盘展开成员，但受限流式读取并验证 CRC，拒绝路径穿越、绝对/drive/反斜杠路径、空/点路径段、加密、链接/特殊文件、重复路径、嵌套 ZIP 和成员数/大小/总大小/压缩倍率超限；
- 新增扫描 adapter 和独立扫描事实；未配置扫描器只返回 `NOT_CONFIGURED`，畸形/异常返回 `ERROR`，production settings 无条件要求真实 `CLEAN` 才允许后续服务发布；
- 将上传、ZIP、OOXML 阈值及 staging 路径集中到 settings 和 `.env.example`；测试 storage 全部使用 `tmp_path`，不污染固定媒体目录；
- CP2 未实现数据库上传 saga、下载、删除/恢复、页面或 Phase 4 内容。

#### 验证结果

- CP2 非数据库定向测试：48 项通过，0.09s；
- `scripts/check.zsh`：Ruff、85 文件 format、Django check、migration drift、210 项 PostgreSQL pytest（4.23s）和 89% coverage 全部通过；
- `git diff --check`：通过；没有 model 变化或新 migration；
- 一次包含 PostgreSQL 用例的普通沙箱定向命令得到 47 项通过、2 项因 `127.0.0.1:5432 Operation not permitted` 发生环境错误；随后使用获准的项目门禁完整运行，210 项全部通过，确认不是代码或数据库缺陷。

#### 下一步

进入 CP3，实现上传服务的持久化 TEMPORARY saga、锁后重新鉴权、幂等 token、原子发布、确定状态/补偿和审计；下载、回收站与 UI 继续保留到后续 checkpoint。

### 2026-08-19 — Phase 3 CP1：模型、约束与权限

- 状态：**CP1 实现、本机迁移和本地验证完成；CP2 尚未开始。**
- 分支：`agent/phase-3-files`，父 checkpoint `b079cb6`；
- 提交 / PR：`ccf191f feat(documents): add phase three models and permissions`；分支尚未推送，无 Phase 3 PR。

#### 完成内容

- 实现 `FileAsset` 的持久化状态、扫描事实、上传幂等 token、服务器存储键、校验元数据和状态形状约束；
- 实现全局/项目级 `DocumentCategory`，含大小写不敏感唯一约束、范围不可变触发器和跨项目/停用分类数据库保护；
- 实现 `Document` 与 FileAsset 一对一生命周期、版本组骨架、单一活动当前版本、软删除管理器和上传者一致性校验；
- 扩展文件上传、失败、下载、隔离、缺失、完整性失败、软删除和恢复审计动作；
- 实现全局/项目分类管理、上传、查看、下载、编辑、软删除和恢复权限决策，覆盖 INTERNAL、RESTRICTED、归档、软删除和账号失效边界；
- CP1 未实现物理 staging、内容检测、上传/下载服务、软删除/恢复页面或 Phase 4 内容。

#### 验证结果

- 定向 PostgreSQL 测试：32 项通过，0.50s；
- `scripts/check.zsh`：Ruff、79 文件 format、Django check、migration drift、164 项 PostgreSQL pytest（4.09s）和 88% coverage 全部通过；
- `git diff --check`：通过；
- 迁移前 custom-format 快照 `.local/backups/pre-phase3-cp1-20260819.dump` 已由 `pg_restore -l` 校验，SHA-256 为 `84032884b4938045cecdc1dad97cbc6d919458416350af41bf4877738e624b55`；
- 本机开发库已成功应用 `audit.0003` 与 `documents.0001`，迁移状态为 `[X]`，复核 `No changes detected`。

#### 下一步

进入 CP2，只实现 ADR-0006 冻结的 staging、流式大小/SHA256、真实类型检测、ZIP/OOXML 安全校验和扫描适配器边界；完整上传 saga、下载、删除/恢复与 UI 保留到后续 checkpoint。

### 2026-08-19 — Phase 3 CP0：文件架构冻结

- 状态：**CP0 架构冻结完成并完成文档验证；后续已进入 CP1。**
- 分支：`agent/phase-3-files`，基线 `a203107c44ef9870161a49893de85959af4d77e2`；
- 提交 / PR：`b079cb6 docs(files): freeze phase three architecture`；尚未推送，无 Phase 3 PR。

#### 完成内容

- 从已核验 clean 且与 `origin/main` 一致的最新 main 创建 Phase 3 分支；
- 修正 README 和当前状态快照中 Phase 1 / Phase 2 已合并、最新 main CI 已通过的状态漂移；
- 新增 ADR-0006，冻结文件分类范围、版本骨架、PDF/DOCX/XLSX/PNG/JPEG/ZIP 白名单、纯 Python
  服务端类型检测、ZIP 安全阈值、生产扫描 fail-closed、持久化 TEMPORARY saga、状态恢复、幂等、权限、
  下载完整性、软删除/回收站和 User → Project → Document → FileAsset 锁序；
- 同步架构和数据库文档，明确 Document/FileAsset 一对一生命周期、服务器生成相对 storage key、
  DELETED 恢复转换和跨项目分类的数据库/服务双层校验；
- 未创建业务模型、migration、上传/下载代码或 Phase 4 内容。

#### 验证结果

- `git diff --check`：通过；
- Markdown fenced code block 配对、ADR 相对链接和当前状态关键词检查：通过；
- Git 分支与状态：`agent/phase-3-files`，CP0 已作为独立文档 checkpoint 提交；
- Python、Django、PostgreSQL、Ruff、format 和 migration drift：CP0 未运行，因为本 checkpoint 只修改文档。

#### 下一步

进入 CP1，只实现已冻结的模型、约束、文件权限、审计动作、migrations 与 PostgreSQL 测试；不提前实现
上传、下载、软删除/恢复页面或物理存储服务。

### 2026-08-19 — Phase 1 / Phase 2：stacked PR 评审、合并与 Git 基线收口

- 状态：**Phase 1 / Phase 2 最终 review、PR 合并、main CI 与本地 Git 基线收口完成；Phase 3 尚未开始。**
- 分支：`main`；
- 提交 / PR：PR #1 head `119e209` → merge commit `ad3181c`；PR #2 head `1bef3ce` → merge commit `0fccbb8`。

#### 完成内容

- 只读核验两条 PR 的 base/head、Draft、mergeability、CI、review submission 和 review thread；两条 PR 均无 review blocker 或未解决 thread；
- 完成 Phase 1 代码、migration、权限和文档最终审查，以 merge commit 合并 PR #1；
- 合并后重新 fetch 并核验真实拓扑：`119e209` 同时为最新 main 与 Phase 2 head 的祖先，`origin/main...origin/agent/phase-2-projects` 仍只包含原 Phase 2 变更；
- 因此仅将 PR #2 base 从 `agent/phase-1-auth` 调整为 `main`，没有 rebase、squash、新功能提交或历史重写；
- 复核 retarget 后 PR #2 的 46 文件 diff、权限边界、migration、锁序、事务、IDOR/CSRF、账号离组联动和 Phase 2/3 文档边界，未发现 blocker；
- 以 merge commit 合并 PR #2，并将本地 `main` fast-forward 到合并后的 `origin/main`。

#### 验证结果

- PR #1 head CI run `31371151159` success；Phase 1 merge commit `ad3181c` 的 main CI run `32257435132` success；
- PR #2 head CI run `32256185247` success；Phase 2 merge commit `0fccbb8` 的 main CI run `32257797190` success；
- PR #2 最终 review 时复跑 `scripts/check.zsh`：Ruff、75 文件 format、Django check、migration drift、132 项 PostgreSQL pytest（3.65s）和 88% coverage 全部通过；`git diff --check` 通过；
- `119e209` 与 `1bef3ce` 均已成为 `origin/main` 祖先；最终 Git 状态在本条收口记录推送后再次核验。

#### 边界与下一步

- Phase 3 尚未开始；本次没有创建 Phase 3 分支，也没有实现 FileAsset / Document / Upload / Download；
- Phase 1 / Phase 2 已具备进入下一阶段的 Git 前置条件，但必须等待新的明确指令后才创建 Phase 3 分支；
- 外部到期调度器、Docker、第二套环境、服务器部署和恢复演练仍属于后续阶段。

### 2026-08-19 — Phase 2：远端交付

- 状态：**Phase 2 可独立实现范围本地验收及实现 commit 远端 CI 完成；Draft PR #2 待评审；真实文件下载联合权限验收待 Phase 3；Phase 3 尚未开始。**
- 分支：`agent/phase-2-projects`，upstream=`origin/agent/phase-2-projects`；
- 提交 / PR：`5c68b403 feat(projects): complete phase two project system`；[Draft PR #2](https://github.com/ACM-player/Document_filing_reimbursemment_system/pull/2)，base=`agent/phase-1-auth`、head=`agent/phase-2-projects`。

#### 完成内容

- 复核 46 个 Phase 2 提交文件（28 个新增、18 个修改，6807 行新增、86 行删除），未发现 Secret、备份、截图、数据库 dump、缓存、Phase 3 实现或无关文件；
- 使用显式路径暂存并形成 Phase 2 主提交，不重写 Phase 1 历史；分支已推送并设置 upstream；
- GitHub CLI 2.97.0 通过 `dev_app` 环境调用，`ACM-player` 认证有效且具有 `repo` / `workflow` scopes，仓库权限为 ADMIN；
- GitHub App 创建 PR 因 installation 权限返回 `403 Resource not accessible by integration`，按发布技能回退到 `conda run -n dev_app gh pr create` 后成功创建 stacked Draft PR #2；
- 核验 PR #2 为 Open Draft、可合并，head 为 `5c68b403`；Phase 1 Draft PR #1 仍未合并。

#### 验证结果

- 主提交前最终 `scripts/check.zsh`：Ruff、75 文件 format、Django check、migration drift、132 项 PostgreSQL pytest（4.01s）和 88% coverage 全部通过；`git diff --check` 通过；
- 实现 commit `5c68b403` 对应 [GitHub Actions CI run 32255773119](https://github.com/ACM-player/Document_filing_reimbursemment_system/actions/runs/32255773119) 成功；`test` job 的 Ruff、format、migration drift、migration 应用及 pytest/coverage steps 全部通过；
- 本条记录作为单独文档 commit 推送后，仍需确认 PR 最新 head 的 CI；最终结果以 PR checks 与交付报告为准。

#### 未完成 / 遗留边界

- Draft PR #2 尚未评审或合并；本任务不合并 Phase 1 / Phase 2，不 rebase、squash 或调整 PR base；
- Phase 3 尚未开始，真实 FileAsset / Document / 鉴权 Download 的联合权限验收仍待 Phase 3；
- 外部到期调度器、Docker、第二套环境、服务器部署和恢复演练仍属于后续阶段。

#### 下一步

提交并推送本次 `taskline.md` 同步，确认最新 head CI 通过后停止；后续先处理 PR 评审与 stacked 分支拓扑，再另行决定是否进入 Phase 3。

### 2026-08-12 — 需求基线一致性修订

- 状态：**文档边界修订完成；Phase 2 可独立实现范围本地验收完成；真实文件下载联合权限验收待 Phase 3；远端提交、CI 与评审待办。**
- 分支：`agent/phase-2-projects`，基线 `119e209`；
- 提交 / PR：本次未暂存、未提交、未推送，也未创建 PR；Phase 3 未开始。

#### 修订内容

- 将 `Line.md` 页首改为长期有效的需求、架构与 Phase 验收基线说明，实际进度统一指向本文件；
- 将 Phase 2 验收收窄为项目元数据、可见性、成员、访问申请、VIEWER 生命周期、管理员全局访问和统一项目级权限决策；
- 将真实 Document / FileAsset / Download 的权限、安全失败、SHA256 和直接 URL / IDOR 验收明确保留在 Phase 3，并要求执行 Phase 2 → Phase 3 真实文件联合权限验收；
- 澄清 Phase 1 的系统角色边界、Phase 2 的项目级权限决策和 Phase 3 的真实文件下载之间的跨阶段验收关系；
- 完整检查其余 Phase，未发现需要修改的明确同类型跨阶段验收矛盾；
- 本次只调整 Phase 边界表述，没有改变已实现的业务需求、数据模型、权限模型、架构设计或 Phase 顺序，也没有修改业务代码、测试或 migration。

#### 验证结果

- `git diff --check` 通过；
- `Line.md` 与 `taskline.md` 的 ATX 标题层级和 fenced code block 配对检查通过；
- 人工复核 Phase 1 / Phase 2 / Phase 3 描述：项目级权限决策与真实文件下载边界一致，未发现相互矛盾；
- 人工复核两份文档的状态表述一致，Phase 3 保持未开始；
- 本次没有修改业务代码、测试或 migration，因此未重新运行 PostgreSQL 测试套件。

#### 未完成 / 遗留边界

- Phase 3 尚未开始；真实文件下载联合权限验收必须等待 Document、FileAsset 和鉴权 Download 实现后执行；
- Phase 2 工作树仍未提交或推送，GitHub Actions 和 PR 评审仍未执行。

#### 下一步

保持 Phase 3 未开始状态；先按既有交付流程处理 Phase 2 的提交、远端 CI 与评审，待另行确认后再进入 Phase 3。

### 2026-08-12 — Phase 2：发布前检查被 GitHub CLI 阻塞

- 状态：**本地验收保持通过；远端发布未开始。**
- 分支：`agent/phase-2-projects`，基线 `119e209`；暂存区为空；
- 远端：`origin/agent/phase-1-auth` 位于 `119e209`，`origin/agent/phase-2-projects` 不存在。

#### 实际检查与停止边界

- 最终工作树 `scripts/check.zsh` 再次通过：132 项 PostgreSQL pytest（3.97s）、88% coverage、Ruff、格式、Django check 和 migration drift 全部通过；
- Git 收尾复核：17 个 tracked 修改、28 个 untracked 文件、无 staged 内容，`git diff --check` 通过；
- 本机迁移保持 `audit.0002 [X]`、`projects.0001 [X]`，开发库 User / Project / ProjectType / Membership / AccessRequest / AuditLog 计数均为 0；
- 迁移前备份 SHA-256 复核一致，`pg_restore -l` 可读取 110 行目录；备份与浏览器截图均由 `.gitignore` 排除；
- 发布前置检查发现 `gh` 未安装。按 GitHub 发布工作流要求在 `gh auth status` 前停止，未执行 staging、commit、push 或 PR 创建。

#### 精确下一步

安装并认证 GitHub CLI；重新执行发布前范围确认。Phase 1 未合并时，把 Phase 2 Draft PR 堆叠到 `agent/phase-1-auth`；远端 CI 与评审稳定后再进入 Phase 3。

### 2026-08-12 — Phase 2：本地实现与验收完成

- 状态：**Phase 2 本地实现、迁移和验收完成；远端提交、CI 与评审尚未执行。**
- 分支：`agent/phase-2-projects`，基线 `119e209`；
- 提交 / PR：未提交、未推送、无 upstream、无 Phase 2 PR。

#### 完成内容

- 完成项目门户资格与系统角色边界：活跃 LAB_MEMBER 可进入；SYSTEM_ADMIN / superuser 即使不属于 LAB_MEMBER 仍有全局项目权限；其他账号在对象解析前统一 403；
- 收紧 INTERNAL 普通读者信息边界，成员目录只对可管理成员者查询和展示；
- 审批表单校验或服务错误在原页保留绑定字段和决策，自移除后跳转可访问详情；删除未使用的宽泛 Admin form；
- 补 SYSTEM_ADMIN、非门户账号、IDOR、软删除、CSRF、失败回显、只读 Admin 和成员目录回归；
- Primary 修正系统管理员无 LAB_MEMBER 时目录/详情角色展示，并由定向测试和真实浏览器复核；
- 创建并校验迁移前 PostgreSQL custom-format 快照，应用 `audit.0002` 与 `projects.0001`；
- 使用固定前缀临时数据完成多角色真实浏览器流程，之后精确清理账号、项目、成员、申请、Session 和 23 条测试审计；
- 更新 README 并新增 `docs/PHASE2_REPORT.md`，明确本地完成、远端未验证及 Phase 3/4/部署边界。

#### 验证结果

- 最终工作树 `scripts/check.zsh`：Ruff、75 文件格式、Django check、migration drift、132 项 PostgreSQL pytest（3.97s）和 88% coverage 全部通过；
- 本机 migration：`audit.0002 [X]`、`projects.0001 [X]`，`No changes detected`；
- 页面安全定向测试：34 项通过；
- 浏览器：受限最小披露、申请、失败回显、批准、撤销即时失权、INTERNAL 信息隔离、SYSTEM_ADMIN 全局创建/管理/软删除、普通非门户 403 全部通过；1280×720 和 390×844 布局正常，控制台 0 warning/error；
- 迁移前快照 SHA-256：`30d9469b5183cbbc7ad92c4e389f704b3a8237fe4155ba9afe9fbcdf3f9f8b8e`。

#### 未完成 / 遗留边界

- 工作树仍未提交或推送，Phase 2 GitHub Actions、PR 与评审没有证据；
- 外部到期调度器、Docker、第二套环境和恢复演练属于部署后续；
- FileAsset / Document、真实文件下载鉴权属于 Phase 3，报销附件联合权限属于 Phase 4；
- 申请历史时间线和软删除额外确认页可作为后续 UI 增强，不是当前 `Line.md` 的 Phase 2 阻塞。

#### 下一步

复核 Git、迁移、开发库清洁度和备份；随后审查、提交并推送 Phase 2 工作树，等待远端 CI 和评审。远端结果稳定前不提前开始 Phase 3。

### 2026-08-12 — Phase 2：授权锁序真实并发回归

- 状态：**首批五条高风险事务链已通过确定性 PostgreSQL 并发验证；Phase 2 仍未完成。**
- 分支：`agent/phase-2-projects`，基线 `119e209`；
- 提交 / PR：未提交、未推送、无 upstream、无 Phase 2 PR。

#### 完成内容

- 新增真实线程事务回归，所有 worker 使用独立数据库连接、事务内 `lock_timeout` / `statement_timeout`、事件或屏障控制顺序、join 超时和完整异常回传；
- 验证账号离组先持有目标 User 锁时，后续直接授权和访问审批均安全失败，不产生离组后活动授权；
- 验证 PI 转移与旧 PI 离组按统一锁序串行完成，规范 PI、成员角色和旧账号终态一致；
- 验证申请型成员移除与撤销并发只产生一次撤销审计；移除与到期并发只落一个终态，不死锁。

#### 验证结果

- `tests/test_project_service_concurrency.py`：连续三轮均为 5 项通过，分别用时 0.87s、0.79s、0.78s；
- 新文件 Ruff check / format check：通过；`git diff --check`：通过；
- Primary 已逐行审查测试：线程使用真实服务和 PostgreSQL 行锁，patch 仅用于线程限定的同步 hook，没有替换核心事务结果。

#### 未完成 / 遗留问题

- 当前并发集合覆盖已识别的五条最高风险链，不代表未来 Phase 或全部页面写端点自动具备并发验收；
- 页面权限入口、IDOR、CSRF、审批失败回显和成员自移除交互仍在下一里程碑处理；
- 最终 migrations、综合门禁、浏览器和 CI 仍未完成。

#### 下一步

修正项目门户角色边界并完成页面安全矩阵；随后再应用最终迁移并运行综合门禁与浏览器验收。

### 2026-08-12 — Phase 2 中断接管与当前树回归复核

- 状态：**只读接管完成；中断后遗留的服务边界、幂等和锁序实现已核实并通过当前树 PostgreSQL 回归，Phase 2 仍未完成。**
- 分支：`agent/phase-2-projects`，基线 `119e209`；
- 提交 / PR：未提交、未推送、无 upstream、无 Phase 2 PR；接管时为 16 个 tracked 修改、25 个 untracked 文件，暂存区为空。

#### 完成内容

- 完整读取 `Line.md` 与本文件；确认根目录无项目级 `AGENTS.md`，按全局规则接管；
- 核对分支、Git status、tracked / untracked / staged 状态和实际代码，确认没有语法残片或空壳函数；
- 发现中断后 `apps/projects/services.py` 已写入目标锁序辅助、审批锁后复核、服务边界和顺序幂等实现，且新增 `test_project_service_boundaries.py` 与 `test_project_service_idempotency.py`，本文件此前记录已落后于代码；
- 修正项目页面到期测试的 mock 边界：不再替换共享 `django.utils.timezone.now`，避免测试把登录 Session 一并推进到过期；真实到期服务仍执行并精确断言落库时间。

#### 验证结果

- 项目专属环境门禁确认：`/opt/miniconda3/envs/labarchive/bin/python`，Python 3.13.14；
- 接管后高风险定向 PostgreSQL pytest：首次 32 项通过、2 项失败；失败均为测试全局时间 mock 导致登录 Session 返回 302；修正后 34 项通过；
- 当前工作树完整 PostgreSQL pytest：105 项通过；
- 修正后的项目页面到期用例单独复跑：2 项通过；单文件 Ruff 通过；
- `git diff --check`：通过；
- 真实并发、完整 Ruff / Django / migration 综合门禁、本机开发库 migration、浏览器和 CI 尚未执行。

#### 未完成 / 遗留问题

- 现有幂等用例是顺序重复调用，不能证明并发审批、离组、PI 转移、移除、撤销和到期无死锁或无授权复活；
- 完整页面权限/IDOR/归档与软删除写端点、CSRF、审批失败回显、危险操作确认和成员信息边界仍待验收；
- `ProjectMembershipAdminForm(fields="__all__")` 未使用且字段范围过宽，仍需删除或收紧；
- 最终 migrations 尚未应用到本机开发库，`scripts/check.zsh`、浏览器和 CI 未运行。

#### 下一步

先补确定性 PostgreSQL 事务并发回归；通过后继续页面安全矩阵和交互边界，再应用最终迁移、运行综合门禁及浏览器验收。

### 2026-08-10 — Phase 2：账号与项目授权生命周期

- 状态：**生命周期核心已实现并通过 PostgreSQL 定向验证；最后新增的真实后台、普通移除、页面和命令集成用例待复跑，Phase 2 仍未完成。**
- 分支：`agent/phase-2-projects`，基线 `119e209`；
- 提交 / PR：未提交、未推送、无 upstream、无 Phase 2 PR；当前为 16 个 tracked 修改和 23 个 untracked 文件，暂存区为空。
- - 中断说明：本线程最终因 Codex 周使用额度耗尽被平台强制终止，未生成正常最终回复；因此最后一次 `taskline.md` 更新之后进行的锁序、幂等及相关代码调查可能存在未完成或未记录操作。下一线程必须以当前 Git 工作树、代码和实际测试重新核验，不得假定本线程自然结束或当前 Phase 已完成。

#### 完成内容

- 新增统一 `change_user_status` 服务和严格状态机；Django Admin 状态写入口改为调用该事务服务，不再单独重复写状态审计；
- 冻结 DISABLED 为临时暂停：不关闭 Membership 或 PENDING / APPROVED 申请，恢复 ACTIVE 时只归一化已经自然到期的申请授权；
- 冻结 DEPARTED / ARCHIVED 为不可逆终态：在账号状态与审计的同一事务中取消 PENDING、精确撤销 APPROVED、结束其余 DIRECT Membership；
- 账号永久离组前阻断任何未软删除项目（含 ARCHIVED 项目）的规范 PI，要求先显式转移；DISABLED PI 保留规范字段和 PI Membership；
- 关闭申请时保留原 `reviewed_by`、`reviewed_at` 和 `review_note`，关闭操作者与原因写入 append-only 审计；审计失败会回滚账号和项目关系；
- 申请型 VIEWER 从成员页移除时复用来源申请撤销路径，避免 Membership 与申请状态分叉；
- 项目详情和成员管理页改为项目级到期归一化，新增幂等 `expire_project_access` 管理命令；权限查询本身继续即时忽略过期授权；
- 新增 ADR-0005，并补账号生命周期、真实 Admin POST、普通移除、页面到期和命令用例。

#### 验证结果

- 生命周期实施后的账号/项目定向 pytest：31 项通过，使用本机 PostgreSQL 测试数据库；覆盖 DISABLED 恢复、DEPARTED/ARCHIVED 清理、PI 阻断/转移、审计失败回滚及既有项目服务和 Admin 回归；
- 到期命令无数据库 pytest：5 项通过，命令发现与 help 输出通过；1 项 PostgreSQL 行为用例主动 deselect；
- Ruff：当前 71 个 Python 文件 format check 通过，`ruff check .` 通过；Django system check 0 issues；`git diff --check` 通过；
- migration drift 返回 `No changes detected`，但沙箱无法连接 127.0.0.1:5432，迁移历史一致性检查有明确权限警告；
- 当前工作树完整 pytest 未重跑：受控 PostgreSQL 执行在新增测试后因 Codex 执行额度限制被拒。最近一次完整结果仍是生命周期修改前的 66 项通过，不能替代当前树验证；
- 新增真实 Admin POST、普通移除、项目级页面到期及命令 PG 集成测试均已写出且通过 Ruff，但本次未执行到测试体；浏览器、覆盖率、`scripts/check.zsh`、本机 migration 和 CI 未运行。

#### 未完成 / 遗留问题

- 授权入口仍存在 User / Project / Request / Membership 锁序互逆：离组可与审批、直接授权或 PI 转移竞态，成员移除也可与撤销/到期形成死锁路径；
- 重复移除、重复取消/撤销以及相同 DIRECT 角色设置尚未统一为幂等结果；
- 审批仍未在锁后复核申请人 ACTIVE + LAB_MEMBER、项目未删除/可授权及 RESTRICTED 最新状态；服务层状态和停用类型白名单仍不足；
- 账号永久终止保留系统 Group；当前受支持状态机不能恢复终态，未来若改变角色保留或恢复政策必须单独设计并审计；
- `expire_project_access` 可人工可靠运行，但 Phase 2 不内置调度器；部署外部调度器前不得宣称无人访问时持续自动落库。

#### 下一步

先统一目标 User → Project → Request → Membership 的锁顺序和锁后复核，再实现重复操作幂等及服务边界业务冲突；获得 PostgreSQL 执行权限后先运行本条新增用例，再运行当前工作树完整门禁。

### 2026-08-10 — Phase 2：授权血缘与 PI 规范事实

- 状态：**可交付项本地实现与 PostgreSQL 自动化验证完成；Phase 2 仍未完成。**
- 分支：`agent/phase-2-projects`，基线 `119e209`；
- 提交 / PR：未提交、未推送、无 upstream、无 Phase 2 PR；保留现有工作树继续处理生命周期阻塞。

#### 完成内容

- 为 `ProjectMembership` 增加 `source_access_request` nullable 一对一 `PROTECT` 关系，使每条申请授权精确绑定具体访问申请；
- 增加授权形状数据库约束：DIRECT 不关联申请且永不过期，APPROVED_REQUEST 必须关联申请且只能是 VIEWER，PI 因此只能是永久 DIRECT；
- 将 `Project.principal_investigator` 冻结为负责人规范事实，活动 PI Membership 作为必须匹配的物化授权；权限解析在两者不一致时安全失败；
- 撤销和到期改为只操作申请精确绑定的历史 Membership，删除原 project + user 模糊匹配；
- 申请授权被直接设为普通成员或 PI 时，结束旧授权行和来源申请，再创建不同 UUID 的 DIRECT 行，保留原角色、来源和到期历史；
- 直接分配成员时取消同一用户的待处理申请，陈旧审批不再生成“APPROVED 但无授权”的记录；
- 按尚未应用、尚未提交的事实重新生成 `projects.0001`，并新增 ADR-0004 及架构、数据库说明；
- 增加授权组合、一对一保护、跨项目/用户校验、PI 安全失败、多轮撤销/到期隔离、直接晋升和 PI 转移回归测试。

#### 验证结果

- 项目专属环境：Python 3.13.14，解释器 `/opt/miniconda3/envs/labarchive/bin/python`；
- 授权模型、权限和服务定向 pytest：33 项通过；服务定向复跑 13 项通过；
- 完整 pytest：66 项通过，使用 PostgreSQL 测试数据库并包含 Phase 1 回归；
- Ruff check / format：通过；Django system check：0 issues；migration drift：`No changes detected`；
- 首次接管全量测试因沙箱禁止连接本机 `127.0.0.1:5432` 产生 49 个数据库 setup error；获准连接同一本机 PostgreSQL 后原草稿 53 项通过，修改后 66 项通过，确认不是代码或数据库服务失败；
- 覆盖率、本机开发库 migration、`scripts/check.zsh`、CI 和浏览器流程本次未运行。

#### 未完成 / 遗留问题

- 账号 `DEPARTED` / `ARCHIVED` 尚未事务性结束活动 Membership 和 PENDING/APPROVED 申请，重新激活仍有授权复活风险；
- 普通成员移除尚未委托统一申请撤销路径；可靠到期执行机制和全部审计语义尚未闭环；
- 项目、申请、Membership 锁顺序及审批最新状态复核尚未统一；服务层仍信任部分表单过滤；
- 当前迁移仅在全新 PostgreSQL 测试库执行，本机开发库仍未应用；当前工作树仍不适合提交或推送。

#### 下一步

实现统一授权生命周期：明确 DISABLED 暂停语义，事务性处理 DEPARTED / ARCHIVED、普通移除、撤销和到期；补离组后重新激活不恢复旧权限及普通移除一致性回归。完成后再次更新本快照并追加历史。

### 2026-08-10 — Phase 2 中断交接：项目系统草稿

- 状态：**部分完成；不得标记为 Phase 2 完成，不建议直接提交或推送当前业务草稿。**
- 分支：`agent/phase-2-projects`，基线 `119e209`；
- 提交 / PR：本次草稿无提交、未推送、无 upstream、无 PR；`main` 当时为 `ed1443d`，Phase 1 Draft PR #1 尚未合并。

#### 完成内容

- 建立项目类型、项目、项目成员和访问申请的首版模型与约束；
- 建立项目 CRUD、软删除、PI 转移、成员管理、访问申请、审批、撤销和到期服务草稿；
- 建立权限查询、表单、视图、URL、页面、后台入口、审计动作和首版 migrations；
- 建立模型、权限、服务、页面测试草稿；
- 工作树记录为 10 个已跟踪文件修改（含当时更新的 `taskline.md`）和 16 个未跟踪文件，暂存区为空；未执行 reset、revert 或删除。

#### 验证结果

- Ruff format / check：通过；
- Django system check：0 issues；
- migration drift：No changes detected；
- Phase 2 定向测试：24 项通过；
- 完整 pytest：53 项通过，覆盖率 83%，使用 PostgreSQL 测试数据库，Phase 1 回归同时通过；
- `git diff --check`：通过；当时更新交接记录前，已跟踪业务文件差异为 463 行新增、20 行删除，未跟踪文件未计入。

#### 未完成 / 遗留问题

- `projects.0001` 和 `audit.0002` 未应用到本机开发库；
- 未运行 Phase 2 最终 `scripts/check.zsh`、GitHub Actions、浏览器流程、并发/重复提交/CSRF 专项验证；
- 已识别账号离组授权复活、申请与授权无精确关联、普通移除与撤销不一致、到期不能保证落库、审批不复核最新状态、锁序缺失、PI 双事实源及服务层校验不足等高优先级问题；
- 另有 LAB_MEMBER 移除边界、INTERNAL 成员信息暴露、审批失败回显、申请历史展示、重复移除、自移除重定向、危险操作确认和后台表单字段等问题。

#### 下一步

先修数据模型和授权生命周期，再统一锁序与服务校验并补回归测试；完成后才应用迁移、运行综合门禁和 UI 验证，并考虑提交推送。

### 2026-08-10 — 更正：进度追踪机制已提交并推送

- 状态：完成；
- 提交 / PR：`119e209 docs: add task progress log`，已推送至 `origin/agent/phase-1-auth`，Draft PR #1；
- 更正原因：上一条记录生成时文档确实尚未提交，随后已完成发布；保留原记录并追加更正，不覆盖历史状态；
- 验证结果：Draft PR #1 的 GitHub Actions 再次通过，耗时 34 秒；
- 未完成：Phase 1 分支仍是 Draft PR，尚未合并到 `main`。

### 2026-08-10 — 建立本地进度追踪机制

- 状态：记录生成时已完成文件建立，但尚未提交或推送；
- 分支：`agent/phase-1-auth`；
- 提交 / PR：记录生成时无对应提交；后续状态见上一条更正记录。

#### 完成内容

- 建立根目录 `taskline.md`；
- 定义每个任务完成后的记录字段；
- 将进度记录步骤写入总体开发流程和 README 目录说明；
- 根据 Phase 1 本地测试、远端 CI、提交和 PR 证据写入首条完整记录。

#### 验证结果

- 已核对 Phase 1 本地测试、远端 CI、提交和 PR 证据。

#### 未完成 / 遗留问题

- 该记录生成时，进度文档修改尚未提交或推送。

#### 下一步

后续每个可交付任务在交付前更新本文件，并在状态发生变化时追加更正记录。

### 2026-08-10 — Phase 1：账号、认证与审计基础

- 状态：**可独立实现的功能与本地/远端验证完成；严格按全部验收条目计算，跨阶段联合权限验收仍未闭环。**
- 分支：`agent/phase-1-auth`；
- 提交 / PR：`3cbdeee feat(auth): complete phase one authentication`、`6f5d609 ci: enable PostgreSQL data checksums`；[Draft PR #1](https://github.com/ACM-player/Document_filing_reimbursemment_system/pull/1)。

#### 完成内容

- 增加 `ACTIVE`、`DISABLED`、`DEPARTED`、`ARCHIVED` 账号生命周期及数据库一致性约束；
- 增加 Profile 和 `LAB_MEMBER`、`REIMBURSEMENT_ADMIN`、`SYSTEM_ADMIN` 固定系统角色；
- 实现登录、POST-only 退出、首次强制改密、个人改密和管理员一次性临时密码；
- 实现 12 位密码下限、12 小时 Session、关闭浏览器失效和旧 Session 失效；
- 实现用户名 HMAC 指纹、来源 IP 和五次失败/十五分钟登录限制；
- 实现登录、退出、密码、账号状态、角色和资料变更的脱敏 append-only 审计；
- 增加管理后台、基础页面、数据库迁移和 Phase 1 执行报告；
- 修正 GitHub Actions 的 PostgreSQL 初始化参数，使 CI 启用数据页校验和。

#### 验证结果

- `scripts/check.zsh`：通过；
- pytest：29 项通过，覆盖率 89%；
- Django system check：0 issues；migration drift：No changes detected；
- Ruff check / format：通过；
- 本机 PostgreSQL 17：`accounts.0002` 和 `audit.0001` 已应用；
- GitHub Actions：通过，最初记录耗时 41 秒；后续 `119e209` 推送后再次通过，耗时 34 秒。

#### 未完成 / 遗留问题

- INTERNAL / RESTRICTED 项目访问依赖 Phase 2 的项目、成员和访问申请模型；
- “报销管理员不能因角色访问受限项目档案”依赖 Phase 2 项目权限与 Phase 4 报销权限联合测试；
- Docker、管理员 MFA、反向代理真实来源 IP 和服务器部署保留到后续阶段；
- Draft PR #1 尚未合并到 `main`。

#### 下一步

冻结并实现 Phase 2 的项目字段、项目内角色、可见性、访问申请状态机和权限矩阵。

### 2026-08-10 — Phase 0：工程基础

- 状态：**本机工程基础已验证；Docker 和跨环境验收未闭环，不能标记为 Phase 0 全部完成。**
- 分支：历史工程基础工作；
- 提交 / PR：历史提交包括 `8cd4076`、`15ce6dd`、`810ccb3`；无独立 Phase 0 PR 记录。

#### 完成内容

- 建立 Django 工程、基础应用、配置分层、健康检查和工程检查脚本；
- 建立本机 Conda `labarchive` 环境及 PostgreSQL 17 开发路径；
- 固定 Python 3.13.14、Django 5.2.16 等基础依赖并记录校验信息；
- 完成基础本机 Web / health 路径和 Phase 0 报告。

#### 验证结果

- 本机 pytest：6 项通过，覆盖率 85%；
- 本机 Django / PostgreSQL 基础路径、Web 和 health 检查通过；
- 详细证据保留在 `docs/PHASE0_REPORT.md`。

#### 未完成 / 遗留问题

- Docker 路径未验证；
- 第二套全新环境验证仅部分完成；
- 恶意文件扫描、服务器部署和生产级备份恢复属于后续阶段；
- Phase 0 报告生成时 CI 尚未验证，后续 Phase 1 已建立并通过 CI，但不能据此追溯宣称 Phase 0 Docker 验收完成。

#### 下一步

在对应后续阶段分别完成 Docker、跨环境、文件安全、部署及备份恢复验收，不与本机工程基础验证混为同一完成状态。

## 5. Taskline 更新规则

1. 每次新 Codex 开发线程开始前，应先读取 `Line.md` 和 `taskline.md`，并检查 Git 实际状态。
2. `taskline.md` 顶部“当前状态快照”必须反映最新状态，包括分支、基线、工作树、远端、PR 和验证级别。
3. 每个可交付任务完成后，应更新当前状态快照，并在“工作历史”顶部追加一条记录。
4. 历史记录不因为后续状态变化而覆盖；结论变化时应追加“更正记录”并说明证据。
5. 如果 `taskline.md`、`Line.md` 和代码不一致：实际代码和测试结果用于判断“当前实现事实”，`Line.md` 用于判断“应该达到什么状态”，随后修正 `taskline.md`。
6. 不得仅因为代码存在就标记任务完成；必须区分未开始、进行中、功能实现完成但未验证、本地验证完成、CI 验证完成、跨阶段验收待办和完成。
7. 未执行的测试、迁移、CI、UI 或环境验证必须明确记录“未运行”或“未验证”。
8. 不得把后续 Phase 的实现或验收提前标记为当前 Phase 已完成。

每条历史记录原则上包含：

- 日期、Phase 或任务名称、状态；
- 分支、提交和 PR；
- 完成内容；
- 实际运行的验证及结果；
- 未完成、遗留问题和跨 Phase 依赖；
- 下一步。
