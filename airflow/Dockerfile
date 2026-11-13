FROM apache/airflow:3.1.6-python3.12

ENV DBT_BIN=/opt/dbt_venv/bin/dbt \
    PIP_DISABLE_PIP_VERSION_CHECK=1

USER root
RUN python -m venv /opt/dbt_venv \
    && python -m venv /opt/ai_venv \
    && mkdir -p /opt/airflow/ai_state \
    && chown -R airflow:root /opt/dbt_venv /opt/ai_venv /opt/airflow/ai_state \
    && chmod 0770 /opt/airflow/ai_state

USER airflow
COPY --chown=airflow:root airflow/requirements-airflow.txt /tmp/requirements-airflow.txt
COPY --chown=airflow:root airflow/requirements-dbt.txt /tmp/requirements-dbt.txt
COPY --chown=airflow:root airflow/requirements-ai.txt /tmp/requirements-ai.txt

RUN pip install --no-cache-dir \
        --constraint https://raw.githubusercontent.com/apache/airflow/constraints-3.1.6/constraints-3.12.txt \
        --requirement /tmp/requirements-airflow.txt \
    && pip check

RUN PIP_USER=false /opt/dbt_venv/bin/python -m pip install --no-cache-dir \
        --requirement /tmp/requirements-dbt.txt \
    && /opt/dbt_venv/bin/python -m pip check

RUN PIP_USER=false /opt/ai_venv/bin/python -m pip install --no-cache-dir \
        --requirement /tmp/requirements-ai.txt \
    && /opt/ai_venv/bin/python -m pip check

COPY --chown=airflow:root ai/ /opt/airflow/ai/
COPY --chown=airflow:root tests/ai/ /opt/airflow/tests/ai/
