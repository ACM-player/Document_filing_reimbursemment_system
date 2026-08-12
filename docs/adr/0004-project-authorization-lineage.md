# ADR-0004：项目负责人事实源与申请授权血缘

- 状态：接受
- 日期：2026-08-10

## 背景

Phase 2 首版草稿同时使用 `Project.principal_investigator` 和 PI
`ProjectMembership` 表示负责人，但没有声明哪一处是规范事实。访问申请产生的成员关系也只记录
`APPROVED_REQUEST` 来源枚举，没有记录具体申请。多轮申请、直接晋升、撤销和到期因此可能改写历史来源，
或误终止另一轮申请产生的当前授权。

## 决策

`Project.principal_investigator` 是负责人身份的唯一规范事实。活动 PI Membership 是必须与该字段
匹配的物化授权和成员目录记录，不反向决定负责人。两者不一致时，普通项目权限安全失败；系统管理员
仍通过独立的全局权限处理修复。

`ProjectMembership.source_access_request` 使用 nullable `OneToOneField` 精确指向产生该授权的
`ProjectAccessRequest`，删除来源申请受 `PROTECT` 保护。授权形状固定为：

- `DIRECT`：不关联申请、永不过期；
- `APPROVED_REQUEST`：必须关联一条具体申请，角色只能是 `VIEWER`，到期时间可空；
- PI 因此只能是 `DIRECT`、永不过期且不关联申请。

申请产生的 Membership 是不可改写的授权历史。将申请获批的 VIEWER 直接设为普通成员、管理员或
负责人时，系统结束旧 Membership 和来源申请，再创建新的 `DIRECT` Membership；不得在原行上
覆盖来源、角色或到期时间。撤销和到期只操作申请精确关联的 Membership，不再按项目和用户模糊匹配。

数据库同表约束负责角色、来源、链接和到期形状。以下跨表不变量由事务服务和回归测试负责：

- PI Membership 的用户等于项目规范负责人；
- 申请授权的项目、用户和到期时间等于来源申请；
- 活动申请授权只对应 `APPROVED` 申请；
- 项目创建和负责人转移后，规范字段与活动 PI Membership 一致。

## 未采用方案

- 只保留 PI Membership：无法用普通约束保证每个项目恰有一个负责人，也偏离既有项目字段基线；
- 只保留 Project 负责人字段：会扩大当前页面、成员历史和角色模型的改动，并偏离数据库设计中的 PI
  Membership；
- 保留两个平等事实源：无法定义冲突时的授权结果，不满足默认拒绝原则。

## 后果

- 多轮申请、旧申请撤销和直接晋升可以保留独立、可追溯的授权历史；
- 授权撤销和到期不再可能误伤同一用户的另一轮或直接授权；
- 项目权限解析必须同时验证规范 PI 与活动 PI Membership；
- 负责人转移和账号永久离组必须使用统一事务服务维护物化 PI 授权；
- 普通 Django `CheckConstraint` 不能表达跨表相等关系，不能将服务层保证误写为数据库硬约束。
