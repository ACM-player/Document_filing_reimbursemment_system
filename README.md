# LabArchive

课题组科研事务、报销与数字档案管理平台。

当前阶段：**Phase 1 已完成本地实现与验证，准备进入 Phase 2**。仍以本地开发和个人试运行为主，尚未进入实验室服务器部署阶段。

## 技术基线

- Python 3.13（项目专属 Conda 环境：`labarchive`）
- Django 5.2 LTS
- PostgreSQL 17
- Django Templates + HTMX + Tailwind CSS（业务界面阶段接入）
- pytest + pytest-django
- Ruff
- Docker Compose（本地可选；服务器部署前必须验证）

版本选择依据见 [架构文档](docs/ARCHITECTURE.md)。

## 强制环境门禁

任何 Python、Django、测试、格式化或依赖命令执行前，必须先运行：

```zsh
source /opt/miniconda3/etc/profile.d/conda.sh
conda activate labarchive
test "$CONDA_DEFAULT_ENV" = "labarchive"
```

严禁使用系统 Python、`base`、`dev_app`、`playground` 或其他项目环境。

## 本地安装

首次创建环境：

```zsh
conda env create -f environment.yml
```

安装项目与开发依赖：

```zsh
source /opt/miniconda3/etc/profile.d/conda.sh
conda activate labarchive
test "$CONDA_DEFAULT_ENV" = "labarchive"
python -m pip install -e '.[dev]'
```

复制本地配置并替换示例 Secret 和数据库密码：

```zsh
cp .env.example .env
```

`.env` 不得提交到 Git。

## PostgreSQL

开发和测试均使用 PostgreSQL，不提供 SQLite 回退。可选择：

1. 本机安装 PostgreSQL 17；或
2. 安装 Docker 后使用 `compose.yaml` 中的 PostgreSQL。

当前 macOS 本地开发可直接使用专属 Conda 环境中的 PostgreSQL 17：

```zsh
scripts/postgres_local.zsh init
scripts/postgres_local.zsh status
scripts/postgres_local.zsh stop
```

数据保存在 Git 忽略的 `.local/postgres`，服务仅监听 `127.0.0.1:5432`。脚本不会提供自动删除或重置数据库的命令。

此脚本中的 `trust` 初始化方式只适用于当前单用户、本机回环地址的开发实例，不得复制到实验室服务器生产配置。

Docker 本地启动流程：

```zsh
docker compose up -d db
docker compose run --rm web python manage.py migrate
docker compose up web
```

服务仅绑定到 `127.0.0.1`。不要将开发服务暴露到校园网或公网。

## 常用检查

以下命令同样必须在 `labarchive` 环境中执行：

```zsh
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate
pytest
ruff check .
ruff format --check .
```

或统一执行：

```zsh
scripts/check.zsh
```

## 目录

```text
apps/                 Django 业务 Apps
config/               Django 项目与分环境配置
docs/                 架构、数据库、ADR、备份和恢复文档
media/                本地上传目录，仅提交占位文件
scripts/              备份与维护脚本
tests/                跨 App 测试
Line.md               总体需求与开发计划
taskline.md           已完成工作、验证证据、待办和下一步的本地进度记录
compose.yaml          本地 Docker Compose
```

## 当前边界

Phase 1 已实现账号生命周期、预定义系统角色、登录与退出、首次强制改密、个人资料、管理员临时密码重置、登录限制和认证审计。项目、项目成员及 `INTERNAL` / `RESTRICTED` 访问控制属于 Phase 2，当前尚未实现。验证结果见 `docs/PHASE1_REPORT.md`；Phase 0 的历史结果和 Docker 未验证项保留在 `docs/PHASE0_REPORT.md`。
