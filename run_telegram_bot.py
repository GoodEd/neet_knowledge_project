"""Entry point for the NEET PYQ Telegram Bot (webhook mode)."""

import os
import logging
from importlib import import_module


def _load_dotenv() -> None:
    try:
        dotenv = import_module("dotenv")
    except ModuleNotFoundError:
        return
    load_fn = getattr(dotenv, "load_dotenv", None)
    if callable(load_fn):
        load_fn()


_load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

    webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL")
    if not webhook_url:
        raise ValueError("TELEGRAM_WEBHOOK_URL environment variable is required")

    port = int(os.getenv("TELEGRAM_WEBHOOK_PORT", "8443"))

    logger.info("Initializing NEET PYQ Telegram Bot (webhook)...")

    from src.telegram_bot.bot import create_application, run_webhook

    app = create_application(token)
    run_webhook(app, webhook_url=webhook_url, port=port)


if __name__ == "__main__":
    main()
