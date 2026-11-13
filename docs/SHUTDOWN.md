# Ending a demonstration

Wait until the intended DAG run has finished. Pause both project DAGs, then stop the local services. Keep the persistent volumes so that the AI caches and lifetime reservation ledger survive.

```bash
bash airflow/airflow.sh exec scheduler airflow dags pause zomato_batch
bash airflow/airflow.sh exec scheduler airflow dags pause zomato_local_check
bash airflow/airflow.sh stop
```

If you use a dedicated Docker VM, stop that VM as well. Stop any separately started dbt docs or screenshot-preview HTTP servers. Do not stop unrelated project workloads.

In an authorized Snowflake session, suspend the project warehouse:

```sql
ALTER WAREHOUSE ZOMATO_WH SUSPEND;
SHOW WAREHOUSES LIKE 'ZOMATO_WH';
```

Check that its state is `SUSPENDED`. Inspect project tasks, pipes and other autonomous resources before claiming background work is stopped. A warehouse can auto-resume on a later query, so recheck its state after the last verification query.

Stopping compute does **not** remove Snowflake database storage, Time Travel/Fail-safe storage or S3 objects. An S3 bucket also cannot be “stopped.” Confirm the account's current plan, credits and retained resources. A free trial is not proof of permanently free storage. See the current [Snowflake trial rules](https://docs.snowflake.com/en/user-guide/admin-trial-account) and [AWS plan guidance](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html).

If permanent cloud cleanup is desired, first verify a local data/source backup and obtain explicit approval for the exact database, warehouse and bucket. Deleting live project data is separate from pausing the demonstration. In a versioned S3 bucket, all retained versions and delete markers must be considered, along with incomplete multipart uploads. Follow [AWS empty-bucket guidance](https://docs.aws.amazon.com/AmazonS3/latest/userguide/empty-bucket.html) and [multipart cleanup guidance](https://docs.aws.amazon.com/AmazonS3/latest/userguide/abort-mpu.html).

Do not add payment details, buy credits, upgrade an account or enable automatic recharge to keep this portfolio demo available. Public code and screenshots remain useful after hosted services are stopped. The repository makes no account-wide zero-charge guarantee.

## Recorded release closeout

After the November 13 evidence capture and explicit approval, the project database, project warehouse and dedicated S3 bucket were removed. S3 reported 15 deleted objects and zero failures before successful bucket deletion. Seven local CSV backups, code, screenshots and saved examples remain intact. All local project services and the dedicated VM were stopped; live AI was locked. The public project is an archived demonstration, not a running hosted deployment. See [sanitized closeout record](../portfolio/evidence/closeout.json). Snowflake recovery retention remains provider-managed.
