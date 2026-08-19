# Phase 2 执行报告

- 执行日期：2026-08-12
- 开发方式：本机个人开发与调试，不部署服务器
- 当前结论：**Phase 2 项目系统已完成本地实现与验收，可以进入提交、远端 CI 和评审；这些远端交付步骤尚未执行。**

## 1. 已实现

| 范围 | 实现结果 |
| --- | --- |
| 项目模型 | `ProjectType`、`Project`、`ProjectMembership`、`ProjectAccessRequest`，UUID 主键、软删除和数据库约束 |
| 项目状态与可见性 | `PLANNING` / `ACTIVE` / `PAUSED` / `COMPLETED` / `ARCHIVED`；`INTERNAL` / `RESTRICTED` |
| 项目角色 | `PI` / `MANAGER` / `MEMBER` / `VIEWER`；`Project.principal_investigator` 为负责人规范事实 |
| 项目操作 | 创建、编辑、负责人转移、成员管理、正式归档和系统管理员软删除 |
| 项目门户资格 | 活跃 `LAB_MEMBER` 可进入；活跃 `SYSTEM_ADMIN` / superuser 即使不属于 `LAB_MEMBER` 仍具有全局管理权；其他账号在对象解析前统一拒绝 |
| 可见性 | INTERNAL 对活跃课题组成员只读；RESTRICTED 未授权成员只见最小目录信息，获批后才见完整元数据 |
| 访问申请 | 提交、批准、拒绝、取消、撤销和到期；批准默认创建精确绑定来源申请的 `VIEWER` 授权 |
| 授权血缘 | `source_access_request` 一对一绑定；撤销、到期和直接晋升只处理对应授权，不误伤后续申请 |
| 账号生命周期 | `DISABLED` 暂停但保留授权历史；`DEPARTED` / `ARCHIVED` 事务性关闭项目关系，未转移 PI 会安全阻断 |
| 并发与幂等 | 统一 User → Project → AccessRequest → Membership 锁序；锁后复核、业务冲突转换和重复操作幂等 |
| 页面与后台 | 项目目录、详情、表单、成员管理和访问审批页面；项目后台只读、项目类型后台可配置 |
| 审计 | 项目、成员、负责人、访问申请、撤销、到期和账号撤权关键操作写入 append-only 审计 |

## 2. 数据库迁移与迁移前快照

在迁移前对本机开发库生成 PostgreSQL custom-format 快照：

```text
.local/backups/pre-phase2-20260812-migration.dump
SHA-256 30d9469b5183cbbc7ad92c4e389f704b3a8237fe4155ba9afe9fbcdf3f9f8b8e
```

快照已通过 `pg_restore -l` 读取目录。迁移前开发库没有用户或审计业务数据；浏览器验收使用固定前缀的临时数据，完成后已精确清理，开发库仅保留迁移结构。

已在本机 PostgreSQL 17 应用：

```text
audit.0001_initial                  [X]
audit.0002_alter_auditlog_action    [X]
projects.0001_initial               [X]
```

`python manage.py makemigrations --check --dry-run` 返回 `No changes detected`，模型与 migration 无漂移。

## 3. 自动化验证

所有 Python、Django 和 pytest 命令均使用项目专属 Conda 环境 `labarchive`，测试数据库为 PostgreSQL，不使用 SQLite。

综合门禁 `scripts/check.zsh` 结果：

```text
Ruff check                         通过
Ruff format --check                75 个 Python 文件通过
Django system check                0 issues
makemigrations --check --dry-run   No changes detected
pytest                             132 passed in 3.97s
coverage                           88%
```

综合测试覆盖：

- 模型约束、授权形状、PI 规范事实和软删除；
- INTERNAL / RESTRICTED、项目角色、系统角色及账号状态权限矩阵；
- 创建、更新、成员设置/移除、负责人转移和访问申请全生命周期；
- 服务层陈旧对象复核、字段白名单、顺序幂等和唯一约束冲突；
- DEPARTED / ARCHIVED 撤权、DISABLED 恢复、真实 Django Admin POST；
- 跨项目 UUID / IDOR、软删除对象、POST-only 与 CSRF；
- 到期即时失效、页面归一化和 `expire_project_access` 命令幂等。

另有五个使用独立连接和真实 PostgreSQL 行锁的线程事务用例，连续三轮均为 5 项通过：

1. 账号离组与直接成员授权；
2. 账号离组与访问审批；
3. PI 转移与旧 PI 离组；
4. 申请型成员移除与访问撤销；
5. 成员移除与授权到期。

## 4. 真实浏览器验收

使用本机 `127.0.0.1:8000` 和可精确清理的临时数据完成多角色真实浏览器流程：

- 未授权成员只见 RESTRICTED 项目的名称、编号、负责人和状态，项目说明未泄露；
- 提交访问申请后保持最小视图；负责人选择“拒绝”但不填原因时，原页保留选择并显示字段错误；
- 批准后申请人获得 `VIEWER` 并可查看完整项目，不能管理成员；
- 系统管理员撤销后，申请人立即回到最小视图且可重新申请；
- INTERNAL 普通读者可见项目说明，但看不到其他成员或授权到期元数据；
- 非 `LAB_MEMBER` 且非系统管理员的活跃账号访问目录和已知项目 UUID 均返回 403；
- 非 `LAB_MEMBER` 的 `SYSTEM_ADMIN` 可查看全部项目、显示正确角色、编辑、管理成员、创建及软删除项目；
- 1280×720 桌面视口和 390×844 移动视口布局正常，浏览器控制台无 warning/error。

浏览器验收生成的账号、项目、Membership、申请、Session 和测试审计均已按固定前缀精确清理，没有留下业务数据。

## 5. 明确保留到后续阶段

| 项目 | 当前边界 | 处理阶段 |
| --- | --- | --- |
| 提交、推送、远端 CI 和 PR 评审 | 本地工作树尚未提交；不能把本地门禁写成远端通过 | Phase 2 交付后续 |
| 项目文件上传、下载和档案级鉴权 | Phase 2 只冻结项目元数据与未来文件权限函数；没有 FileAsset / Document | Phase 3 |
| 报销附件联合权限 | 已证明报销管理员不会仅凭系统角色读取 RESTRICTED 项目；附件模型尚不存在 | Phase 4 |
| 无人访问时持续到期落库 | 权限查询即时失效，页面和幂等命令可归一化；生产外部调度尚未配置 | 部署阶段 |
| Docker、第二套全新环境和恢复演练 | 本机 Conda + PostgreSQL 路径不能替代跨环境验收 | 部署准备阶段 |
| MFA、TLS、可信反向代理和服务器监控 | 当前仅本机个人使用 | Phase 10 / 上线前 |

这些保留项不会被标记为已验证，也不阻止 Phase 2 的本地实现验收。
