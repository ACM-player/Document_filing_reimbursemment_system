# Phase 1 执行报告

- 执行日期：2026-08-10
- 开发方式：本机个人开发与调试，不部署服务器
- 当前结论：**Phase 1 的账号与认证范围已完成本地实现和验证，可以开始 Phase 2；依赖项目模型的跨模块权限验收保留到 Phase 2。**

## 1. 已实现

| 范围 | 实现结果 |
| --- | --- |
| 账号模型 | `ACTIVE`、`DISABLED`、`DEPARTED`、`ARCHIVED` 生命周期；数据库约束保证状态与 `is_active` 一致 |
| 个人资料 | 自动创建一对一 Profile；用户只能自助修改显示名称、邮箱、院系、学工号和电话 |
| 系统角色 | 固定初始化 `LAB_MEMBER`、`REIMBURSEMENT_ADMIN`、`SYSTEM_ADMIN`；新账号自动加入基础成员角色 |
| 登录与退出 | 无公开注册；统一失败提示；安全校验登录后的 `next` 地址；退出仅允许 POST |
| 首次改密 | 管理员创建或重置后设置 `must_change_password`，中间件限制用户只能改密或退出 |
| 密码重置 | 系统管理员生成一次性临时密码；只在本次响应显示，并禁止响应缓存 |
| 登录限制 | 同一规范化用户名与来源 IP 在 15 分钟内失败 5 次，限制登录 15 分钟 |
| Session | 最长 12 小时，关闭浏览器失效；密码修改和账号停用后旧 Session 在下一次请求失效 |
| 审计 | 登录成功/失败、退出、密码修改与重置、账号创建/状态、角色和资料变更；记录 request ID、IP 与 User-Agent |
| 审计保护 | 应用层 append-only；不提供编辑或删除入口；失败登录只保存用户名 HMAC 指纹，不保存密码和原始用户名 |
| 管理后台 | 用户创建、生命周期管理、固定角色分配、资料管理员备注、一次性临时密码重置和只读审计日志 |

## 2. 数据库迁移

已在本机 PostgreSQL 17 应用：

```text
accounts.0001_initial                                      [X]
accounts.0002_loginthrottle_userprofile_alter_user_options_and_more [X]
audit.0001_initial                                         [X]
```

新增核心表：

- `accounts_userprofile`
- `accounts_loginthrottle`
- `audit_auditlog`

## 3. 本地验证

所有命令均在项目专属 Conda 环境 `labarchive` 中运行，使用 PostgreSQL 测试数据库，不使用 SQLite。

```text
python manage.py check
结果：0 issues

python manage.py makemigrations --check --dry-run
结果：No changes detected

pytest --cov --cov-report=term-missing
结果：29 passed；总覆盖率 89%

ruff check .
结果：通过

ruff format --check .
结果：通过
```

自动化验证覆盖：

- 新账号 Profile 与基础角色初始化；
- 账号状态和 `is_active` 数据库约束；
- 正常登录、安全跳转和脱敏审计；
- 禁用、离组、归档账号拒绝登录；
- 停用账号和修改密码使旧 Session 失效；
- 首次登录强制改密；
- 五次失败后的用户名/IP 组合限制；
- 个人资料字段白名单；
- POST-only 退出；
- 管理员一次性临时密码重置；
- 审计记录不可通过普通模型和 QuerySet API 修改或删除；
- PostgreSQL 17 与数据页校验和基线。

## 4. 明确保留到后续阶段

| 项目 | 原因 | 处理阶段 |
| --- | --- | --- |
| `INTERNAL` / `RESTRICTED` 项目访问 | 项目、成员和访问申请模型尚未实现 | Phase 2 |
| 报销管理员不能继承受限项目访问 | 需要项目权限与报销权限联合测试 | Phase 2 和 Phase 4 |
| 管理员 MFA | 当前仅本机个人使用；多人或远程访问前重新评估 | 服务器部署前 |
| 代理后的真实来源 IP | 当前只信任本机 `REMOTE_ADDR`；部署时需配置可信反向代理 | Phase 10 |
| Docker 路径 | 当前电脑未安装 Docker，沿用 Phase 0 未验证项 | 部署准备阶段 |

这些保留项不会被标记为已验证，也不能用本地认证测试代替。
