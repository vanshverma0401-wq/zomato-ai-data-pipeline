import argparse
import json

from ai.common import BudgetLedger, LiveAccessError, live_access_status, load_settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-free-credits", action="store_true")
    parser.add_argument("--free-credit-usd", type=float)
    parser.add_argument("--no-paid-fallback", action="store_true")
    args = parser.parse_args()
    settings = load_settings()
    ledger = BudgetLedger(settings.state_path)
    if args.confirm_free_credits:
        if args.free_credit_usd is None:
            parser.error("Enter the currently verified promotional balance with --free-credit-usd.")
        try:
            ledger.arm(free_credit_usd=args.free_credit_usd, no_paid_fallback=args.no_paid_fallback)
        except LiveAccessError as error:
            parser.error(str(error))
    status = ledger.status()
    status["live_access"] = live_access_status()
    status["api_key_present"] = bool(settings.api_key.startswith("sk-"))
    status["chat_model"] = settings.chat_model
    status["embedding_model"] = settings.embedding_model
    status["sample_n"] = settings.sample_n
    status["rag_sample_n"] = settings.rag_sample_n
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
