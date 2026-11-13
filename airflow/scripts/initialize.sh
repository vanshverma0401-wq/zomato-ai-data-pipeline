#!/bin/bash
set -euo pipefail
airflow db migrate
if ! airflow users list --output json | python -c 'import json, os, sys; sys.exit(0 if any(u.get("username") == os.environ["AIRFLOW_ADMIN_USER"] for u in json.load(sys.stdin)) else 1)'; then
  airflow users create \
    --username "$AIRFLOW_ADMIN_USER" \
    --password "$AIRFLOW_ADMIN_PASSWORD" \
    --firstname Local --lastname Tutorial --role Admin \
    --email airflow@localhost.invalid
fi
