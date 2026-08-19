#!/bin/bash
# 在同一 Postgres 實例建立 CharacterOS 專用庫，不覆寫 State Vault。
set -euo pipefail

exists="$(psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -tAc "SELECT 1 FROM pg_database WHERE datname = 'characteros'")"
if [ -z "$exists" ]; then
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
        -c "CREATE DATABASE characteros"
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname characteros \
    -f /opt/characteros/schema.sql
