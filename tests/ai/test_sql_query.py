import json
import unittest
from contextlib import contextmanager
from dataclasses import replace

from ai.sql_query import (
    ALLOWED_TABLES,
    QueryValidationError,
    describe_allowed_marts,
    execute_approved_query,
    generate_approved_query,
    validate_sql,
)


SCHEMA_CONTEXT = "\n".join([
    "ZOMATO.MARTS.FCT_ORDERS(ORDER_ID NUMBER, RESTAURANT_ID VARCHAR, CITY TEXT, SALES_AMOUNT NUMBER(38, 0), DELIVERY_TIME_MIN NUMBER, ORDER_STATUS TEXT, ORDER_DATE DATE, IS_DELIVERED BOOLEAN)",
    "ZOMATO.MARTS.DIM_RESTAURANTS(RESTAURANT_ID VARCHAR, RESTAURANT_NAME TEXT, CITY TEXT)",
    "ZOMATO.MARTS.MART_RESTAURANT_PERFORMANCE(RESTAURANT_ID VARCHAR, RESTAURANT_NAME TEXT, REVENUE NUMBER)",
])


class FakeProvider:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def complete(self, system, user, schema=None):
        self.calls.append((system, user, schema))
        return self.response


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
        self.description = [("CITY",), ("GMV",)]
        self.sfqid = "test-query-id"
        self.fetch_size = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None, timeout=None):
        self.calls.append((sql, params, timeout))
        return self

    def fetchmany(self, size):
        self.fetch_size = size
        return self.rows


class FakeConnections:
    def __init__(self, rows):
        self.cursor_instance = FakeCursor(rows)
        self.calls = []

    @contextmanager
    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        yield self

    def cursor(self):
        return self.cursor_instance


class SQLGuardTests(unittest.TestCase):
    def test_aggregate_is_qualified_and_bounded(self):
        result = validate_sql("select city, sum(sales_amount) as amount from fct_orders group by city")
        self.assertIn("ZOMATO.MARTS.FCT_ORDERS", result.sql)
        self.assertTrue(result.sql.endswith("LIMIT 100"))
        self.assertEqual(result.tables, ("FCT_ORDERS",))

    def test_small_limit_is_kept_and_large_limit_is_clamped(self):
        self.assertTrue(validate_sql("SELECT * FROM FCT_ORDERS LIMIT 5").sql.endswith("LIMIT 5"))
        self.assertTrue(validate_sql("SELECT * FROM FCT_ORDERS LIMIT 10000").sql.endswith("LIMIT 100"))

    def test_cte_join_and_union_use_only_resolved_marts(self):
        sql = "WITH a AS (SELECT city FROM fct_orders) SELECT city FROM a UNION ALL SELECT city FROM dim_restaurants"
        result = validate_sql(sql)
        self.assertEqual(result.tables, ("DIM_RESTAURANTS", "FCT_ORDERS"))
        self.assertTrue(result.sql.endswith("LIMIT 100"))

    def test_nested_cte_cannot_disguise_an_outer_physical_table(self):
        sql = "SELECT * FROM secret_table WHERE EXISTS (WITH secret_table AS (SELECT * FROM FCT_ORDERS) SELECT 1 FROM secret_table)"
        with self.assertRaises(QueryValidationError):
            validate_sql(sql)

    def test_other_databases_schemas_and_tables_are_rejected(self):
        for source in ["ZOMATO.RAW.ORDERS", "OTHER.MARTS.FCT_ORDERS", "INFORMATION_SCHEMA.COLUMNS", "MARTS.UNKNOWN", "FACT_ORDER_ITEMS"]:
            with self.subTest(source=source), self.assertRaises(QueryValidationError):
                validate_sql(f"SELECT * FROM {source}")

    def test_writes_commands_multiple_statements_and_select_into_are_rejected(self):
        for sql in [
            "DELETE FROM ZOMATO.MARTS.FCT_ORDERS",
            "SHOW TABLES",
            "CALL MY_PROCEDURE()",
            "SELECT * FROM FCT_ORDERS; DROP TABLE FCT_ORDERS",
            "SELECT * INTO NEW_TABLE FROM FCT_ORDERS",
            "WITH RECURSIVE a AS (SELECT * FROM FCT_ORDERS) SELECT * FROM a",
        ]:
            with self.subTest(sql=sql), self.assertRaises(QueryValidationError):
                validate_sql(sql)

    def test_external_access_functions_and_table_functions_are_rejected(self):
        for sql in [
            "SELECT GET_DDL('TABLE', 'ZOMATO.RAW.ORDERS') FROM FCT_ORDERS",
            "SELECT SYSTEM$GET_PRIVATELINK_CONFIG() FROM FCT_ORDERS",
            "SELECT READ_FILE('secret') FROM FCT_ORDERS",
            "SELECT ZOMATO.MARTS.MY_FUNCTION(city) FROM FCT_ORDERS",
            "SELECT * FROM TABLE(RESULT_SCAN('query-id'))",
            "SELECT * FROM TABLE(GENERATOR(ROWCOUNT => 100))",
            "SELECT * FROM IDENTIFIER('ZOMATO.RAW.ORDERS')",
            "SELECT * FROM @ZOMATO.RAW.ZOMATO_RAW_STAGE",
        ]:
            with self.subTest(sql=sql), self.assertRaises(QueryValidationError):
                validate_sql(sql)

    def test_sequence_expressions_and_select_side_effects_are_rejected(self):
        for sql in [
            "SELECT ZOMATO.MARTS.SOME_SEQUENCE.NEXTVAL FROM FCT_ORDERS",
            "SELECT SOME_SEQUENCE.NEXTVAL FROM FCT_ORDERS",
            'SELECT "ZOMATO"."MARTS"."SOME_SEQUENCE".NEXTVAL FROM FCT_ORDERS',
            "SELECT SOME_SEQUENCE.CURRVAL FROM FCT_ORDERS",
            "SELECT NEXT VALUE FOR SOME_SEQUENCE FROM FCT_ORDERS",
            "SELECT * FROM FCT_ORDERS FOR UPDATE",
        ]:
            with self.subTest(sql=sql), self.assertRaises(QueryValidationError):
                validate_sql(sql)

    def test_comments_are_rejected_but_strings_are_not_substring_filtered(self):
        with self.assertRaises(QueryValidationError):
            validate_sql("SELECT * FROM FCT_ORDERS -- trusted query")
        result = validate_sql("SELECT city FROM FCT_ORDERS WHERE city = 'drop -- keep this text'")
        self.assertIn("drop -- keep this text", result.sql)

    def test_unbounded_or_invalid_limit_expressions_are_rejected(self):
        for suffix in ["LIMIT -1", "LIMIT $limit", "LIMIT 0", "LIMIT 1.5"]:
            with self.subTest(suffix=suffix), self.assertRaises(QueryValidationError):
                validate_sql(f"SELECT * FROM FCT_ORDERS {suffix}")

    def test_reference_mart_typo_and_actual_column_names_are_preserved(self):
        result = validate_sql("SELECT city, gmv, aov FROM ZOMATO.MARTS.MART_DAILY_CITY_REVENUNE")
        self.assertEqual(result.tables, ("MART_DAILY_CITY_REVENUNE",))

    def test_monthly_grouping_and_conditional_rates_are_supported(self):
        queries = [
            "SELECT DATE_TRUNC('month', order_date) AS month, SUM(sales_amount) FROM FCT_ORDERS GROUP BY 1",
            "SELECT payment_method, ROUND(DIV0(COUNT_IF(order_status = 'Cancelled'), COUNT(*)), 4) AS cancel_rate FROM FCT_ORDERS GROUP BY 1",
            "SELECT city FROM FCT_ORDERS WHERE is_delivered AND (sales_amount > 0 OR NOT customer_rating IS NULL)",
        ]
        for sql in queries:
            with self.subTest(sql=sql):
                self.assertEqual(validate_sql(sql).tables, ("FCT_ORDERS",))

    def test_query_without_an_allowed_mart_is_rejected(self):
        with self.assertRaises(QueryValidationError):
            validate_sql("SELECT 1")


class GenerationAndExecutionTests(unittest.TestCase):
    def approval(self):
        provider = FakeProvider(json.dumps({"sql": "SELECT city FROM FCT_ORDERS"}))
        return generate_approved_query("Which cities have orders?", SCHEMA_CONTEXT, provider, "session-a")

    def test_generation_requests_strict_json_and_returns_bound_sql(self):
        provider = FakeProvider(json.dumps({"sql": "SELECT city FROM FCT_ORDERS"}))
        result = generate_approved_query("Which cities have orders?", SCHEMA_CONTEXT, provider, "session-a")
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0][2]["required"], ["sql"])
        self.assertFalse(provider.calls[0][2]["additionalProperties"])
        self.assertEqual(result.question, "Which cities have orders?")
        self.assertEqual(result.session_id, "session-a")

    def test_empty_question_never_calls_the_provider(self):
        provider = FakeProvider('{}')
        with self.assertRaises(QueryValidationError):
            generate_approved_query(" ", "schema", provider, "session-a")
        self.assertEqual(provider.calls, [])

    def test_invalid_or_unsafe_provider_outputs_are_rejected(self):
        for output in ["not json", '{"sql": 5}', '{"sql":"SELECT * FROM FCT_ORDERS","extra":true}', '{"sql":"DELETE FROM FCT_ORDERS"}']:
            with self.subTest(output=output), self.assertRaises(QueryValidationError):
                generate_approved_query("Show orders", SCHEMA_CONTEXT, FakeProvider(output), "session-a")

    def test_invented_ambiguous_or_unavailable_columns_cannot_be_approved(self):
        queries = [
            "SELECT RESTAURANT_NAME FROM FCT_ORDERS",
            "SELECT o.RESTAURANT_NAME FROM FCT_ORDERS o",
            "SELECT CITY FROM FCT_ORDERS o JOIN DIM_RESTAURANTS r ON o.RESTAURANT_ID = r.RESTAURANT_ID",
            "WITH c AS (SELECT CITY FROM FCT_ORDERS) SELECT RESTAURANT_NAME FROM c",
            "SELECT CITY FROM DIM_CUSTOMER",
        ]
        for sql in queries:
            with self.subTest(sql=sql), self.assertRaises(QueryValidationError):
                generate_approved_query("Show restaurant results", SCHEMA_CONTEXT, FakeProvider(json.dumps({"sql": sql})), "session-a")

    def test_real_columns_aggregate_aliases_ctes_and_joins_are_approved(self):
        queries = [
            "SELECT CITY, AVG(DELIVERY_TIME_MIN) AS AVG_MIN FROM FCT_ORDERS GROUP BY CITY ORDER BY AVG_MIN DESC",
            "SELECT CITY, COUNT_IF(ORDER_STATUS = 'Cancelled') / NULLIF(COUNT(*), 0) AS RATE FROM FCT_ORDERS GROUP BY CITY ORDER BY RATE DESC",
            "WITH c AS (SELECT CITY, SUM(SALES_AMOUNT) AS TOTAL FROM FCT_ORDERS GROUP BY CITY) SELECT CITY, TOTAL FROM c ORDER BY TOTAL DESC",
            "SELECT r.RESTAURANT_NAME, SUM(o.SALES_AMOUNT) AS REVENUE FROM FCT_ORDERS o JOIN DIM_RESTAURANTS r ON o.RESTAURANT_ID = r.RESTAURANT_ID GROUP BY r.RESTAURANT_NAME ORDER BY REVENUE DESC",
            "SELECT RESTAURANT_NAME, REVENUE FROM MART_RESTAURANT_PERFORMANCE ORDER BY REVENUE DESC LIMIT 10",
        ]
        for sql in queries:
            with self.subTest(sql=sql):
                approved = generate_approved_query("Show restaurant results", SCHEMA_CONTEXT, FakeProvider(json.dumps({"sql": sql})), "session-a")
                self.assertTrue(approved.sql)

    def test_malformed_or_empty_schema_context_is_rejected_before_provider(self):
        for context in ["", "schema", "FCT_ORDERS(CITY TEXT)", "ZOMATO.RAW.ORDERS(CITY TEXT)", "ZOMATO.MARTS.FCT_ORDERS()"]:
            provider = FakeProvider(json.dumps({"sql": "SELECT CITY FROM FCT_ORDERS"}))
            with self.subTest(context=context), self.assertRaises(QueryValidationError):
                generate_approved_query("Show cities", context, provider, "session-a")
            self.assertEqual(provider.calls, [])

    def test_stale_question_session_or_modified_sql_cannot_open_a_connection(self):
        approved = self.approval()
        cases = [
            (approved, "A different question", "session-a"),
            (approved, approved.question, "session-b"),
            (replace(approved, sql="SELECT * FROM DIM_CUSTOMER LIMIT 100"), approved.question, "session-a"),
        ]
        for query, question, session_id in cases:
            connection_factory = FakeConnections([])
            with self.subTest(question=question, session=session_id), self.assertRaises(QueryValidationError):
                execute_approved_query(query, question, session_id, connection_factory)
            self.assertEqual(connection_factory.calls, [])

    def test_execution_is_timed_and_results_are_bounded(self):
        approved = self.approval()
        connections = FakeConnections([(f"city-{i}", i) for i in range(150)])
        result = execute_approved_query(approved, approved.question, "session-a", connections)
        self.assertEqual(connections.calls, [{"schema": "MARTS", "query_only": True}])
        self.assertEqual(connections.cursor_instance.calls[0][2], 30)
        self.assertEqual(connections.cursor_instance.fetch_size, 100)
        self.assertEqual(len(result.rows), 100)
        self.assertEqual(result.columns, ("CITY", "GMV"))
        self.assertEqual(result.query_id, "test-query-id")

    def test_schema_context_fetch_is_filtered_to_known_marts(self):
        connections = FakeConnections([
            ("DIM_RESTAURANTS", "RATING_COUNT", "NUMBER"),
            ("MART_DELIVERY_SLA", "P90", "NUMBER"),
            ("UNLISTED_TABLE", "SECRET", "TEXT"),
        ])
        context = describe_allowed_marts(connections)
        self.assertIn("DIM_RESTAURANTS(RATING_COUNT NUMBER)", context)
        self.assertIn("MART_DELIVERY_SLA(P90 NUMBER)", context)
        self.assertNotIn("UNLISTED_TABLE", context)
        query, params, timeout = connections.cursor_instance.calls[0]
        self.assertIn("ZOMATO.INFORMATION_SCHEMA.COLUMNS", query)
        self.assertEqual(set(params[1:]), set(ALLOWED_TABLES))
        self.assertEqual(params[0], "MARTS")
        self.assertEqual(timeout, 30)


if __name__ == "__main__":
    unittest.main()
