from datetime import datetime, timezone

from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator

DBT = "/opt/dbt_venv/bin/dbt"
COMMON = "--project-dir /opt/airflow/dbt/zomato --profiles-dir /opt/airflow/dbt_profiles"

with DAG(
    dag_id="zomato_local_check",
    start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=True,
    tags=["zomato", "local-readiness", "manual"],
) as dag:
    parse_project = BashOperator(
        task_id="parse_project",
        bash_command=f"{DBT} parse --no-partial-parse {COMMON}",
        retries=0,
    )
    discover_tests = BashOperator(
        task_id="discover_tests",
        bash_command=f"{DBT} --quiet ls --resource-type test --output name {COMMON}",
        retries=0,
    )
    parse_project >> discover_tests
