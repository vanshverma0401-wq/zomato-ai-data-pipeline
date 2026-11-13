# Features and model reference

This reference describes the implemented tutorial workflow, recorded live examples and their boundaries. The final four-task run succeeded on November 13, 2026; detailed evidence is listed in the [case-study register](CASE_STUDY.md#verification-register). Start with [FINAL_TESTING.md](../FINAL_TESTING.md) for manual commands.

## 1. Batch warehouse and orchestration

The `zomato_batch` DAG is manually triggered and has no timed schedule. Its final dependency chain is `reload_raw` → `dbt_build_core` → `enrich_reviews` → `dbt_build_ai`. The separate `zomato_local_check` DAG parses the dbt project and discovers tests without running model SQL or data tests against Snowflake.

Core COPY uses the existing private S3 stage without forcing reloads. The dbt core build excludes the AI tag; the final AI build selects it. The release run `release_final_20261113T185136Z` completed all four tasks on attempt 1, with 16 core model successes/16 passing core tests and one AI model success/12 passing AI tests.

## 2. Review sentiment and topic enrichment

The classifier reads nonempty eligible comments from `STAGING.STG_REVIEWS`, ordered by review ID. By default it selects at most five reviews per run that lack an output matching the review ID, full comment hash, model and prompt version. Additional runs can accumulate more classified review IDs.

| Field | Interpretation and validation |
|---|---|
| `sentiment_label` | Exactly one of positive, negative or neutral. |
| `sentiment_score` | Finite value from -1 to 1; not a calibrated probability. |
| `topic` | Exactly one of food quality, delivery, pricing, service, packaging or other. |
| `key_issue` | NULL or a nonempty phrase of at most six words. |
| Model/input provenance | Retained model identifier, full comment SHA-256, prompt version and enrichment timestamp. |

Inference uses a bounded excerpt of at most 2,000 characters under the default configuration. Successful validated classifications are saved to the local cache before warehouse persistence. Local enrichment processes serialize through a file lock, and Snowflake `MERGE` updates/inserts the retained output by review ID. This retains the current result, not a full history of model versions.

`mart_review_insights` joins those results to staged reviews and groups by restaurant city, topic and sentiment label. It reports matched-review counts, mean model score, mean source star rating and the count of non-null issue phrases. It describes the enriched subset rather than all 300,000 recorded reviews.

The release run selected and saved five classifications. Recorded examples include review 1 as positive/packaging with score 0.9, review 2 as negative/pricing with score -0.7, and review 3 as neutral/other with score 0.0. The saved warehouse inspection contains five classification rows and five grouped mart rows. These observed examples do not establish held-out accuracy or population sentiment. Private evidence: `verification/2026-11-13-release/warehouse_examples.json`.

## 3. Retrieval-augmented review answers

The review app is available locally at `http://127.0.0.1:8501/` during an explicitly started session.

1. Opening the page loads local configuration/status and any saved index. It does not call Snowflake or a hosted model.
2. **Build / refresh review index** explicitly reads a deterministic sample, normally at most 100 reviews, with at most one retained row per review ID. The current default excerpt limit is 2,000 characters.
3. Missing embeddings are requested from the hosted `text-embedding-3-small` endpoint in bounded batches. Matching cached vectors are reused using review ID, full text hash, model and excerpt-limit identity.
4. Asking a question embeds that question, ranks the saved vectors with cosine similarity and supplies at most five excerpts to the hosted answer model.
5. The answer must name only retrieved review IDs. Inline square-bracket references must agree with the declared citation list. Insufficient-context results use the explicit insufficient-evidence response.

The app shows retrieved excerpts, city/rating metadata, similarity ranking and cited IDs so a user can inspect the answer. Citation validation checks ID membership and formatting; semantic faithfulness still requires reading the sources. Similarity is not a confidence score. Refresh explicitly to include warehouse changes.

Recorded live checks cover food quality, price/value and an unsupported profitability question. The release owner inspected a food-quality answer citing review IDs 7, 12, 99, 30 and 93; the price/value answer cited review 78; the profitability question returned insufficient evidence. These narrow examples demonstrate the path and one observed abstention, not a general grounding or answer-quality score. The retained [example record](../portfolio/evidence/rag_examples.json) and [gallery](../portfolio/README.md) show the accepted outputs.

## 4. Natural language SQL with separate execution

The warehouse app is available locally at `http://127.0.0.1:8502/` during an explicitly started session.

1. Opening the page checks local credit status only; it performs no warehouse or model request.
2. **Generate SQL** is disabled while live access is blocked. On an allowed click, the app reads current column metadata for the explicit mart whitelist and requests a strict JSON SQL object.
3. A Snowflake-dialect AST and scope validator permits one SELECT/WITH query, resolves physical tables independently from CTE aliases, and rejects unapproved relations, commands, writes, external/table functions, unsupported functions and sequence expressions.
4. The app qualifies physical names to `ZOMATO.MARTS`, applies an outer limit of at most 100 and displays the SQL. It does not run the analytical query automatically.
5. **Run query** revalidates the saved SQL and checks its hash against the question and browser session before opening a connection. It uses a 30-second query timeout and fetches at most 100 rows. Changing the question clears the previous approval and results.

Permitted relations are `FCT_ORDERS`, `DIM_RESTAURANTS`, `DIM_CUSTOMER`, `DIM_FOOD`, `DIM_DATE`, `MART_DAILY_CITY_REVENUNE`, `MART_RESTAURANT_PERFORMANCE`, `MART_DELIVERY_SLA` and `MART_REVIEW_INSIGHTS`. Unsupported questions or SQL must fail rather than expand this list silently.

The existing tutorial `DBT_ROLE` remains broader than a dedicated reader role. These application checks do not establish database-enforced read-only access or universal SQL safety. An already approved query can be run without another model request; it still uses warehouse resources.

The recorded prompt “Top 10 cities by delivered GMV” completed SQL generation, inspection and explicit execution, returning warehouse results. Accepted examples are retained in the [gallery](../portfolio/README.md) with the generated SQL and warehouse results visible. Source columns come from metadata rather than the original tutorial's inaccurate hard-coded schema example.

## 5. Warehouse model inventory

All 17 model descriptions and all 144 output-column descriptions are authored in the existing dbt YAML files. Test definitions and functional SQL are preserved.

| Model | Intended grain / transformation |
|---|---|
| `stg_orders` | Source order ID; restaurant-city extraction and delivered flag, with source amounts/durations retained. |
| `stg_order_items` | Source order-item ID; recorded numeric casts without recalculating line amount. |
| `stg_restaurants` | Retained numeric restaurant ID; selected display-field parsing and restaurant-city extraction. |
| `stg_users` | Retained numeric customer ID; recorded attributes, parsed age/family size and lowercase email. |
| `stg_reviews` | Retained source review ID; non-null comment filter and left-joined restaurant city. |
| `stg_food` | Retained source food row intended to be identified by `f_id`; no deduplication. |
| `stg_menu` | Retained source menu row; valid numeric restaurant ID and positive parsed price. |
| `dim_customer` | Customer ID with fixed tutorial age-band labels. |
| `dim_restaurants` | Restaurant ID and its recorded location/attributes. |
| `dim_food` | Retained staged food row; no added deduplication. |
| `dim_date` | Generated calendar date in the fixed 2024–2026 range. |
| `fct_orders` | Order ID; append-oriented incremental timestamp cutoff. |
| `fact_order_items` | Order-item ID with an inner-joined order; incremental cutoff uses the parent order timestamp. |
| `mart_daily_city_revenune` | Order date/restaurant city; all-order counts and delivered monetary summaries. |
| `mart_delivery_sla` | Restaurant city/order hour among delivered orders; duration p50/p90, not lateness. |
| `mart_restaurant_performance` | Restaurant ID plus joined dimension attributes; averages use all non-null source values across statuses. |
| `mart_review_insights` | Restaurant city/topic/sentiment in the accumulating enriched subset. |

The configured data tests comprise 16 core and 12 AI checks, all of which passed in the final live builds. Offline parsing also discovers all 28, and the separate offline behavioral suite passed 71 tests. Generated dbt documentation exposes the authored descriptions and dependencies; the release owner owns the final catalog generation and screenshot record.

## 6. Credits, runtime and evidence

No local LLM, embedding, reranker or translation weights are downloaded. Inference and embeddings use hosted endpoints; SQLite stores only the bounded local index/cache and shared usage controls.

Live requests require the explicitly confirmed, unexpired promotional-credit state. The shared ledger caps conservative lifetime reservations at $0.10; failed requests retain their reservations. It never selects a paid alternate provider or automatic recharge. The allowance is not an account-level guarantee and does not cover unrelated account use, Snowflake or AWS billing.

Private keys, API credentials and runtime settings remain outside the public source package. Reproduction uses the operator's admitted data, service configuration and verified available credits. The authoritative private run receipts and screenshot state are recorded in the [case-study verification register](CASE_STUDY.md#verification-register); additional demonstration receipts and final captures are consolidated by the release owner.

Tutorial provenance: [video](https://www.youtube.com/watch?v=kYwaNMQ3XT8) and [pinned creator source](https://github.com/darshilparmar/zomato-ai-data-engineering-end-to-end-project/tree/57d147dfe6aaed6bfe7c215d74185c39358790a4). This implementation includes AI coding assistance.
