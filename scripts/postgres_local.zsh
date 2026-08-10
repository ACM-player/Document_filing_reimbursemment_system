#!/usr/bin/env zsh
set -euo pipefail

project_root="${0:A:h:h}"
postgres_data_dir="$project_root/.local/postgres"
postgres_log="$project_root/.local/postgres.log"

source /opt/miniconda3/etc/profile.d/conda.sh
conda activate labarchive
test "$CONDA_DEFAULT_ENV" = "labarchive"

ensure_database() {
  if ! psql -h 127.0.0.1 -p 5432 -d postgres -tAc \
    "SELECT 1 FROM pg_roles WHERE rolname = 'labarchive'" | grep -q 1; then
    psql -h 127.0.0.1 -p 5432 -d postgres -v ON_ERROR_STOP=1 \
      -c "CREATE ROLE labarchive LOGIN CREATEDB PASSWORD 'labarchive-local-only'"
  fi

  psql -h 127.0.0.1 -p 5432 -d postgres -v ON_ERROR_STOP=1 \
    -c "ALTER ROLE labarchive CREATEDB" >/dev/null

  if ! psql -h 127.0.0.1 -p 5432 -d postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname = 'labarchive'" | grep -q 1; then
    createdb -h 127.0.0.1 -p 5432 -O labarchive labarchive
  fi
}

case "${1:-status}" in
  init)
    if [[ ! -f "$postgres_data_dir/PG_VERSION" ]]; then
      mkdir -p "$postgres_data_dir"
      initdb \
        -D "$postgres_data_dir" \
        --encoding=UTF8 \
        --locale=C \
        --data-checksums \
        --auth=trust
    fi
    if ! pg_ctl -D "$postgres_data_dir" status >/dev/null 2>&1; then
      pg_ctl \
        -D "$postgres_data_dir" \
        -l "$postgres_log" \
        -o "-h 127.0.0.1 -p 5432" \
        start
    fi
    ensure_database
    ;;
  start)
    if [[ ! -f "$postgres_data_dir/PG_VERSION" ]]; then
      print -u2 "PostgreSQL is not initialized. Run: scripts/postgres_local.zsh init"
      exit 1
    fi
    if ! pg_ctl -D "$postgres_data_dir" status >/dev/null 2>&1; then
      pg_ctl \
        -D "$postgres_data_dir" \
        -l "$postgres_log" \
        -o "-h 127.0.0.1 -p 5432" \
        start
    fi
    ensure_database
    ;;
  stop)
    if pg_ctl -D "$postgres_data_dir" status >/dev/null 2>&1; then
      pg_ctl -D "$postgres_data_dir" stop -m fast
    else
      print "PostgreSQL is not running."
    fi
    ;;
  status)
    pg_ctl -D "$postgres_data_dir" status
    ;;
  *)
    print -u2 "Usage: scripts/postgres_local.zsh {init|start|stop|status}"
    exit 2
    ;;
esac
