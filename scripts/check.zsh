#!/usr/bin/env zsh
set -euo pipefail

project_root="${0:A:h:h}"
cd "$project_root"

source /opt/miniconda3/etc/profile.d/conda.sh
conda activate labarchive
test "$CONDA_DEFAULT_ENV" = "labarchive"

ruff check .
ruff format --check .
python manage.py check
python manage.py makemigrations --check --dry-run
pytest --cov --cov-report=term-missing
