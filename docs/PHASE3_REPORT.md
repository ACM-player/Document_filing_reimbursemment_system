# Phase 3 执行报告

- 执行日期：2026-08-19 至 2026-08-20
- 开发方式：本机 `labarchive` Conda 环境、PostgreSQL 17；不使用 SQLite
- 当前结论：**Phase 3 文件档案系统已完成本地实现与独立验收；分支尚未推送，无 Phase 3 PR 或远端 CI 证据。**

## 1. checkpoint 与实现范围

| Checkpoint | 本地实现与验收结果 |
| --- | --- |
| CP0 | ADR-0006 冻结格式、分类、版本骨架、状态机、可恢复 saga、幂等、权限、下载、回收站与锁序 |
| CP1 | `FileAsset`、`DocumentCategory`、`Document`、数据库约束/触发器、文件权限和审计动作 |
| CP2 | 受控 staging/最终 key、流式大小与 SHA256、真实类型、ZIP/OOXML 安全校验、扫描 adapter |
| CP3 | TEMPORARY 持久化意图、全局 token 幂等、双重锁后鉴权、原子发布、隔离和中断恢复 |
| CP4 | 鉴权下载、安全文件名与响应头、物理异常 fail closed、MISSING 转换及下载审计 |
| CP5 | 权限对称软删除、回收站查询、安全恢复、完整性/类型/扫描/版本冲突复核 |
| CP6 | reconciliation、稳定 task ID、stale TEMPORARY、AVAILABLE/MISSING 修复、orphan 报告、可补偿 staging 清理和真实并发加固 |
| CP7 | 项目档案列表、项目级分类、上传、下载、软删除、回收站、恢复页面及真实多格式/浏览器验收 |

Phase 3 新上传仍固定为独立 document group、`version=1`、`is_current=true`。本阶段没有实现版本替换、
永久物理删除、报销附件或 Phase 4 业务。

## 2. 安全与权限边界

- 媒体目录没有公开 URL；下载必须重新读取当前账号、项目、Document 和 FileAsset 状态；
- 文件名和最终 key 由服务器生成，原始文件名仅用于显示和受控下载文件名；
- 上传不信任客户端 MIME，按二进制签名及 ZIP/OOXML 结构判定 PDF、DOCX、XLSX、PNG、JPEG、ZIP；
- ZIP 拒绝路径穿越、drive/反斜杠路径、链接/特殊文件、加密、重复路径、嵌套 ZIP、CRC 错误和超限结构；
- `SYSTEM_ADMIN` 具有全局项目文件管理权，但 `REIMBURSEMENT_ADMIN` 不自动获得 RESTRICTED 项目访问；
- PI/MANAGER 可管理项目分类和全部项目文件，MEMBER 可上传且只可软删除本人上传，VIEWER/普通 INTERNAL 读者只读；
- ARCHIVED 项目只读，soft-deleted 项目拒绝全部文件访问；非门户账号在 UUID 解析前返回 403；
- 所有页面写入口为 CSRF 保护的 POST；服务在事务锁后再次鉴权，页面过滤不作为安全边界；
- 上传、下载、隔离、缺失、软删除、恢复与 reconciliation 均写 append-only 审计。

## 3. 文件与数据库一致性

PostgreSQL 和文件系统不被伪装成同一 ACID 事务。上传建立持久化 TEMPORARY 意图，文件写入同文件系统
staging，校验后原子发布，再在第二事务复核权限、最终普通文件属性、大小与 SHA256。异常保留为
TEMPORARY、QUARANTINED 或 MISSING，并由显式恢复或 reconciliation 处理。

reconciliation 使用稳定 task UUID，保守处理 stale TEMPORARY、AVAILABLE/MISSING 与过期 staging。
未知最终 orphan 只报告、不自动删除；审计失败时 staging 清理会补偿恢复。production 缺少真实扫描器时，
任务在任何文件状态变更前 fail closed。

## 4. migration 与快照

当前本机开发库已应用 `documents.0001` 与 `audit.0001–0004`。CP7 没有模型变化或新 migration。

应用 `audit.0004` 前的 PostgreSQL custom-format 快照：

```text
.local/backups/pre-phase3-cp6-20260820.dump
SHA-256 19b50cc27a9fde3857d84e7b8f7751af4fef559e4d40a1b7d7284e8a08ee9cdf
```

快照通过 `pg_restore --list` 验证目录可读。该结果不是跨服务器恢复演练，也不替代生产备份验收。

## 5. 自动化验证

CP7 实现后的完整 `scripts/check.zsh` 门禁：

```text
Ruff check                         通过
Ruff format --check                99 个 Python 文件通过
Django system check                0 issues
makemigrations --check --dry-run   No changes detected
pytest                             297 passed in 9.28s
coverage                           88%
```

CP7 定向 PostgreSQL 页面测试为 21 项通过，覆盖：

- PDF、DOCX、XLSX、PNG、JPEG、ZIP 六类真实结构样本的上传、重新下载和 SHA256；
- token 重放、无效文件安全回显、项目级分类和审计；
- INTERNAL、RESTRICTED、PI、MEMBER、VIEWER、SYSTEM_ADMIN、REIMBURSEMENT_ADMIN 与无权限账号；
- 直接 URL / IDOR、归档只读、软删除项目 404、回收站范围与恢复；
- 登录门禁、门户资格先验判断、POST-only 与 CSRF。

CP6 另有 38 项重点 PostgreSQL 测试；其中 7 项真实线程并发连续三轮通过，没有死锁或超时。覆盖同 token
跨项目竞争、上传/恢复与项目归档或账号禁用、删除/归档锁序和并发 reconciliation。

## 6. 真实浏览器验收

浏览器验收运行在 Django `testserver` 创建的隔离 PostgreSQL `test_labarchive` 及 `/private/tmp` 媒体根：

- 登录隔离 SYSTEM_ADMIN，经过项目目录和项目详情进入档案页；
- 实际上传 PDF，页面显示原始文件名、大小、分类、AVAILABLE 状态和受控操作；
- 点击下载产生受控下载事件，服务器返回 200 和准确的 80 字节；
- 390px 移动视口 `bodyScrollWidth == innerWidth`，宽表保留在局部横向滚动容器；
- 恢复 1280px 桌面视口后布局正常；浏览器控制台 warning/error 为 0。

软删除/恢复的浏览器按钮状态由页面可见性确认，最终提交行为由 CSRF 与 PostgreSQL 自动化测试承担，
避免在浏览器安全策略下执行额外删除。验收后已删除 `test_labarchive`、fixture、样本和临时媒体目录；
本机开发库 `labarchive` 保持存在且未写入浏览器验收业务数据。

## 7. 证据边界与后续阶段

- Phase 3 当前结论是**本地验证完成**，不是 CI 验证、PR 评审或已合并；
- 本地与 CI 允许明确记录扫描 `NOT_CONFIGURED`，但绝不记录为 `CLEAN`；正式恶意软件扫描器是上线阻塞项；
- Nginx/X-Accel、服务器目录权限、TLS、监控、Docker/第二套全新环境和备份恢复演练尚未验证；
- 100 MiB 是已实现和自动化覆盖的边界，没有声称完成 100 MiB 文件性能基准；
- 报销、`ExpenseAttachment` 和附件联合权限属于 Phase 4，本次没有开始。

因此 Phase 3 可以在本地范围收口；下一业务阶段只能在新的明确授权下进入。
