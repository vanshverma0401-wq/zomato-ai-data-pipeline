# Public export adaptations

This source export retains the full pipeline, the three AI features and all 71 working offline tests. Six additional tests exercise portable credit configuration. The public-copy suite was run locally with the host test environment and passed all 77 tests without OpenAI, Snowflake or Docker calls. That result qualifies the offline code path only.

The latest active RAG citation prompt/schema, SQL average-grain prompt and five model YAML description changes are included. Those files otherwise retain the reviewed working implementation.

The portability changes are limited to:

- `ai/common.py`: organization and project IDs are reader-provided environment variables; settings read them after dotenv loading. The promotional expiry is reader-provided with timezone validation and defaults to January 1, 1970, so missing configuration blocks live requests. Credit receipts remain bound to the configured organization/project; stale provider identities are blocked before transport. The runtime file and host key defaults are repository-relative rather than tied to the author's private configuration directory. The existing request bounds, rates, lifetime allowance, receipt window and concurrency controls are retained.
- `tests/ai/test_common.py`: explicitly synthetic organization/project IDs and January 2030 dates replace dependencies on the author's private credit configuration. The original test methods and behavior assertions are retained.
- `tests/ai/test_public_config.py`: six tests cover missing/malformed expiry, missing identity, dynamic settings, project-bound receipts and stale provider identity.
- `airflow/airflow.sh`: uses the current Docker CLI environment and `airflow/runtime.env` by default. It does not force a user's daemon socket or Docker configuration directory. `ZOMATO_RUNTIME_ENV` can select another private runtime file.
- `.env.example` and `airflow/runtime.env.example`: empty OpenAI fields and placeholder local service settings. They contain no working credentials or pre-armed receipt.
- `snowflake/01_setup.sql`: removes stale comments about Spark/Iceberg from the retained setup statements. `02_storage_integration.sql` points to the included setup guide. `05_copy_into.sql` removes expected-count commentary so readers measure their own release.
- `snowflake/06_service_user_template.sql`: adds a generic dedicated service-user/public-key setup template and explicit RAW stage/file-format/table grants. It contains no applied key or account-specific value.
- `docs/SETUP.md`, `docs/DATA.md`, `FINAL_TESTING.md`, `.gitignore` and `NOTICE`: portable reproduction, data provenance, exclusions and creator attribution.

The [configuration review diff](PUBLIC_CONFIGURATION.diff) compares the three adapted local files with their working-copy baseline. Private organization/project/credit metadata is replaced with redaction markers on the baseline side. It is a review artifact, not a patch to apply to a private checkout. The complete executable public files contain the actual portable implementation.

The AWS IAM templates and Snowflake scripts originate from Darshil Parmar's pinned tutorial commit `57d147dfe6aaed6bfe7c215d74185c39358790a4`. No root LICENSE or README license declaration was found at that baseline. NOTICE documents provenance without inventing a license or claiming redistribution permission.

Excluded from this export: acquired CSVs, all private environment files, applied authentication SQL, key material, real IAM/account metadata, billing screenshots, runtime caches, logs, dbt targets, verification evidence and virtual environments. The setup scripts are templates to review and fill locally; external cloud resources and data remain reader-provided.
