#!/bin/bash
set -euo pipefail
task_dir="$(cd "$(dirname "$0")" && pwd)"
runtime_env="${ZOMATO_RUNTIME_ENV:-$task_dir/runtime.env}"
exec docker compose --env-file "$runtime_env" -f "$task_dir/docker-compose.yaml" "$@"
