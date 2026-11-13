import uuid

import pandas as pd
import streamlit as st

from ai.common import LiveAccessError, get_connection, get_provider, live_access_status
from ai.sql_query import (
    QueryValidationError,
    describe_allowed_marts,
    execute_approved_query,
    generate_approved_query,
)


def render_page():
    st.title("Ask your Zomato warehouse")
    st.caption("Generate SQL, review it, then choose Run query. Results are limited to 100 rows and 30 seconds.")
    status = live_access_status()
    if status["allowed"]:
        st.caption(status["message"])
    else:
        st.warning(status["message"])
    with st.sidebar:
        st.subheader("Example questions")
        for example in [
            "Top 10 cities by delivered GMV",
            "Average delivery time by city",
            "Cancellation rate by payment method",
            "Top 10 restaurants by delivered sales amount",
        ]:
            st.write(example)
    if "sql_session_id" not in st.session_state:
        st.session_state.sql_session_id = uuid.uuid4().hex
    question = st.text_input("Your question", key="sql_question", max_chars=2000)
    approved = st.session_state.get("sql_approval")
    if approved is not None and approved.question != question.strip():
        st.session_state.pop("sql_approval", None)
        st.session_state.pop("sql_result", None)
        approved = None
    if st.button("Generate SQL", disabled=len(question.strip()) < 3 or not status["allowed"]):
        st.session_state.pop("sql_approval", None)
        st.session_state.pop("sql_result", None)
        approved = None
        try:
            status = live_access_status()
            if not status["allowed"]:
                raise LiveAccessError(status["message"])
            with st.spinner("Reading the available mart schema and generating SQL"):
                context = describe_allowed_marts(get_connection)
                approved = generate_approved_query(question, context, get_provider(), st.session_state.sql_session_id)
            st.session_state.sql_approval = approved
        except QueryValidationError as error:
            st.error(str(error))
        except LiveAccessError as error:
            st.error(str(error))
        except Exception as error:
            st.error(f"SQL generation failed ({type(error).__name__}). Check the provider and warehouse configuration.")
    if approved is not None:
        st.code(approved.sql, language="sql")
        st.caption("Relations: " + ", ".join(approved.tables))
    if st.button("Run query", disabled=approved is None):
        st.session_state.pop("sql_result", None)
        try:
            with st.spinner("Running the approved query"):
                result = execute_approved_query(approved, question, st.session_state.sql_session_id, get_connection)
            st.session_state.sql_result = result
        except QueryValidationError as error:
            st.error(str(error))
        except Exception as error:
            st.error(f"Query execution failed ({type(error).__name__}). Check access, syntax and warehouse availability.")
    result = st.session_state.get("sql_result")
    if result is not None:
        frame = pd.DataFrame(result.rows, columns=result.columns)
        st.success(f"{len(frame)} rows returned")
        st.dataframe(frame, hide_index=True)
        if result.query_id:
            st.caption("Snowflake query ID: " + result.query_id)
        if len(frame.columns) == 2 and pd.api.types.is_numeric_dtype(frame.iloc[:, 1]) and st.checkbox("Show a bar chart"):
            st.bar_chart(frame, x=frame.columns[0], y=frame.columns[1])


if __name__ == "__main__":
    render_page()
