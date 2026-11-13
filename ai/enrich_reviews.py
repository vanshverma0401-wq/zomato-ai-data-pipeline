import argparse
import json


def main(argv=None):
    from ai.common import get_connection, get_provider, load_settings, state_dir
    from ai.enrichment import run_enrichment

    parser = argparse.ArgumentParser(description="Enrich a bounded sample of previously unprocessed reviews.")
    parser.add_argument("--sample-n", type=int)
    args = parser.parse_args(argv)
    settings = load_settings()
    sample_n = settings.sample_n if args.sample_n is None else args.sample_n
    if not 1 <= sample_n <= 20:
        parser.error("--sample-n must be between 1 and 20")
    provider = get_provider()
    with get_connection(schema="AI", query_only=False) as connection:
        result = run_enrichment(
            connection,
            provider,
            sample_n=sample_n,
            model=settings.chat_model,
            cache_dir=state_dir() / "enrichment",
            max_review_chars=settings.max_review_chars,
        )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
