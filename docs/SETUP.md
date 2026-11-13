# Portable setup and testing

This is a tutorial-derived learning pipeline for the original Zomato-style dataset. The implementation is complete; configuration values and external data belong to the reader. No dataset, credentials, armed credit ledger, or cloud account is distributed here. Read [NOTICE](../NOTICE) for source attribution and the upstream license uncertainty.

The required tools are Docker Engine with Compose v2, a usable AWS account with S3/IAM, and a Snowflake account. OpenAI access is needed only for the three AI demonstrations. Host-side offline tests use Python 3.12 and three small Python dependencies. The AI modules use hosted embeddings; they do not download model weights. The file locks target Linux containers and macOS/Linux hosts.

## Data and cloud setup

Obtain the seven CSVs through the [creator's pinned README](https://github.com/darshilparmar/zomato-ai-data-engineering-end-to-end-project/blob/57d147dfe6aaed6bfe7c215d74185c39358790a4/README.md). See [data acquisition, generated-fact provenance and exact schema notes](DATA.md). Review the dataset terms before redistributing it. This project expects the original tutorial column order, including a leading index column in the four dimension CSVs. Inspect your headers before loading.

Create a private S3 bucket and upload one CSV under each prefix:

| Prefix under the bucket | CSV |
|---|---|
| `raw/restaurants/` | `restaurant.csv` |
| `raw/users/` | `users.csv` |
| `raw/food/` | `food.csv` |
| `raw/menu/` | `menu.csv` |
| `raw/orders/` | `orders.csv` |
| `raw/order_items/` | `order_items.csv` |
| `raw/reviews/` | `reviews.csv` |

Keep all four S3 Block Public Access settings enabled. Snowflake accesses the bucket using a trusted IAM role and external ID.

For a fresh tutorial account, review and run `snowflake/01_setup.sql` as an administrative setup step. It creates `ZOMATO_WH`, `ZOMATO`, the tutorial schemas and `DBT_ROLE`. Its broad tutorial grants are not a production least-privilege policy. Do not run setup SQL blindly in an existing shared account.

Use `aws/iam/s3-read-policy.json` with your bucket name. Create an IAM role initially using `snowflake-role-trust-policy-initial.json` with your AWS account ID. Replace `<ROLE_ARN>` and `<BUCKET>` in `snowflake/02_storage_integration.sql`, then create the integration once. Read its `STORAGE_AWS_IAM_USER_ARN` and `STORAGE_AWS_EXTERNAL_ID` and replace the IAM role trust policy with `snowflake-role-trust-policy-final.json` containing those values. The initial account-root trust is only a bootstrap template. Do not leave it as the final trust policy.

Recreating an existing storage integration can regenerate its external ID and invalidate configured trust. Inspect existing integration metadata rather than rerunning `CREATE OR REPLACE` after configuration.

Set your bucket in `snowflake/03_stage_and_formats.sql` and run it. `LIST` should show your seven prefixes. Then run `04_raw_tables.sql` once for fresh RAW tables and `05_copy_into.sql` to load them. The table script uses `CREATE OR REPLACE`; rerunning it over loaded tables discards those tables. The loader follows the creator's policy: skip malformed dimension rows with `CONTINUE`, and abort malformed generated-fact loads. Inspect COPY results and your own counts; a completed statement does not mean no dimension rows were skipped. No `FORCE` reload or `PURGE` is required.

## Private local configuration

From the repository root, create private copies of the templates:

```bash
cp .env.example .env.local
cp airflow/runtime.env.example airflow/runtime.env
mkdir -p airflow/secrets
chmod 700 airflow/secrets
chmod 600 .env.local airflow/runtime.env
```

Edit the copied files locally. `.env.local` supplies your OpenAI key, organization ID, project ID and verified promotional-credit expiry. Leave AI fields blank to run only the offline tests and core pipeline. `OPENAI_CREDIT_EXPIRES_AT` must be the actual expiry from your billing page, as an ISO 8601 timestamp with a timezone, such as the format `YYYY-MM-DDTHH:MM:SS+00:00`. Missing expiry defaults to an already expired date and blocks live requests. Changing an expiry setting does not renew promotional credits.

`airflow/runtime.env` supplies local Airflow/Postgres secrets and Snowflake service settings. Generate unique values for each local password and signing secret. A Fernet key can be generated with:

```bash
python3 -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Generate other random secrets separately with `openssl rand -hex 32`. Put the generated values only into the private runtime file. On Linux, set `AIRFLOW_UID` to your host UID from `id -u`; keep the Compose group ID at `0`. The example uses the image's default UID `50000`.

Generate an encrypted RSA private key and its public key:

```bash
openssl genpkey -algorithm RSA -aes-256-cbc -pkeyopt rsa_keygen_bits:2048 -out airflow/secrets/snowflake_airflow_key.p8
openssl pkey -in airflow/secrets/snowflake_airflow_key.p8 -pubout -out airflow/secrets/snowflake_airflow_key.pub
chmod 600 airflow/secrets/snowflake_airflow_key.p8
```

Store the passphrase in the private `SNOWFLAKE_KEY_PASSPHRASE` setting. Review `snowflake/06_service_user_template.sql`, replace its public-key placeholder with the public PEM body without the delimiter lines, then run it through your authorized administrative session. Use a dedicated new service user with only the intended role grants; do not attach the workload key to your administrative human user. The template uses the established RSA user property; its key has no intrinsic expiry, so manage rotation explicitly. The tutorial `DBT_ROLE` remains broad: the SQL app adds application validation, not a database-enforced read-only role.

The example `ZOMATO_AIRFLOW_SECRET_DIR=./secrets` is resolved relative to the Compose directory. The private key is mounted read-only at `/run/secrets/snowflake_airflow_key.p8`. All source templates remain unchanged in version control; do not save your filled account identifiers, trust policy or public-key assignment into the repository.

## Offline tests

From the repository root:

```bash
python3.12 -m venv .venv-ai
.venv-ai/bin/python -m pip install python-dotenv==1.2.4 jsonschema==4.26.0 sqlglot==30.31.0
.venv-ai/bin/python -m unittest discover -s tests/ai -v
```

Dependency installation accesses the Python package registry. The tests themselves use temporary state, synthetic identities and fake external boundaries. They make no Snowflake or OpenAI requests and do not arm live credit access. The exported suite contains the original 71 tests plus six portability checks.

## Build and start the stack

Choose your Docker context before running the wrapper. It uses your current Docker CLI environment and does not force Docker Desktop, Colima, a daemon socket or a private Docker configuration directory. If your engine runs inside a VM, make sure the `airflow`, `zomato` and configured secrets directories are shared with that VM. The AI source and tests are built into the image, so they need no additional bind mounts.

```bash
bash airflow/airflow.sh config --quiet
bash airflow/airflow.sh build
bash airflow/airflow.sh up -d --no-build
bash airflow/airflow.sh ps
bash airflow/airflow.sh exec scheduler airflow dags list-import-errors
bash airflow/airflow.sh exec rag-app /opt/ai_venv/bin/python -m unittest discover -s /opt/airflow/tests/ai -v
bash airflow/airflow.sh exec scheduler /opt/dbt_venv/bin/dbt parse --no-partial-parse --project-dir /opt/airflow/dbt/zomato --profiles-dir /opt/airflow/dbt_profiles
bash airflow/airflow.sh exec rag-app /opt/ai_venv/bin/python -m ai.preflight
```

Initialization exits after migration and admin creation. The API server, scheduler, DAG processor and two Streamlit apps stay running. Rebuild after changing AI source or tests. The root `.dockerignore` excludes private configuration and data from the build context. Avoid printing `docker compose config` without `--quiet`, because rendered configuration can contain credentials.

## Live-credit gate and manual run

First check current AWS and Snowflake balances and terms. Their free resources and trial credits are separate from OpenAI. Do not enable a paid upgrade to complete this demonstration.

For live AI, verify your selected OpenAI organization/project has usable promotional credit, a known expiry and enough remaining credit to cover the entire bounded allowance. Keep automatic recharge off and do not buy credits or upgrade. This project cannot verify those billing conditions or disable account-level paid fallback for you. If you cannot establish that the demonstration stays within usable promotional credit, keep live access locked. The configured chat model is `gpt-4o-mini`; its model page marks it deprecated, so confirm availability for your own account. There is no automatic substitution or retry. If you have no eligible usable promotional credit, leave AI locked and use the offline tests.

Set the variable below to the current balance you actually verified. Its default `0.00` intentionally cannot arm live access:

```bash
verified_promo_usd=0.00
bash airflow/airflow.sh exec rag-app /opt/ai_venv/bin/python -m ai.preflight --confirm-free-credits --free-credit-usd "$verified_promo_usd" --no-paid-fallback
```

Read `live_access.allowed` in the output. Stop if it is false. Confirm inside a container so the receipt is written to the same named `ai_state` volume as the DAG and apps. Confirmation lasts at most 24 hours and never past your configured actual expiry. Reservations share a lifetime cap of $0.10 of promotional-credit use, persist across restarts and re-arming, and remain reserved on failure. This is a conservative application allowance, not an account-level billing guarantee or evidence that any API account is free.

After confirming the gate, inspect the loaded four tasks and trigger one run:

```bash
bash airflow/airflow.sh exec scheduler airflow tasks list zomato_batch
bash airflow/airflow.sh exec scheduler airflow dags unpause zomato_batch
bash airflow/airflow.sh exec scheduler airflow dags trigger zomato_batch
bash airflow/airflow.sh exec scheduler airflow dags list-runs zomato_batch
```

The graph should contain `reload_raw`, `dbt_build_core`, `enrich_reviews`, and `dbt_build_ai`. Inspect its outcomes at http://127.0.0.1:8080 using the admin login from your runtime file. The core build contains 16 models; the AI lane creates validated enrichment and the review-insights mart. Both DAGs have `schedule=None`. After the intended run reaches a terminal state and its tasks have completed, pause it:

```bash
bash airflow/airflow.sh exec scheduler airflow dags pause zomato_batch
```

## App demonstrations

Open http://127.0.0.1:8501 for review RAG. Page load makes no model or warehouse request. Explicitly build the bounded deterministic index, ask a review question, and compare the generated `[review_id]` citations with the retrieved excerpts. Refreshing unchanged reviews reuses embeddings. Concurrent refreshes are locked; the last complete index stays readable. Citation checks establish IDs and formatting, not semantic faithfulness or customer-wide prevalence.

Open http://127.0.0.1:8502 for natural-language SQL. Generate a query first, review it, then choose its separate execution action. Editing the question invalidates the previous approval. Only whitelisted marts/functions and a bounded read query are accepted. The application uses the existing tutorial role and a query timeout; it does not claim the database account is read-only.

Successful enrichment responses and embeddings are cached in `ai_state`. Keep the named volumes to preserve caches and the shared allowance. Stop services with `bash airflow/airflow.sh stop`; this guide provides no volume-reset command.
