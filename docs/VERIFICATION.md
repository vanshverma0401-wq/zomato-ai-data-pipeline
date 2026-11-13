# Release verification — November 13, 2026

The accepted final Airflow run was `release_final_20261113T185136Z`, from 18:51:48.664 to 18:52:32.820 UTC. All four tasks succeeded on attempt 1. This was a replay over previously loaded tutorial data; 44 seconds is not a fresh-load benchmark.

| Check | Recorded result |
|---|---|
| `reload_raw` | Successful COPY task over the seven existing source prefixes. No forced reload or purge. |
| `dbt_build_core` | PASS=32: 16 model operations and 16 data tests. |
| `enrich_reviews` | Five selected reviews, five valid responses saved. |
| `dbt_build_ai` | PASS=13: one model operation and 12 data tests. |
| Warehouse facts | 10,000,000 orders and 22,998,179 order items. |
| Documentation | Fresh generated catalog; 17 models, 144 documented columns and eight sources. |
| Working-copy offline tests | 71 passed, including the final SQL column-resolution regressions. |
| Public-copy offline tests | 77 passed: 71 working checks plus six portability checks. |

The SQL app received a later, independent correction after the DAG finished: current schema metadata is parsed and SQLGlot resolves columns before a generated query is approved. Missing/ambiguous columns and missing table metadata now fail closed. The interactive SQL app is separate from the four-task DAG, so this change did not require a second pipeline run.

During manual example review, an average-of-averages query, an incorrect cancellation expression and a query inventing a restaurant-name column were rejected before execution. Prompt guidance now states the order grain, title-case status values and cancellation denominator, and prefers the restaurant performance mart for restaurant sales. These improvements do not guarantee metric correctness: users must inspect generated SQL and filters.

RAG initially returned a citation list without matching inline citations. The application rejected it. A clearer output schema description and formatting example corrected the observed cases; the validator still rejects the missing-inline-citation response. The final gallery retains two cited answers and one insufficient-evidence answer. This is a functional demonstration, not a model-accuracy evaluation.

Publication-safe evidence lives in [portfolio/evidence](../portfolio/evidence/) and the [captioned screenshot gallery](../portfolio/README.md). Full local logs, billing views, account metadata, credentials and authentication evidence are deliberately absent from the public repository.

The public code preserves feature behavior while externalizing private account configuration and promotional expiry. Therefore its configuration seam has separate offline qualification; a fresh clone with the reader's cloud accounts was not live-tested. The private working environment supplied the live demonstration. Source attribution and dataset provenance are recorded in [NOTICE](../NOTICE) and [DATA.md](DATA.md).
