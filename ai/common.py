from __future__ import annotations

import json
import math
import os
import sqlite3
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CREDIT_EXPIRES_AT = datetime(1970, 1, 1, tzinfo=timezone.utc)
LIMIT_MICRO_USD = 100000


class LiveAccessError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default="", repr=False)
    state_path: Path = ROOT / "airflow" / "state"
    sample_n: int = 5
    rag_sample_n: int = 100
    top_k: int = 5
    max_review_chars: int = 2000
    max_question_chars: int = 1000
    chat_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    database: str = "ZOMATO"
    organization_id: str = field(default_factory=lambda: os.environ.get("OPENAI_ORGANIZATION_ID", ""))
    project_id: str = field(default_factory=lambda: os.environ.get("OPENAI_PROJECT_ID", ""))


def _configured_identity():
    organization_id = os.environ.get("OPENAI_ORGANIZATION_ID", "").strip()
    project_id = os.environ.get("OPENAI_PROJECT_ID", "").strip()
    if not organization_id or not project_id:
        raise LiveAccessError("Configure your own OPENAI_ORGANIZATION_ID and OPENAI_PROJECT_ID before enabling live requests.")
    return organization_id, project_id


def _credit_expires_at():
    value = os.environ.get("OPENAI_CREDIT_EXPIRES_AT", "").strip()
    if not value:
        return CREDIT_EXPIRES_AT
    try:
        expires_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise ValueError
        return expires_at.astimezone(timezone.utc)
    except ValueError:
        raise LiveAccessError("OPENAI_CREDIT_EXPIRES_AT must be a verified ISO 8601 timestamp with a timezone.") from None


def load_settings():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env.local", override=False)
    load_dotenv(Path(os.environ.get("ZOMATO_RUNTIME_ENV", str(ROOT / "airflow/runtime.env"))), override=False)
    sample_n = int(os.environ.get("SAMPLE_N", "5"))
    rag_sample_n = int(os.environ.get("RAG_SAMPLE_N", "100"))
    if not 1 <= sample_n <= 20 or not 1 <= rag_sample_n <= 500:
        raise ValueError("Samples must be 1–20 enrichment reviews and 1–500 RAG reviews.")
    return Settings(
        api_key=os.environ.get("OPENAI_API_KEY", ""),
        state_path=Path(os.environ.get("AI_STATE_DIR", str(ROOT / "airflow/state"))),
        sample_n=sample_n,
        rag_sample_n=rag_sample_n,
    )


def state_dir():
    path = load_settings().state_path
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


class BudgetLedger:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "usage.sqlite3"
        with self._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS state (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS reservations (amount INTEGER NOT NULL, created_at TEXT NOT NULL)")

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        os.chmod(self.path, 0o600)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def arm(self, *, free_credit_usd, no_paid_fallback, now=None):
        now = now or datetime.now(timezone.utc)
        expires_at = _credit_expires_at()
        organization_id, project_id = _configured_identity()
        if now >= expires_at:
            raise LiveAccessError("The recorded promotional credit period has expired. Live requests remain blocked.")
        if not no_paid_fallback or not math.isfinite(float(free_credit_usd)) or float(free_credit_usd) < LIMIT_MICRO_USD / 1000000:
            raise LiveAccessError("Confirm at least $0.10 of usable promotional credits and no paid fallback first.")
        receipt = {"confirmed_at": now.isoformat(), "expires_at": min(now + timedelta(hours=24), expires_at).isoformat(), "free_credit_usd": float(free_credit_usd), "no_paid_fallback": True, "organization_id": organization_id, "project_id": project_id}
        with self._connect() as conn:
            conn.execute("INSERT OR REPLACE INTO state VALUES ('credit_confirmation', ?)", (json.dumps(receipt),))

    def _check_access(self, conn, amount, now):
        row = conn.execute("SELECT value FROM state WHERE name='credit_confirmation'").fetchone()
        if row is None:
            raise LiveAccessError("Live AI is locked. Complete the free-credit check in FINAL_TESTING.md first.")
        receipt = json.loads(row[0])
        if now >= _credit_expires_at() or now >= datetime.fromisoformat(receipt["expires_at"]) or not receipt["no_paid_fallback"]:
            raise LiveAccessError("The free-credit confirmation expired. Live requests are blocked.")
        organization_id, project_id = _configured_identity()
        if receipt.get("organization_id") != organization_id or receipt.get("project_id") != project_id:
            raise LiveAccessError("The credit confirmation belongs to a different project.")
        used = conn.execute("SELECT COALESCE(SUM(amount),0) FROM reservations").fetchone()[0]
        if used + amount > LIMIT_MICRO_USD:
            raise LiveAccessError("This tutorial's $0.10 credit-use allowance is exhausted. Requests are blocked.")
        return LIMIT_MICRO_USD - used

    def check_access(self, *, now=None):
        with self._connect() as conn:
            return self._check_access(conn, 1, now or datetime.now(timezone.utc))

    def reserve(self, amount, *, now=None):
        now = now or datetime.now(timezone.utc)
        if not isinstance(amount, int) or amount <= 0:
            raise ValueError("Invalid request reservation.")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._check_access(conn, amount, now)
            conn.execute("INSERT INTO reservations VALUES (?, ?)", (amount, now.isoformat()))

    def status(self):
        with self._connect() as conn:
            used = conn.execute("SELECT COALESCE(SUM(amount),0) FROM reservations").fetchone()[0]
            row = conn.execute("SELECT value FROM state WHERE name='credit_confirmation'").fetchone()
        return {"reserved_micro_usd": used, "limit_micro_usd": LIMIT_MICRO_USD, "credit_confirmation": None if row is None else json.loads(row[0]), "credit_period_expires_at": _credit_expires_at().isoformat()}


def live_access_status(settings=None, *, now=None):
    try:
        settings = settings or load_settings()
        if not settings.api_key.startswith("sk-"):
            raise LiveAccessError("Live AI is locked because the private OpenAI API key is missing.")
        remaining = BudgetLedger(settings.state_path).check_access(now=now)
        return {"allowed": True, "message": f"Live AI is enabled; ${remaining / 1000000:.4f} remains in the shared promotional-credit allowance.", "remaining_micro_usd": remaining}
    except LiveAccessError as error:
        return {"allowed": False, "message": str(error), "remaining_micro_usd": 0}
    except Exception:
        return {"allowed": False, "message": "Live AI is locked because its local credit status could not be checked. Review FINAL_TESTING.md.", "remaining_micro_usd": 0}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Unexpected API redirect.")


def _transport(endpoint, payload, headers):
    if endpoint not in ("chat/completions", "embeddings"):
        raise ValueError("Unsupported API endpoint.")
    request = urllib.request.Request("https://api.openai.com/v1/" + endpoint, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urllib.request.build_opener(NoRedirect).open(request, timeout=45) as response:
        return json.load(response)


class Provider:
    def __init__(self, settings, *, transport=None, now=None):
        self.settings = settings
        self.transport = transport or _transport
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.ledger = BudgetLedger(settings.state_path)

    def _request(self, endpoint, payload, reserve):
        if not self.settings.api_key.startswith("sk-"):
            raise LiveAccessError("The private OpenAI API key is missing.")
        if (self.settings.organization_id, self.settings.project_id) != _configured_identity():
            raise LiveAccessError("The provider settings do not match the configured OpenAI organization and project.")
        self.ledger.reserve(reserve, now=self.now())
        headers = {"Authorization": "Bearer " + self.settings.api_key, "Content-Type": "application/json", "OpenAI-Organization": self.settings.organization_id, "OpenAI-Project": self.settings.project_id}
        try:
            return self.transport(endpoint, payload, headers)
        except Exception:
            raise RuntimeError("OpenAI request failed. No automatic retry or alternate paid provider was used.") from None

    def complete(self, system, user, schema=None):
        if self.settings.chat_model != "gpt-4o-mini":
            raise ValueError("Only the configured tutorial chat model is permitted.")
        payload = {"model": self.settings.chat_model, "temperature": 0, "max_completion_tokens": 700, "store": False, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if schema is not None:
            payload["response_format"] = {"type": "json_schema", "json_schema": {"name": "zomato_result", "strict": True, "schema": schema}}
        byte_count = len(json.dumps(payload, ensure_ascii=False).encode())
        if byte_count > 40000:
            raise ValueError("The request exceeds the tutorial prompt limit.")
        reserve = math.ceil((byte_count + 1024) * 0.15 + 700 * 0.60) + 100
        response = self._request("chat/completions", payload, reserve)
        try:
            choice = response["choices"][0]
            content = choice["message"]["content"]
            if choice["finish_reason"] != "stop" or choice["message"].get("refusal") or not isinstance(content, str):
                raise ValueError
            if schema is not None:
                import jsonschema
                jsonschema.validate(json.loads(content), schema)
            return content
        except Exception:
            raise ValueError("The model response was incomplete or invalid.") from None

    def embed(self, texts):
        if self.settings.embedding_model != "text-embedding-3-small":
            raise ValueError("Only hosted tutorial embeddings are permitted.")
        if not texts or len(texts) > 100 or any(not isinstance(t, str) or not t.strip() or len(t) > 2000 for t in texts):
            raise ValueError("Embedding inputs must contain 1–100 nonempty texts of at most 2000 characters.")
        byte_count = sum(len(t.encode()) for t in texts)
        if byte_count > 200000:
            raise ValueError("The embedding batch is too large.")
        response = self._request("embeddings", {"model": self.settings.embedding_model, "input": texts, "encoding_format": "float"}, math.ceil(byte_count * 0.02) + 100)
        try:
            rows = sorted(response["data"], key=lambda r: r["index"])
            vectors = [r["embedding"] for r in rows]
            if [r["index"] for r in rows] != list(range(len(texts))) or len(vectors) != len(texts):
                raise ValueError
            size = len(vectors[0])
            if not size or any(len(v) != size or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in v) for v in vectors):
                raise ValueError
            return vectors
        except (KeyError, TypeError, IndexError, ValueError):
            raise ValueError("The embedding response was invalid.") from None


def get_provider():
    return Provider(load_settings())


@contextmanager
def get_connection(schema="MARTS", query_only=True):
    load_settings()
    import snowflake.connector
    if schema not in {"AI", "STAGING", "MARTS"}:
        raise ValueError("Unsupported warehouse schema.")
    required = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_SERVICE_LOGIN", "SNOWFLAKE_KEY_PASSPHRASE")
    if any(not os.environ.get(key) for key in required):
        raise RuntimeError("The existing Snowflake service configuration is missing.")
    key_path = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH", str(ROOT / "airflow/secrets/snowflake_airflow_key.p8"))
    connection = None
    try:
        connection = snowflake.connector.connect(account=os.environ["SNOWFLAKE_ACCOUNT"], user=os.environ["SNOWFLAKE_SERVICE_LOGIN"], private_key_file=key_path, private_key_file_pwd=os.environ["SNOWFLAKE_KEY_PASSPHRASE"], authenticator="SNOWFLAKE_JWT", role="DBT_ROLE", warehouse="ZOMATO_WH", database="ZOMATO", schema=schema, login_timeout=20, network_timeout=40, session_parameters={"STATEMENT_TIMEOUT_IN_SECONDS": 30, "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS": 30, "QUERY_TAG": "zomato_ai_query" if query_only else "zomato_ai_enrichment"})
    except Exception:
        raise RuntimeError("Snowflake connection failed. Check the existing service login configuration.") from None
    try:
        yield connection
    finally:
        connection.close()
