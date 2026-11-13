from datetime import datetime, timezone

from airflow.sdk import DAG
from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator
from airflow.providers.standard.operators.bash import BashOperator

DBT = "/opt/dbt_venv/bin/dbt"
DBT_PROJECT = "/opt/airflow/dbt/zomato"
DBT_PROFILES = "/opt/airflow/dbt_profiles"

COPY_RAW = [
    "USE WAREHOUSE ZOMATO_WH",
    "COPY INTO ZOMATO.RAW.restaurants FROM @ZOMATO.RAW.ZOMATO_RAW_STAGE/restaurants/ ON_ERROR='CONTINUE'",
    "COPY INTO ZOMATO.RAW.users FROM @ZOMATO.RAW.ZOMATO_RAW_STAGE/users/ ON_ERROR='CONTINUE'",
    "COPY INTO ZOMATO.RAW.food FROM @ZOMATO.RAW.ZOMATO_RAW_STAGE/food/ ON_ERROR='CONTINUE'",
    "COPY INTO ZOMATO.RAW.menu FROM @ZOMATO.RAW.ZOMATO_RAW_STAGE/menu/ ON_ERROR='CONTINUE'",
    "COPY INTO ZOMATO.RAW.orders FROM @ZOMATO.RAW.ZOMATO_RAW_STAGE/orders/ ON_ERROR='ABORT_STATEMENT'",
    "COPY INTO ZOMATO.RAW.order_items FROM @ZOMATO.RAW.ZOMATO_RAW_STAGE/order_items/ ON_ERROR='ABORT_STATEMENT'",
    "COPY INTO ZOMATO.RAW.reviews FROM @ZOMATO.RAW.ZOMATO_RAW_STAGE/reviews/ ON_ERROR='ABORT_STATEMENT'",
]

with DAG(
    dag_id="zomato_batch",
    start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=True,
    tags=["zomato", "dbt", "snowflake", "manual"],
) as dag:
    reload_raw = SQLExecuteQueryOperator(
        task_id="reload_raw",
        conn_id="snowflake_default",
        sql=COPY_RAW,
        split_statements=True,
        autocommit=True,
        retries=0,
        show_return_value_in_logs=False,
    )
    dbt_build_core = BashOperator(
        task_id="dbt_build_core",
        bash_command=(
            f"{DBT} build --exclude tag:ai --project-dir {DBT_PROJECT} "
            f"--profiles-dir {DBT_PROFILES}"
        ),
        retries=0,
    )
    enrich_reviews = BashOperator(
        task_id="enrich_reviews",
        bash_command="/opt/ai_venv/bin/python -m ai.enrich_reviews",
        retries=0,
    )
    dbt_build_ai = BashOperator(
        task_id="dbt_build_ai",
        bash_command=(
            f"{DBT} build --select tag:ai --project-dir {DBT_PROJECT} "
            f"--profiles-dir {DBT_PROFILES}"
        ),
        retries=0,
    )
    reload_raw >> dbt_build_core >> enrich_reviews >> dbt_build_ai
