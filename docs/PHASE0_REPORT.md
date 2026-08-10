# Phase 0 执行报告

- 执行日期：2026-08-10
- 当前结论：**工程基础已建立；本地 Conda + PostgreSQL 路径通过，Docker 路径未验证，因此 Phase 0 尚未最终关闭。**

## 1. 已完成

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| Git 仓库 | 通过 | `main` 分支已初始化；基线提交 `8cd4076`、工程提交 `15ce6dd` |
| 专属环境 | 通过 | Conda 环境 `labarchive`，Python 3.13.14 |
| Django | 通过 | Django 5.2.16，分环境 settings |
| PostgreSQL | 通过 | Conda PostgreSQL 17.10，仅监听 `127.0.0.1:5432` |
| 数据页校验和 | 通过 | `pg_checksums --check`：0 个错误，版本 1 |
| 自定义用户 | 通过 | `accounts.User` 使用 UUID 主键，进入首次 migration |
| 核心 Apps | 通过 | accounts、core、projects、documents、expenses、todos、audit |
| 架构文档 | 通过 | `docs/ARCHITECTURE.md` 与 2 个 ADR |
| 数据库设计 | 通过 | `docs/DATABASE.md` 与初版 Mermaid ER 图 |
| 环境变量 | 通过 | `.env.example` 已提交，`.env` 被 Git 忽略 |
| 质量工具 | 通过 | pytest、pytest-django、coverage、Ruff |
| CI 骨架 | 通过 | PostgreSQL 17 服务、migration、测试与 Ruff 检查 |
| 本机 Web 启动 | 通过 | `127.0.0.1:8000` 首页与 `/health/` 均返回 HTTP 200 |

## 2. 验证结果

### 2.1 环境版本

```text
Python 3.13.14
Django 5.2.16
Psycopg 3.3.4
PostgreSQL 17.10
pytest 9.0.2
pytest-django 4.12.0
Ruff 0.15.22
```

### 2.2 Django 与 migration

```text
python manage.py check
结果：0 issues

python manage.py makemigrations --check --dry-run
结果：No changes detected

python manage.py migrate --noinput
结果：contenttypes、auth、accounts、admin、sessions 全部成功
```

### 2.3 测试

```text
6 passed
coverage: 85%
```

测试覆盖：

- 首页与健康接口；
- 强制 PostgreSQL backend；
- 自定义 UUID User 配置；
- User 在真实 PostgreSQL 测试数据库持久化；
- PostgreSQL 主版本为 17；
- 数据页校验和开启。

### 2.4 HTTP 验证

```text
GET /health/ -> 200
{"service": "labarchive", "status": "ok", "environment": "development"}

GET / -> 200
```

开发服务验证后已停止，PostgreSQL 本地实例保持运行，便于继续开发。

## 3. 未完成或未验证

| 项目 | 状态 | 原因 | 后续处理 |
| --- | --- | --- | --- |
| `docker compose up` | 未验证 | 当前电脑未安装 Docker | 安装 Docker 后单独验证，不影响 Conda 本地开发 |
| CI 远程运行 | 未验证 | 尚未配置 GitHub 远程仓库 | 推送仓库后观察首次 CI |
| 全新 Conda 环境二次重建 | 部分验证 | 当前环境是本次全新创建，但尚未从 `environment.yml` 再建第二套环境 | 依赖升级或交接前执行 |
| 数据库与附件联合恢复 | 未执行 | 当前没有业务文件模型和真实附件 | Phase 9 前完成，服务器部署准入项 |
| 恶意文件扫描 | 未确定 | 属于文件模块与生产安全决策 | Phase 3 设计，生产上线前阻塞 |
| Nginx / HTTPS / Linux | 延后 | 用户决定先本地个人试运行 | 服务器部署阶段验证 |

## 4. 当前默认值

- 本地单文件上限：100 MiB，待样本验证；
- 本地 RPO：暂定 24 小时；
- 本地 RTO：暂定 1 个工作日；
- 本地 PostgreSQL 数据目录：`.local/postgres`；
- 本地媒体目录：`media`；
- 回收站：暂定 90 天，V1 不自动物理删除；
- 用户账号：暂定由管理员创建，不开放公开注册。

这些默认值不是最终业务确认。进入相应 Phase 前必须重新讨论。

## 5. Phase 0 关闭条件

Phase 0 最终关闭前至少还需：

1. 在安装 Docker 的环境运行并验证 `docker compose up`；
2. 记录验证日志和失败原因；
3. ~~确认没有真实 Secret、数据库数据目录或媒体文件进入 Git；~~ 已确认；
4. ~~完成 Git 初始提交并保持工作树可解释。~~ 已完成。

Docker 验证可以延后，但不得把 Phase 0 报告改写成“全部完成”。当前可以继续完善 Phase 0，也可以在明确接受该未验证项后开始 Phase 1 的本地开发。
