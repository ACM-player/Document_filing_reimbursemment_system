# LabArchive / LabOffice
# 课题组科研事务、报销与数字档案管理平台
## 项目总体设计与开发计划书

---

> 文档状态：需求、架构与 Phase 验收基线
> 实际开发进度与验证状态：见 `taskline.md`
> 最近修订：2026-08-12
> 本次修订重点：校准 Phase 2 与 Phase 3 的验收边界，不改变既有业务需求和架构设计。
> 对应远端github仓库为：https://github.com/ACM-player/Document_filing_reimbursemment_system.git

---

# 1. 项目概述

## 1.1 项目名称

暂定名称：

**LabArchive / LabOffice**

中文名称：

**科研事务、报销与数字档案管理平台**

项目名称后续可以修改，不应在核心代码中大量硬编码品牌名称。

---

## 1.2 项目定位

本项目不是一个简单的“报销网页”或“文件上传系统”，而是一个面向科研课题组长期使用的内部信息管理平台。

系统预计长期运行：

- 5 年
- 10 年
- 20 年
- 甚至更长时间

因此必须优先考虑：

- 数据长期保存
- 数据迁移能力
- 文件可恢复性
- 数据库可维护性
- 权限安全
- 操作审计
- 备份恢复
- 软件升级
- 文件检索
- 系统可扩展性
- 避免厂商锁定
- 避免数据只能依赖当前软件读取

系统第一阶段主要包括两个核心业务：

1. 报销管理
2. 项目文件与合同档案管理

未来可继续扩展：

- 科研设备管理
- 耗材管理
- 论文管理
- 专利管理
- 实验数据管理
- 软件与代码归档
- 会议记录
- 课题组资产管理
- 项目全过程管理
- OCR
- AI 文件识别
- AI 自然语言搜索

---

# 2. 核心设计原则

整个项目开发过程中必须长期遵循以下原则。

---

## 2.1 数据优先于软件

任何情况下：

**数据的重要性高于程序本身。**

即使未来：

- 当前开发者毕业
- Python 版本变化
- Django/FastAPI 停止维护
- 当前数据库损坏
- 当前 Web 系统无法运行

实验室原始文件仍然必须能够直接访问。

因此：

- PDF 仍为 PDF
- Word 仍为 DOCX
- Excel 仍为 XLSX
- 图片仍为 PNG/JPG
- 压缩包仍为 ZIP

禁止设计只有当前软件才能读取的专有文件格式。

---

## 2.2 数据库只保存元数据，不直接保存大型附件

数据库用于保存：

- 文件名称
- 文件路径
- 所属项目
- 上传者
- 文件分类
- 文件大小
- MIME 类型
- SHA256
- 创建时间
- 修改时间
- 文件版本
- 权限信息
- 删除状态

真实附件文件保存在服务器文件系统。

原则上禁止把 PDF、Word、图片等大型二进制文件直接存入 PostgreSQL。

---

## 2.3 业务数据与物理文件路径解耦

数据库中的业务对象不能过度依赖人工文件夹名称。

推荐：

```text
Document
    id
    project_id
    category_id
    file_asset_id

FileAsset
    id
    original_filename
    stored_filename
    relative_path
    sha256
```

用户修改：

- 项目名称
- 文件显示名称
- 分类名称

不能导致数据库关系失效。

---

## 2.4 所有关键对象使用不可变 ID

用户、项目、报销、文件等核心对象必须使用内部唯一 ID。

推荐：

- UUID
- 或数据库自增 ID + UUID 外部标识

禁止把：

- 姓名
- 项目名称
- 文件名

作为系统核心关联键。

---

## 2.5 默认不进行真正物理删除

核心数据默认采用：

**软删除机制。**

用户点击删除：

```text
正常
↓
已删除
↓
回收站
↓
管理员永久删除
```

重要文件删除必须留下审计记录。

---

## 2.6 重要修改必须可追溯

系统必须保存操作日志。

至少包括：

- 谁
- 什么时间
- 做了什么
- 对哪个对象
- 修改前状态
- 修改后状态
- 请求 IP
- 必要时记录 User-Agent

关键行为：

- 登录
- 上传
- 下载
- 修改
- 删除
- 恢复
- 更改权限
- 更改报销状态
- 创建项目
- 删除项目

都应该有审计记录。

---

## 2.7 开发过程中严格保持环境隔离门禁

开始时使用本地 Miniconda 新建项目专属虚拟环境，项目以后的所需包应安装在此虚拟环境中。

每次执行以下操作前都必须先激活并确认当前处于项目专属环境：

```text
安装依赖
生成 migration
运行 Django 命令
运行测试
执行格式化或静态检查
```

不得使用系统 Python 或其他项目的既有虚拟环境代替。

---

## 2.8 原始上传文件默认不可变

文件成功入库并计算 SHA256 后，不允许直接覆盖原物理文件。

用户执行“替换文件”时，应：

```text
创建新的文件资产
+
创建新的文档版本或附件记录
```

原版本按权限和保留策略继续保存。这样可以降低数据库记录、SHA256 与真实文件内容不一致的风险，并提高增量备份和长期校验的可靠性。

---

## 2.9 默认最小权限与安全失败

系统默认遵循：

```text
没有明确授权 = 拒绝访问
权限判断异常 = 拒绝访问
文件安全检查未完成 = 不允许下载或使用
```

任何新页面、下载入口、导出任务和 API 都必须显式声明访问规则，不能依赖“界面上没有显示链接”来实现权限控制。

---

# 3. 推荐技术栈

## 3.1 第一阶段推荐架构

采用单体 Web 架构。

推荐：

```text
Backend:
Python 3.x
Django

Database:
PostgreSQL

Frontend:
Django Templates
HTMX
Tailwind CSS

Reverse Proxy:
Nginx

WSGI/ASGI:
Gunicorn / Uvicorn

Deployment:
Docker Compose

File Storage:
Linux Server File System

Version Control:
Git

Production OS:
Linux
```

---

## 3.2 暂时不要前后端完全分离

V1 阶段原则上不要使用：

```text
React + 独立API
Vue + 独立API
Node.js 前端服务器
复杂微服务
```

原因：

- 增加部署复杂度
- 增加维护成本
- 增加认证复杂度
- 增加长期升级成本
- 当前业务并不需要高复杂度 SPA

优先：

```text
Django
+
HTMX
+
Tailwind
```

实现现代 Web 交互。

---

## 3.3 API 预留

虽然第一版不完全前后端分离，但业务层不得与 HTML 强耦合。

未来应可以增加：

```text
/api/v1/
```

为：

- 移动端
- 自动化程序
- AI Agent
- OCR 服务
- 第三方系统

提供接口。

---

## 3.4 本地优先开发与个人试运行

前期需求和业务流程仍有较多不确定性，V1 在功能基本稳定前采用：

```text
本地开发
↓
自动化测试
↓
个人试运行
↓
修正数据模型与交互
↓
本地备份、恢复和导出验证
↓
实验室服务器试部署
```

本地阶段要求：

- 使用项目专属 Miniconda 环境；
- 开发数据库仍使用 PostgreSQL，不得为了方便静默改用 SQLite；
- 服务默认只监听本机，不开放至局域网或公网；
- 数据库、媒体目录、临时目录和 Secret 均通过环境变量配置；
- development 与 production 配置从一开始分离；
- 可以延后 Nginx、HTTPS、域名和服务器监控，但不能延后权限、migration、SHA256、软删除、审计接口和备份设计；
- 个人调试优先使用可丢弃数据，开始录入真实合同或报销材料后必须执行有效备份；
- 定期验证全新环境启动，避免系统只能在当前电脑上运行。

从本地试运行进入服务器部署前，至少满足：

```text
核心业务流程稳定
自动化测试与权限测试通过
PostgreSQL migration 可在全新数据库执行
项目导出可脱离软件读取
数据库与附件已完成一次联合恢复
Linux / 容器环境兼容性验证通过
服务器参数、RPO、RTO 和备份目标已确认
```

---

# 4. 系统总体架构

```text
Windows / macOS / Linux / Mobile
                │
                │ Browser
                ▼
            Nginx
                │
                ▼
             Django
        ┌───────┴────────┐
        │                │
        ▼                ▼
   PostgreSQL        File Storage
        │                │
        │                │
 Metadata / ACL       PDF/DOCX/XLSX
        │                │
        └────────┬───────┘
                 │
                 ▼
              Backup
```

---

# 5. 用户角色与权限体系

权限必须采用 RBAC 思路设计，但不要把业务规则完全写死。

---

## 5.1 初始角色

### 系统管理员

权限：

- 系统最高权限
- 用户管理
- 角色管理
- 项目管理
- 分类管理
- 所有报销查看
- 所有文件查看
- 操作日志查看
- 系统配置
- 回收站管理

---

### 报销管理员

权限：

- 查看全部报销
- 按用户查看
- 按项目查看
- 按状态查看
- 修改报销处理状态
- 添加管理员备注
- 导出报销数据
- 查看报销附件

原则上不得自动获得全部项目档案管理权限。

---

### 项目负责人

可以：

- 查看负责项目
- 管理项目成员
- 上传项目文件
- 查看项目文件
- 管理项目分类
- 查看关联报销
- 修改部分项目元数据

---

### 普通成员

可以：

- 查看自己的报销
- 创建自己的报销
- 修改未锁定报销
- 上传附件
- 查看所有“课题组内部可见”项目及其文件
- 对受限项目提交访问申请
- 上传有权限项目的文件
- 根据项目角色管理有权限的项目文件

---

## 5.2 权限模型

至少考虑：

```text
CustomUser
Django Group
Django Permission
ProjectMembership
```

ProjectMembership 可以包含：

```text
project
user
role
can_view
can_upload
can_edit
can_manage_members
```

V1 可适度简化，但数据库必须预留项目级权限能力。

V1 的实现原则：

```text
系统级角色与权限：优先使用 Django Group + Permission
项目级角色与权限：使用 ProjectMembership
对象查询：先按当前用户权限限定 QuerySet
对象操作：提交时再次执行服务端权限检查
```

除非 Django 自带权限模型确实无法满足需求，不额外复制一套功能重叠的 Role / Permission 系统。

管理员后台、普通页面、下载入口、导出任务和未来 API 必须复用同一组权限规则，避免不同入口权限不一致。

V1 不实现含义不清的单成员 Boolean 权限开关。访问判断采用：

```text
系统管理员全局权限
+
项目成员角色权限
+
项目可见性赋予的内部只读权限
+
系统默认拒绝
```

如果未来实现单成员例外权限，对应字段必须能够区分“未设置、明确允许、明确拒绝”三种状态；不能用一个默认 `False` 的 Boolean 同时表示“继承角色”和“明确拒绝”。

---

## 5.3 V1 系统级角色矩阵

系统级角色使用 Django Group。正常成员可以同时拥有附加角色，权限取合法授权的并集，但项目档案与报销附件继续使用各自独立的业务边界。

| 权限 | 课题组成员 | 报销管理员 | 系统管理员 |
| --- | --- | --- | --- |
| 登录、修改自己的资料和密码 | 是 | 是 | 是 |
| 管理自己的报销 | 是 | 是 | 是 |
| 按项目可见性和项目角色访问档案 | 是 | 是 | 是 |
| 查看全部报销及报销附件 | 否 | 是 | 是 |
| 处理、备注和导出报销 | 否 | 是 | 是 |
| 查看受限且未加入项目的档案 | 否 | 否 | 是 |
| 创建、禁用、离组和归档用户 | 否 | 否 | 是 |
| 分配预定义系统角色 | 否 | 否 | 是 |
| 查看审计日志、管理回收站和系统配置 | 否 | 否 | 是 |
| 使用 Django 管理后台 | 否 | 否 | 是 |

补充规则：

- `is_staff` 只表示 Django 管理后台访问资格，不等于业务最高权限；
- `is_superuser` 不作为日常角色，仅用于初始化或紧急恢复；
- 正式多人使用时应保留独立应急超级管理员账号；
- Phase 1 的角色定义由代码和 migration 固定；系统管理员只能给用户分配预定义角色，暂不开放任意编辑 Permission；
- 报销管理员不会因系统角色自动获得受限项目档案权限。

---

## 5.4 项目可见性与访问申请

项目增加：

```text
visibility
```

V1 支持两种可见性：

```text
INTERNAL
课题组内部可见，默认值

RESTRICTED
受限项目
```

权限规则：

- 所有 `ACTIVE` 状态的已登录课题组成员都可以查看和下载 `INTERNAL` 项目及其正常文件；
- 内部只读权限不包含上传、修改元数据、删除、管理分类或管理成员；
- `RESTRICTED` 项目只允许系统管理员、项目成员和获得批准的申请人访问；
- 未获授权的正常成员只能看到受限项目的最小目录信息：项目名称、编号、负责人、状态和“申请访问”入口，不能看到描述、文件或关联报销；
- 无权访问受限项目的正常成员可以提交访问申请并填写用途；
- 项目负责人、项目管理员或系统管理员可以批准、拒绝或撤销访问；
- 批准访问默认创建 `VIEWER` 项目成员关系，可设置到期时间；
- 批准申请不得把已有的负责人、管理员或成员降级为 `VIEWER`；
- 访问申请、审批、拒绝、撤销和到期必须写审计日志；
- V1 先采用项目级可见性，不增加文档级例外开关；如将来确需单文件保密，再单独设计。

项目档案开放不改变报销隐私：发票、支付截图、个人订单等报销附件不属于“内部可见项目文件”。

---

## 5.5 V1 项目角色矩阵

| 权限 | 项目负责人 | 项目管理员 | 项目成员 | 只读成员 |
| --- | --- | --- | --- | --- |
| 查看项目和下载文件 | 是 | 是 | 是 | 是 |
| 修改项目基本信息 | 是 | 部分 | 否 | 否 |
| 管理项目成员 | 是 | 是，但不能更换负责人 | 否 | 否 |
| 管理文档分类 | 是 | 是 | 否 | 否 |
| 上传项目文件 | 是 | 是 | 是 | 否 |
| 修改、软删除全部项目文件 | 是 | 是 | 否 | 否 |
| 修改、软删除自己上传的文件 | 是 | 是 | 是，仅项目未归档时 | 否 |
| 查看其他成员的关联报销概要 | 是 | 是 | 否 | 否 |
| 查看其他成员的报销附件 | 否 | 否 | 否 | 否 |

关联报销概要只包括标题、人员、项目、类别、金额、日期和状态。其他成员的报销附件只允许报销管理员和系统管理员查看。

所有 `ACTIVE` 课题组成员都可以创建项目，创建者自动成为项目负责人。更换项目负责人和正式归档暂由系统管理员执行。

---

# 6. 用户系统

## 6.1 用户字段

项目必须在第一次正式 migration 前创建自定义 Django User 模型，并设置：

```text
AUTH_USER_MODEL
```

即使初期仅继承 Django `AbstractUser`，也不能先使用默认 User、投入开发后再替换。

User 至少包含：

```text
id
username
display_name
email
account_status
must_change_password
is_active
is_staff
created_at
updated_at
last_login
```

可扩展 Profile：

```text
department
student_or_staff_id
phone
notes
avatar
```

其中电话等非核心字段不是 V1 必需。

---

## 6.2 用户生命周期

支持：

```text
ACTIVE：正常
DISABLED：临时禁用
DEPARTED：离组
ARCHIVED：归档
```

用户离开课题组后不得直接删除。

原因：

历史记录仍然需要显示：

```text
某文件由 XXX 于 2027 年上传
```

因此离组用户应该：

```text
account_status = DEPARTED
is_active = false
```

而不是删除数据库记录。

用户禁用或离组后：

- 不得继续创建新的登录会话；
- 应使既有会话在合理时间内失效；
- 历史上传、报销、审计记录仍保留原归属；
- 不得通过重新分配所有历史记录来“清理用户”。

V1 默认由管理员创建和启用账号，不开放匿名注册。若未来增加统一身份认证或账号申请，应单独记录架构决策。

`account_status` 是业务生命周期状态，Django `is_active` 是认证门禁。两者必须保持：

```text
account_status == ACTIVE
等价于
is_active == true
```

只能通过统一账号服务修改状态，并使用数据库约束和测试防止两者不一致。

---

## 6.3 账号创建与个人资料

V1 确认采用：

- 不开放公开注册；
- 系统管理员创建账号；
- 使用唯一 `username` 登录；
- 邮箱可选，V1 不要求唯一；
- 管理员生成一次性临时密码，通过线下方式交付；
- `must_change_password = true` 时，用户首次登录后只能进入修改密码、退出和必要说明页面；
- 用户可以修改自己的显示名称、邮箱和密码；
- 用户不能修改自己的用户名、账号状态和角色；
- 未配置邮件系统前，由系统管理员执行密码重置；
- 系统不得记录或再次显示明文临时密码。

---

## 6.4 密码、登录限制与 Session

V1 安全基线：

```text
最短密码长度：12 位
连续失败阈值：同一用户名与来源 5 次
限制时间：15 分钟
Session 最长时间：12 小时
关闭浏览器：Session 失效
```

登录失败统一提示，不得暴露用户名是否存在。禁用账号、离组、归档和密码修改后，旧 Session 必须在下一次请求时失效。

当前本地个人试运行不强制 MFA；正式服务器开放多人使用或远程访问前，必须重新评估管理员 MFA。

---

## 6.5 认证与角色审计

Phase 1 起至少记录：

```text
LOGIN_SUCCESS
LOGIN_FAILED
LOGOUT
PASSWORD_CHANGED
PASSWORD_RESET_BY_ADMIN
USER_CREATED
USER_STATUS_CHANGED
ROLE_ASSIGNED
ROLE_REMOVED
```

登录失败审计不得记录密码、Cookie、Session、认证头或其他 Secret。账号禁用、角色变更和管理员密码重置必须与审计写入保持事务一致性。

---

# 7. 项目管理模块

Project 为整个系统最重要的核心实体之一。

---

## 7.1 项目字段

建议：

```text
id
uuid
project_code
name
short_name
project_type
status
visibility
principal_investigator
start_date
end_date
description
created_by
created_at
updated_at
deleted_at
```

---

## 7.2 项目状态

初始：

```text
筹备
进行中
暂停
已完成
已归档
```

状态应使用可扩展 Enum 或系统配置。

---

## 7.3 项目类型

管理员可配置：

```text
国家自然科学基金
省部级项目
校级项目
企业横向
实验室内部项目
采购项目
其他
```

不能在代码里硬编码全部类别。

---

## 7.4 项目成员

一个项目可以拥有多个成员。

例如：

```text
项目负责人
项目管理员
成员
只读成员
```

项目角色负责上传、修改、成员管理等操作权限；它不再是 `INTERNAL` 项目的只读访问前提。

---

## 7.5 项目访问申请

`ProjectAccessRequest` 至少包含：

```text
id
project_id
requester_id
reason
status
reviewed_by_id
review_note
requested_at
reviewed_at
expires_at
```

状态：

```text
PENDING
APPROVED
REJECTED
CANCELLED
EXPIRED
```

同一用户对同一项目最多只能存在一条待处理申请。批准后默认授予 `VIEWER` 成员关系；撤销、到期或用户离组后必须失效。

---

# 8. 项目档案系统

---

## 8.1 文件分类

系统内置常见分类：

```text
立项材料
申报材料
投标材料
招标材料
合同
技术协议
采购文件
中期报告
年度报告
实验资料
财务材料
验收材料
结题材料
成果材料
其他
```

但管理员和有权限用户可以创建自定义分类。

---

## 8.2 避免纯自由文本分类

文件类别不应该只使用：

```text
category = "用户输入字符串"
```

否则会出现：

```text
合同
合同文件
采购合同
合同扫描件
Contract
正式合同
```

数据库应存在：

```text
DocumentCategory
```

用户可以：

1. 选择已有分类
2. 新建分类

之后其他用户可以复用。

---

## 8.3 统一文件资产

项目文档和报销附件应复用同一套底层文件安全与存储机制，避免分别实现上传、校验、删除、恢复和备份逻辑。

建议建立不可变的 `FileAsset`：

```text
id
uuid
original_filename
stored_filename
relative_path
declared_mime_type
detected_mime_type
file_size
sha256
storage_status
uploaded_by
created_at
quarantined_at
deleted_at
```

其中：

- `relative_path` 必须是相对于受控存储根目录的路径，禁止保存任意绝对路径；
- `stored_filename`、`relative_path` 和 `sha256` 入库后不得静默修改；
- `Document` 与 `ExpenseAttachment` 通过外键引用 `FileAsset`；
- V1 默认一个 `FileAsset` 只归属于一个业务附件记录，暂不因 SHA256 相同就自动共享物理文件；
- 重复文件检测只提示或记录，不得在没有明确生命周期设计时自动去重；
- 物理文件缺失、被隔离或校验失败时，业务记录仍保留并显示异常状态。

---

## 8.4 文件记录

Document 至少包含：

```text
id
uuid
project_id
category_id
title
description
file_asset_id
document_date
version
is_final
uploaded_by
created_at
updated_at
deleted_at
```

---

## 8.5 文件版本

系统至少预留：

```text
document_group_id
version
is_current
```

未来可以实现：

```text
合同 V1
合同 V2
合同 V3
合同最终版
```

而不是上传多个完全独立文件。

V1 如果暂时不做完整版本管理，也必须为后续扩展保留数据结构可能性。

版本规则至少明确：

- 替换文件时创建新版本，不覆盖旧 `FileAsset`；
- 同一文档组在正常状态下只能有一个当前版本；
- 版本号由服务端生成，不能仅依赖用户输入；
- 删除当前版本后，是否自动回退到上一版本必须通过业务规则显式处理；
- `is_final` 是业务标记，不代表文件可以绕过版本和审计规则被覆盖。

---

## 8.6 SHA256

每次文件上传后计算：

```text
SHA256
```

保存到数据库。

用途：

- 检测文件重复
- 检测文件损坏
- 检查文件是否被修改
- 长期数据完整性验证

后期增加：

```text
定期完整性检查任务
```

SHA256 只能证明当前读取内容与已记录内容是否一致，不能替代备份、访问控制或恶意文件检测。

---

# 9. 报销管理模块

---

## 9.1 Expense 基本字段

```text
id
uuid
title
user_id
project_id
category_id
amount
expense_date
status
description
admin_note
created_at
updated_at
submitted_at
completed_at
deleted_at
```

金额必须使用：

```text
Decimal
```

禁止使用 float。

---

## 9.2 报销分类

ExpenseCategory 独立数据表。

例如：

```text
差旅费
材料费
实验耗材
加工费
设备费
软件费
会议费
出版费
办公费
其他
```

管理员可以新增、禁用、排序。

---

## 9.3 报销状态

推荐：

```text
DRAFT
SUBMITTED
PROCESSING
REIMBURSED
ARCHIVED
RETURNED
CANCELLED
```

中文：

```text
草稿
已提交 / 待受理
报销处理中
已报销
已归档
已退回
已取消
```

界面可以在“我的报销”中提供简单勾选式视觉提示，但底层必须保存完整状态，而不是一个 Boolean。

V1 基础状态流转：

```text
DRAFT ──提交──> SUBMITTED ──受理──> PROCESSING ──完成──> REIMBURSED ──归档──> ARCHIVED
                   │                    │
                   └────退回────────────┘
                            ↓
                         RETURNED ──修改并重新提交──> SUBMITTED

DRAFT / RETURNED ──取消──> CANCELLED
```

状态流转必须由服务端统一执行，禁止普通表单任意写入状态字段。

至少遵循：

- 普通成员只能提交、重新提交或取消自己的报销；
- 报销管理员可以受理、退回、确认已报销和归档；
- 提交后普通成员不得修改金额、项目、日期和附件，必须先由管理员退回；
- 退回必须填写原因；
- 每次状态变化必须记录操作者、时间、旧状态、新状态和备注；
- 状态流转与修改锁定规则必须有专门测试。

---

## 9.4 报销附件

ExpenseAttachment：

```text
id
expense_id
file_asset_id
attachment_type
uploaded_by
created_at
deleted_at
```

支持：

- 发票
- 支付截图
- 订单
- 合同
- 行程单
- 说明材料
- PDF
- 图片
- Office 文件
- ZIP

---

## 9.5 我的报销

普通成员默认看到：

```text
我的报销
```

支持筛选：

```text
时间
项目
类别
状态
金额范围
关键词
```

---

## 9.6 管理员报销视图

报销管理员可以：

```text
查看全部
按人查看
按项目查看
按类别查看
按状态查看
按日期查看
```

支持统计：

```text
总金额
待报销金额
已报销金额
项目累计金额
个人累计金额
月份累计金额
年度累计金额
```

---

# 10. 待办系统

不要仅仅把待办理解为一个单独 Checkbox。

V1 可以先实现简单待办。

Todo 字段：

```text
id
user_id
title
description
related_type
related_id
status
due_date
created_at
completed_at
```

可能关联：

```text
Expense
Project
Document
```

例如：

```text
提交高速相机发票
整理项目中期报告
确认 XX 报销到账
上传合同扫描件
```

---

# 11. 搜索系统

搜索是长期档案系统的核心能力之一。

---

## 11.1 V1 搜索

支持搜索：

```text
项目名称
项目编号
文件名称
文件标题
文件描述
报销标题
报销备注
上传人
分类
```

使用 PostgreSQL 基础搜索能力即可。

---

## 11.2 后续全文搜索

V2/V3 增加：

```text
PDF 全文索引
Word 全文索引
OCR 文本
```

未来可以评估：

```text
PostgreSQL Full Text Search
Meilisearch
OpenSearch
Elasticsearch
```

初期禁止过早引入 Elasticsearch。

---

# 12. 文件存储设计

建议数据目录：

```text
/data/labarchive/
```

基本结构：

```text
/data/labarchive/

├── projects/
├── expenses/
├── exports/
├── temp/
├── backups/
└── system/
```

---

## 12.1 项目目录

例如：

```text
projects/
└── <project_uuid>/
    └── documents/
        └── <year>/
```

推荐真实目录主要使用不可变 ID，不要完全依赖中文项目名称。

例如：

```text
projects/
└── 9f92f13e-xxxx-xxxx/
```

项目名称保存在数据库。

---

## 12.2 文件存储名称

不要直接使用用户原始文件名作为物理存储文件名。

推荐：

```text
UUID + 原扩展名
```

例如：

```text
a6938e53-....pdf
```

数据库保存：

```text
original_filename = 高速相机采购合同最终版.pdf
stored_filename = a6938e53-....pdf
```

防止：

- 重名覆盖
- 特殊字符
- 路径注入
- Unicode 问题
- Windows/Linux 文件系统兼容问题

---

# 13. 文件上传安全

上传必须进行基本检查。

至少包括：

```text
最大文件大小
扩展名
客户端声明 MIME 类型
服务端检测真实文件类型
文件名清洗
路径安全
重复文件检测
SHA256
空文件检测
隔离与恶意文件扫描
```

禁止用户上传文件后自行决定服务器绝对路径。

所有路径由服务器生成。

补充要求：

- 扩展名、客户端 MIME 和服务端检测结果明显冲突时，拒绝或隔离文件；
- 未完成安全检查的文件不得进入正常可下载状态；
- 默认不在服务器端自动解压 ZIP，必须限制压缩包大小并防范压缩炸弹；
- HTML、SVG、脚本等可能主动执行的内容不得以内联方式返回；
- 上传失败时清理临时文件，但保留必要且不含敏感内容的失败日志；
- 恶意文件扫描方案和允许格式清单必须在生产部署前确定并完成验证；
- 文件名仅作为显示信息，任何时候都不能参与服务器路径拼接。

---

## 13.1 文件下载安全

上传目录不得作为无需认证的公开静态目录直接暴露。

每次下载必须：

```text
认证用户
↓
查询业务对象
↓
检查项目 / 报销 / 管理员权限
↓
确认文件状态正常
↓
记录下载审计
↓
返回文件
```

开发环境可由 Django 返回文件；生产环境推荐 Django 完成鉴权后，通过 Nginx `X-Accel-Redirect` 等受控机制传输，不能让用户根据真实路径绕过权限。

下载响应默认使用安全的 `Content-Disposition: attachment`，并正确编码中文原始文件名。

---

# 14. 导出与“防软件死亡”设计

项目必须支持完整导出。

例如：

```text
Project_2026_001.zip

├── README.txt
├── project.json
├── index.csv
├── index.xlsx
├── checksums.sha256
├── documents/
├── expenses/
└── attachments/
```

README 至少说明：

```text
项目名称
项目编号
导出时间
数据结构
文件目录说明
```

目标：

即使未来 LabArchive 软件无法运行，管理员仍然可以通过普通文件系统理解和恢复数据。

项目完整导出属于 V1 正式验收范围，不延后到 V2。

导出必须：

- 复用正常页面的权限规则；
- 只包含导出发起人有权访问的数据；
- 记录发起人、条件、时间、结果和文件校验值；
- 对大文件使用临时受控目录，并设置过期清理策略；
- 使用 UTF-8 和公开、可长期读取的格式；
- 通过 `checksums.sha256` 校验包内原始文件；
- 明确导出包是可读副本，不替代系统备份。

---

# 15. 审计日志

AuditLog：

```text
id
user_id
action
object_type
object_id
description
old_value
new_value
ip_address
user_agent
request_id
result
created_at
```

action 示例：

```text
LOGIN
CREATE
UPDATE
DELETE
RESTORE
UPLOAD
DOWNLOAD
STATUS_CHANGE
PERMISSION_CHANGE
EXPORT
```

关键操作必须写日志。

审计日志必须从各业务模块首次实现时同步接入，不能等到 Phase 7 再补录；历史上未记录的操作无法可靠重建。

审计要求：

- `old_value`、`new_value` 使用结构化 JSON，并只记录必要字段；
- 禁止记录密码、Session、Secret、完整认证头等敏感数据；
- 审计记录对业务管理员只读，普通业务操作不得修改或软删除审计日志；
- 用户已离组或删除显示信息后，仍应保留可追溯的操作者 ID 和必要快照；
- 批量操作和后台任务必须记录统一 `request_id` 或任务 ID；
- 日志写入失败时，权限变更、永久删除、导出等高风险操作应安全失败并告警。

---

# 16. 回收站

软删除对象至少包括：

```text
Project
Document
Expense
ExpenseAttachment
```

管理员可以：

```text
恢复
永久删除
```

永久删除必须再次确认。

如果删除真实文件：

应记录：

```text
谁删除
何时删除
原始 SHA256
原始路径
```

永久删除的前置条件必须在 Phase 0 明确，至少考虑：

```text
回收站保留期限
项目或报销是否已归档
文件是否仍被其他记录引用
当前备份是否覆盖该文件
是否存在审计或合规保留要求
```

V1 默认不提供普通用户永久删除能力。管理员永久删除必须二次确认，使用数据库事务更新状态，并通过可重试的后台清理或明确的维护流程删除物理文件，避免出现“数据库已删但文件未删”或相反情况。

---

# 17. Dashboard

登录后 Dashboard 显示：

```text
我的待办
我的待报销
我的项目
最近文件
最近操作
```

管理员额外显示：

```text
待处理报销数量
待报销总金额
近期项目
近期上传
系统存储情况
```

不要在 V1 做过度复杂的数据可视化。

---

# 18. 报表和导出

报销管理员支持导出：

```text
CSV
XLSX
```

可以按照当前筛选条件导出。

例如：

```text
2026 年
项目 A
张三
已报销
```

导出结果应与筛选结果一致。

PDF 报表可作为后续功能。

---

# 19. 数据库初步模型

至少包含：

```text
CustomUser
UserProfile

Django Group
Django Permission

Project
ProjectType
ProjectMembership

FileAsset
Document
DocumentCategory

Expense
ExpenseCategory
ExpenseAttachment
ExpenseStatusHistory

Todo

AuditLog

SystemSetting
```

后续可增加：

```text
DocumentVersion
Tag
DocumentTag
OCRResult
Notification
ExportJob
BackupRecord
```

其中 `ExportJob` 和 `BackupRecord` 如果 V1 采用后台或可追踪任务实现，应在对应阶段提前进入 V1 模型，不受“后续可增加”限制。

数据库约束不能只依赖页面校验。至少评估并测试：

```text
项目编号的唯一性范围
项目成员去重
金额非负与 Decimal 精度
同一文档组当前版本唯一
分类名称在合理范围内唯一
状态字段合法值
外键删除保护策略
软删除对象的条件唯一约束
文件资产路径和 UUID 唯一
```

模型删除策略默认优先使用 `PROTECT` 或显式业务服务处理，禁止因为级联删除配置错误而连带丢失项目、报销、附件或审计记录。

---

# 20. 数据库迁移原则

所有数据库结构变化必须使用：

```text
Django Migration
```

禁止直接手动修改生产数据库结构后不留下 migration。

数据库升级必须可追踪。

---

# 21. 系统配置

以下内容不应硬编码：

```text
项目类别
报销类别
文件类别
系统名称
上传文件大小限制
允许文件格式
部分状态显示
```

通过：

```text
数据库
或
环境变量
```

管理。

密码、Secret Key 等绝对不能提交到 Git。

---

# 22. 配置文件与环境变量

使用：

```text
.env
```

例如：

```text
DATABASE_URL
SECRET_KEY
ALLOWED_HOSTS
MEDIA_ROOT
BACKUP_PATH
MAX_UPLOAD_SIZE
```

仓库中只能提交：

```text
.env.example
```

禁止提交真实：

```text
.env
```

---

# 23. 网络部署策略

当前实验室服务器只能在校园网访问。

第一阶段保持：

```text
校园网
↓
实验室服务器
↓
LabArchive
```

不要主动暴露至公网。

---

## 23.1 校外访问

后续需要远程访问时优先采用：

```text
学校 VPN
WireGuard
Tailscale
```

而不是直接开放数据库或 Django 服务端口到公网。

---

# 24. 服务部署

推荐 Docker Compose：

```text
services:

web
db
nginx
```

未来可增加：

```text
redis
worker
scheduler
search
```

---

## 24.1 PostgreSQL

数据库必须：

- 独立 Volume
- 定期备份
- 禁止公网开放 5432
- 仅内部网络访问

---

## 24.2 Nginx

Nginx 负责：

```text
反向代理
静态文件
上传限制
HTTPS
访问日志
鉴权后的受控文件传输
```

媒体文件真实目录不得配置成可被用户猜测 URL 后直接访问的公开目录。

---

# 25. 备份体系

这是本项目最高优先级功能之一。

原则：

**服务器不是备份。**

---

## 25.1 至少备份

```text
PostgreSQL
+
上传文件
+
必要配置与版本清单
```

代码应由 Git 和发布版本保存。Secret、数据库口令和加密密钥如需进入灾难恢复材料，必须单独加密、限制访问并验证确实可恢复，不能把明文 `.env` 复制到普通备份目录。

---

## 25.2 数据库与文件一致性

数据库备份和附件备份不能仅仅在同一天分别执行后就视为一个可恢复备份集。

每个备份集必须记录：

```text
backup_id
开始与结束时间
应用版本 / Git commit
数据库备份文件及 SHA256
媒体文件清单及 SHA256
备份策略与工具版本
执行结果
验证结果
```

Phase 0 必须确定一种一致性策略，例如：

```text
存储快照
或
短维护窗口内协调 PostgreSQL dump 与媒体同步
或
基于“原始文件不可变”的备份水位与清单机制
```

在一致性方案完成设计和恢复验证前，不能宣称备份体系可用于灾难恢复。

---

## 25.3 推荐频率与保留策略

初期：

```text
每日数据库备份
每日文件增量备份
每周完整备份
```

至少保留：

```text
最近 7 天每日备份
最近 4 周每周备份
最近 12 月每月备份
```

具体策略以后根据磁盘容量调整。

Phase 0 应根据实验室可以接受的数据损失和停机时间，记录：

```text
RPO：最多允许丢失多长时间的数据
RTO：发生故障后希望多长时间恢复服务
```

备份频率由 RPO 决定，恢复工具、服务器准备和演练频率由 RTO 决定，不能只根据磁盘容量决定。

备份任务“进程退出成功”不等于备份有效。至少应检查文件存在、大小合理、校验值正确，并定期执行真实恢复。

---

## 25.4 3-2-1

长期目标：

```text
3 份数据
2 种介质
1 份异地
```

例如：

```text
实验室主服务器
+
NAS
+
异地硬盘 / 第二服务器 / 加密云备份
```

异地备份必须加密，并确保加密密钥不只保存在发生灾难时会一同丢失的主服务器上。

---

# 26. 恢复测试

不能只“做备份”。

必须实现并记录恢复流程。

至少测试：

```text
数据库恢复
附件恢复
数据库+附件联合恢复
```

建议每 3～6 个月人工执行一次恢复演练。

恢复演练必须在隔离测试环境执行，并至少验证：

```text
应用版本与 migration 可用
用户和权限关系正确
项目、报销与附件引用完整
抽样文件 SHA256 一致
完整性检查不存在孤立数据库记录或未知文件
恢复耗时是否满足 RTO
演练记录和失败原因已保存
```

首次生产上线前必须完成一次数据库与附件联合恢复；仅完成备份脚本而未恢复验证，不算 Phase 9 验收通过。

---

# 27. 日志

系统至少包括：

```text
Application Log
Access Log
Error Log
Audit Log
Backup Log
```

生产环境禁止 Debug=True。

---

# 28. 安全要求

至少实现：

```text
CSRF 防护
XSS 防护
SQL 注入防护
文件路径安全
权限验证
Session 安全
密码哈希
上传限制
登录频率限制
```

禁止：

```text
root 用户直接运行应用
数据库 root/superuser 日常连接
开放 PostgreSQL 到公网
代码中保存密码
```

---

# 29. 测试策略

Codex 开发任何核心功能时必须同步增加测试。

至少：

```text
Model Test
Permission Test
Service Test
View/API Test
File Upload Test
Security Test
```

---

## 29.1 必须测试的重要场景

例如：

### 权限

普通成员：

```text
不能查看其他人的私有报销
```

报销管理员：

```text
可以查看所有报销
```

正常登录但未参与项目的用户：

```text
可以查看和下载 INTERNAL 项目文件
不能上传、修改或删除 INTERNAL 项目文件
不能查看 RESTRICTED 项目文件
可以提交 RESTRICTED 项目访问申请
```

还必须测试：

```text
直接访问下载 URL 不能绕过权限
退出或禁用后不能沿用旧会话下载
导出内容不超出发起人的可见范围
管理员后台不能绕过业务规定的关键权限
报销管理员不能因角色访问受限项目档案
项目负责人不能查看其他成员的报销附件
访问申请批准、拒绝、撤销和到期权限正确
```

认证还必须测试：

```text
DISABLED / DEPARTED / ARCHIVED 用户不能登录
首次登录强制修改临时密码
普通用户不能修改自己的角色和账号状态
5 次失败触发 15 分钟限制
错误提示不泄露用户名是否存在
禁用或修改密码后旧 Session 失效
认证审计不包含密码、Cookie 或认证头
```

---

### 文件

测试：

```text
同名文件
中文文件名
超大文件
非法文件名
空文件
重复文件
SHA256
软删除
恢复
扩展名与真实类型不一致
隔离中的文件不可下载
压缩包和主动内容类型安全
物理文件缺失时安全失败并告警
```

---

### 金额

测试：

```text
0
负数
超大值
小数
两位金额精度
```

---

### 报销状态

测试：

```text
合法状态流转
非法跨状态修改被拒绝
提交后普通用户不能修改核心字段
退回原因必填
并发处理不会覆盖较新的状态
每次状态变化产生审计记录
```

---

### 备份与导出

测试：

```text
导出索引与实际文件一致
checksums.sha256 可验证
备份清单与数据库引用一致
全新隔离环境可以联合恢复
恢复后抽样文件 SHA256 一致
```

---

# 30. 前端原则

目标：

```text
简洁
快速
稳定
低学习成本
```

而不是追求复杂动画。

界面必须适配：

```text
1920×1080
笔记本
平板
手机基本查看
```

---

# 31. 页面规划

V1 至少包含：

```text
/login

/dashboard

/projects
/projects/new
/projects/<id>

/projects/<id>/documents
/projects/<id>/members

/documents/<id>

/expenses
/expenses/new
/expenses/<id>

/todos

/search

/admin

/recycle-bin

/profile
```

实际路由由 Codex 根据 Django 最佳实践组织，不要求完全一致。

---

# 32. 项目页面

项目详情页面建议：

```text
项目基本信息

Tabs:

概览
档案
报销
成员
操作记录
```

---

# 33. 报销页面

普通用户默认：

```text
我的报销
```

表格：

```text
标题
项目
类别
金额
日期
状态
附件
```

支持：

```text
新增
编辑
复制
删除
筛选
搜索
```

---

# 34. 文件页面

项目档案页面：

```text
左侧：
分类

右侧：
文件列表
```

支持：

```text
上传
下载
预览
修改元数据
删除
恢复
搜索
```

PDF 和图片可以后期增加浏览器内预览。

---

# 35. 开发阶段

整个开发不得一次性实现所有功能。

采用阶段式开发。

每个可交付任务或 Phase 完成后、提交或交付前，必须更新仓库根目录的 `taskline.md`，写明本次完成内容、验证结果、相关提交或 PR、未完成事项和下一步。不得把后续 Phase 才能执行的联合验收提前标记为完成。

---

## 35.1 Phase 0 必须确认的运行参数

以下内容不能长期以模糊假设进入开发。Phase 0 可以先给出保守默认值，但必须记录在文档或 ADR 中：

```text
项目专属 Conda 环境名称与 Python 版本
Django 与 PostgreSQL 支持版本
实验室生产服务器 OS、CPU、内存与磁盘
MEDIA_ROOT、临时目录和备份目标
预计用户数、项目数、文件总量与增长速度
单文件大小上限和允许文件类型
账号创建、启用、禁用和离组流程
项目文件默认可见范围
报销状态、退回、重新提交和锁定规则
回收站保留期限与永久删除条件
RPO、RTO 和异地备份方式
域名、HTTPS 与校外访问方式
恶意文件扫描方案
```

未确认项必须标记为“待确认”，同时注明当前开发默认值及其风险，不能静默硬编码。

---

# Phase 0：项目初始化

目标：

建立稳定工程基础。

任务：

```text
创建 Git Repository

创建 Django Project

创建自定义 User 并在首次 migration 前配置 AUTH_USER_MODEL

创建核心 Apps 和总体模型骨架

确定 FileAsset、权限、软删除和审计基础接口

配置 PostgreSQL

配置 Docker Compose

配置 .env

配置 Ruff / Formatter

配置 pytest

创建基础 CI

创建 README

创建 docs/ARCHITECTURE.md

创建 docs/DATABASE.md 和初版 ER 图

记录 RPO / RTO 与备份一致性方案

建立 development / production 配置
```

验收：

```text
docker compose up
```

可以启动系统。

数据库连接正常。

测试框架正常。

自定义 User 的首次 migration 可以在空数据库执行。

架构文档、数据库约束和待确认项已完成评审。

不得为了验证启动而提交真实 Secret 或使用系统 Python。

---

# Phase 1：用户与认证

实现：

```text
登录
退出
CustomUser
Django Group / Permission
Profile
账号生命周期
临时密码与首次登录强制改密
个人密码修改
管理员密码重置
登录失败限制
Session 安全策略
预定义角色初始化与分配
登录与权限审计
```

验收：

- 用户可以登录
- 禁用用户无法登录
- 离组和归档用户无法登录
- 首次登录用户必须先修改临时密码
- 用户只能修改允许的个人字段
- 不同系统角色权限不同
- 报销管理员不能因角色访问受限项目档案
- 用户不可访问未授权页面
- 连续登录失败触发限制且不泄露账号是否存在
- 登录、退出、密码和角色操作产生脱敏审计记录

跨阶段验收边界：Phase 1 先验证预定义系统角色本身不会自动授予 `RESTRICTED` 项目访问资格；Project、ProjectMembership 和 ProjectAccessRequest 存在后，在 Phase 2 执行项目级权限决策的联合验收；Document、FileAsset 和鉴权 Download 存在后，在 Phase 3 使用真实文件执行下载边界的联合验收。不能用系统角色测试替代项目级权限测试，也不能用项目级权限测试替代真实文件下载测试。实际开发进度与验证状态见 `taskline.md`，Phase 1 执行证据见 `docs/PHASE1_REPORT.md`。

---

# Phase 2：项目系统

实现：

```text
项目 CRUD
项目成员
项目状态
项目类型
项目可见性
项目权限
项目访问申请
项目关键操作审计
```

验收：

- 所有 `ACTIVE` 状态、正常登录的课题组成员可以查看 `INTERNAL` 项目元数据，并由统一的项目级权限决策认定为具有项目档案内部只读资格；`INTERNAL` 可见性本身不能授予上传、修改、删除、管理分类或管理成员等写权限。
- `RESTRICTED` 项目的完整元数据和项目档案读取资格只允许项目成员、获批申请人和系统管理员获得；未获授权的正常成员只能看到最小目录信息和访问申请入口。
- ProjectMembership 与 ProjectAccessRequest 的创建、查询和状态约束正确，项目级权限决策在页面、服务和后续档案入口之间可以统一复用。
- 访问申请批准后获得 `VIEWER` 成员关系，拒绝、撤销和到期正确生效，且不能降级已有的负责人、管理员或成员授权。
- 系统管理员具有项目级全局访问资格。

跨 Phase 2 → Phase 3 验收边界：

- Phase 2 可以验证用户是否具有项目档案读取资格，以及该资格是否随 `INTERNAL`、`RESTRICTED`、ProjectMembership、访问申请、撤销和到期正确变化。
- 真正的 Document、FileAsset 和鉴权 Download 尚不存在时，不得宣称真实文件下载链路已验收。
- Phase 3 实现 FileAsset、Document 和鉴权 Download 后，必须使用真实文件重新执行 Phase 2 → Phase 3 联合权限验收。
- 联合验收至少覆盖 `INTERNAL`、`RESTRICTED`、`VIEWER`、`SYSTEM_ADMIN`、无权限用户以及直接 URL / IDOR 下载边界。

---

# Phase 3：文件档案系统

实现：

```text
FileAsset
Document
DocumentCategory
Upload
鉴权 Download
SHA256
真实文件类型检测
隔离状态
Soft Delete
Recycle Bin
上传 / 下载 / 删除 / 恢复审计
```

验收：

可以创建项目并上传：

```text
PDF
Word
Excel
图片
ZIP
```

文件能够重新下载并校验 SHA256。

无权限用户无法通过真实路径或直接 URL 下载文件。

被隔离、校验失败或物理缺失的文件安全失败并产生明确日志。

在上述真实文件能力存在后，必须重新执行 Phase 2 → Phase 3 联合权限验收：使用真实 Document、FileAsset 和鉴权 Download，验证 `INTERNAL` 内部只读、`RESTRICTED` 项目成员、获批 `VIEWER`、`SYSTEM_ADMIN`、无权限用户以及直接 URL / IDOR 的下载边界。该联合验收不得削弱本 Phase 的真实文件下载、安全失败、下载审计和 SHA256 要求。

---

# Phase 4：报销系统

实现：

```text
Expense
ExpenseCategory
ExpenseAttachment
Expense Status Workflow
ExpenseStatusHistory
My Expenses
Admin Expenses
关键操作审计
```

验收：

普通用户：

```text
创建
修改
查看
上传附件
```

管理员：

```text
查看全部
筛选
修改状态
```

提交后的编辑锁定、退回原因、重新提交以及非法状态跳转均按规则验证。

---

# Phase 5：待办系统

实现：

```text
Todo
完成
未完成
关联 Expense / Project
```

Dashboard 集成。

---

# Phase 6：搜索

实现全局搜索。

至少覆盖：

```text
Project
Document
Expense
```

支持：

```text
关键词
分类
人员
项目
日期
状态
```

---

# Phase 7：审计管理与完整性复核

实现：

```text
审计日志管理员只读页面
筛选与查询
关键事件覆盖率检查
敏感字段脱敏复核
后台任务 request_id 关联
审计保留和备份策略
```

说明：关键 CRUD、上传、下载、状态和权限日志必须在 Phase 1～6 对应功能首次实现时同步写入，本阶段不能补造历史记录。

---

# Phase 8：统计与 V1 导出

实现：

```text
按人
按项目
按月份
按年度
按类别
报销筛选结果 CSV / XLSX 导出
项目完整可读 ZIP 导出
导出权限与审计
导出包 checksums.sha256
```

报销导出结果必须与筛选条件一致。

项目导出必须包含项目元数据、索引、文档、报销附件和校验清单，并通过无 LabArchive 软件参与的人工可读性检查。

---

# Phase 9：备份体系

实现：

```text
PostgreSQL Backup
Media Backup
一致性备份集
Backup Script
Backup Log
Restore Guide
隔离环境 Restore Test
```

编写：

```text
docs/BACKUP.md
docs/RESTORE.md
```

必须完成一次数据库与附件联合恢复测试，并记录校验结果、恢复耗时和失败原因。

---

# Phase 10：生产部署

部署至实验室服务器。

实现：

```text
Docker Compose Production
Nginx
HTTPS 或经过明确验证的安全访问终止方案
自动启动
日志
备份
监控
```

只允许校园网访问。

生产环境承载账号密码和报销材料，不能因为仅在校园网内就使用明文 HTTP；如 TLS 在其他网关或安全隧道终止，必须记录实际链路和验证结果。

---

# 36. V1 不实现的功能

为了避免 Scope Creep，以下默认不进入 V1：

```text
复杂 AI
自动 OCR
自然语言搜索
移动 App
微信小程序
复杂审批流
电子签名
微服务
Elasticsearch
Kubernetes
消息队列集群
React SPA
Vue SPA
实时协同编辑
```

这些属于 V2+。

---

# 37. V2 规划

V2 可增加：

```text
文件版本管理
标签
高级筛选
更强统计
PDF 在线预览
批量上传
批量下载
定时或批量导出
通知系统
存储容量统计
```

---

# 38. V3 OCR

增加：

```text
扫描件 OCR
PDF OCR
图片 OCR
```

OCRResult：

```text
document_id
text
engine
language
created_at
```

然后纳入全文搜索。

---

# 39. V4 AI 文档识别

上传：

```text
合同扫描.pdf
```

AI 自动识别：

```text
文件类型
合同名称
甲方
乙方
合同金额
签署时间
项目编号
设备名称
```

由用户确认后保存。

禁止 AI 自动覆盖核心业务数据。

---

# 40. V5 AI 搜索

支持：

```text
找一下 2028 年张老师那个高速相机项目的采购合同
```

AI 将自然语言转换成数据库检索条件。

AI 只能访问用户有权限的数据。

---

# 41. 长期可维护性

项目代码必须追求：

```text
简单
明确
可测试
可迁移
低耦合
```

禁止 Codex 为追求“架构高级”而无必要增加：

```text
Repository Pattern 套娃
过多抽象层
复杂 Event Bus
微服务
CQRS
DDD 全家桶
```

只有明确需求才增加复杂度。

---

# 42. 推荐目录结构

参考：

```text
labarchive/

├── manage.py
├── pyproject.toml
├── docker-compose.yml
├── .env.example
├── README.md
│
├── config/
│   ├── settings/
│   ├── urls.py
│   └── wsgi.py
│
├── apps/
│   ├── accounts/
│   ├── projects/
│   ├── documents/
│   ├── expenses/
│   ├── todos/
│   ├── audit/
│   └── core/
│
├── templates/
│
├── static/
│
├── tests/
│
├── scripts/
│   ├── backup/
│   └── maintenance/
│
└── docs/
    ├── ARCHITECTURE.md
    ├── DATABASE.md
    ├── DEPLOYMENT.md
    ├── BACKUP.md
    ├── RESTORE.md
    └── SECURITY.md
```

Codex 可以根据实际情况微调，但不要无理由改变整体模块边界。

---

# 43. Git 规范

主要分支：

```text
main
```

所有功能开发：

```text
feature/xxx
fix/xxx
refactor/xxx
```

提交信息保持清晰。

例如：

```text
feat(expenses): add reimbursement status workflow

fix(documents): prevent unauthorized downloads

test(projects): add project permission tests
```

---

# 44. Codex 工作规则

Codex 在执行本项目时必须遵循以下规则。

---

## 44.1 每阶段先检查再开发

开始任何阶段前：

1. 阅读 README
2. 阅读 docs
3. 检查现有模型
4. 检查 migration
5. 检查测试
6. 检查 Git 状态
7. 再制定本阶段任务

禁止直接大规模重构。

---

## 44.2 小步提交

每完成一个逻辑独立模块：

```text
运行测试
↓
检查格式
↓
提交 Git
```

不要积累几千行修改后一次提交。

---

## 44.3 禁止破坏已有数据

修改模型前：

必须考虑数据库 migration。

禁止：

```text
删除数据库
重新初始化
直接清空数据
```

作为普通问题修复手段。

开发测试环境可以重建，但不得形成生产操作习惯。

---

## 44.4 修改架构需要记录

重要架构决策写入：

```text
docs/ARCHITECTURE.md
```

或者建立：

```text
docs/adr/
```

记录：

```text
为什么这么做
替代方案
未来影响
```

---

## 44.5 不允许静默降低安全性

遇到权限、上传、认证问题时：

禁止为了“让测试通过”直接：

```text
取消权限检查
关闭 CSRF
允许所有文件
关闭认证
```

必须解决根本问题。

---

# 45. Definition of Done

任何功能只有满足以下条件才算完成。

必须：

```text
功能正常
权限正确
测试通过
无明显安全问题
数据库 migration 完整
代码格式检查通过
文档必要时更新
```

如果涉及：

```text
文件
数据库
权限
部署
备份
```

必须有对应测试或者明确的人工验收步骤。

---

# 46. V1 最终验收场景

系统上线前必须完整测试以下真实流程。

---

## 场景 A：普通成员报销

张三：

1. 登录
2. 新建报销
3. 选择项目
4. 选择材料费
5. 输入 3280 元
6. 上传发票 PDF
7. 上传支付截图
8. 提交
9. 查看状态

结果：

报销管理员能够看到。

其他普通成员不能看到。

---

## 场景 B：管理员处理报销

管理员：

1. 登录
2. 查看待报销
3. 按张三筛选
4. 查看附件
5. 修改为报销处理中
6. 最终改为已报销

张三登录后看到状态变化。

---

## 场景 C：项目归档

项目负责人：

1. 创建项目
2. 添加成员
3. 创建“合同”类别
4. 上传合同
5. 填写文档日期
6. 填写备注
7. 下载文件
8. 校验文件完整

十年后理论上仍能：

```text
项目名称
↓
合同
↓
找到文件
```

---

## 场景 D：误删除恢复

成员误删除文件。

管理员：

```text
回收站
↓
找到文件
↓
恢复
```

恢复后：

```text
文件
元数据
项目关联
SHA256
```

均保持正确。

---

## 场景 E：完整备份恢复

模拟主系统损坏。

使用：

```text
数据库备份
+
媒体文件备份
```

部署到新的测试环境。

确认：

```text
用户
项目
报销
文件
附件
权限
审计记录
```

全部恢复，并抽样验证附件 SHA256、数据库引用完整性以及恢复耗时。

这是 V1 正式投入长期使用前的重要验收条件。

---

## 场景 F：脱离软件读取项目导出

管理员或有权的项目负责人：

1. 导出一个包含项目资料、报销和多种附件的完整项目；
2. 在不运行 LabArchive 的独立环境解压；
3. 根据 README、JSON 和表格索引找到指定合同与报销附件；
4. 使用 `checksums.sha256` 验证文件；
5. 确认导出包不包含发起人无权访问的数据。

结果：

```text
数据可理解
文件可直接打开
索引与文件一致
校验通过
权限边界正确
导出操作有审计记录
```

---

# 47. 项目成功标准

V1 达成以下目标即可投入实验室实际使用：

1. 用户可以稳定登录。
2. 普通成员只能访问有权限的数据。
3. 每个人可以管理自己的报销。
4. 报销管理员可以集中管理所有报销。
5. 报销可以按照人、项目、状态和类别查询。
6. 项目可以长期保存文件。
7. 项目文件支持分类和检索。
8. 文件可以安全下载。
9. 删除的数据可以恢复。
10. 系统保存关键操作日志。
11. 数据可以备份。
12. 数据可以恢复。
13. 项目可以导出。
14. 即使软件未来消失，原始文件仍能直接读取。
15. 文件不能通过绕过业务权限的直接 URL 访问。
16. 数据库与附件可以作为一致备份集在隔离环境联合恢复。

---

# 48. Codex 初始执行任务

Codex 收到本计划后，不要立即完成整个系统。

第一步只执行：

```text
Phase 0
+
数据库模型总体设计
+
项目目录骨架
+
开发环境
```

具体要求：

1. 分析本计划书。
2. 将未确认的运行参数、当前默认值和风险整理成清单。
3. 使用本地 Miniconda 新建并验证项目专属环境，禁止使用系统 Python 或其他既有环境。
4. 创建 `docs/ARCHITECTURE.md`，记录权限、文件存储、安全下载、审计和备份一致性方案。
5. 创建 `docs/DATABASE.md`，明确模型、约束、外键删除和软删除策略。
6. 输出初版 ER 数据关系。
7. 建立 Django 项目，并在第一次 migration 前建立自定义 User。
8. 建立 PostgreSQL。
9. 建立 Docker Compose。
10. 建立 pytest。
11. 建立代码格式化和静态检查。
12. 建立基础 Git 仓库规范。
13. 创建核心 Django Apps 和必要的模型骨架。
14. 创建 `.env.example`，确保真实 Secret 不进入 Git。
15. 记录 RPO、RTO、备份目标以及待验证的一致性方案。
16. 暂时不要实现大量业务页面。
17. 运行全部测试、格式检查、静态检查和 migration 检查。
18. 检查项目能从全新环境按 README 启动。
19. 生成 Phase 0 完成报告，逐项列出通过、失败、未验证和原因。

Phase 0 验收通过后，再进入 Phase 1。

---

# 49. 最重要的项目约束

Codex 在整个项目周期中必须始终记住：

> 本系统目标不是做一个演示 Demo，而是建设一个真正可能运行十年以上的实验室长期数据管理系统。

因此优先级顺序为：

```text
数据安全
>
数据完整性
>
权限正确
>
可恢复性
>
长期维护
>
功能完整
>
界面美观
>
技术炫技
```

不得为了快速完成而牺牲：

- 数据安全
- 文件完整性
- 数据迁移能力
- 权限
- 测试
- 备份
- 长期维护性

---

# 50. 最终目标

LabArchive 最终应成为课题组的长期数字基础设施。

未来成员即使不知道系统最初是谁开发的，也应该能够：

```text
登录
↓
找到项目
↓
找到合同
↓
找到报销
↓
找到历史材料
↓
理解数据
↓
导出数据
↓
恢复数据
```

系统应尽量避免成为只有最初开发者才能维护的“个人项目”。

最终追求：

**数据留得住、找得到、看得懂、查得清、恢复得了、十几年以后仍然可用。**
