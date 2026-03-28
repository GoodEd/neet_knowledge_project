"""Entry point for the NEET PYQ Telegram Bot."""

import logging
import os
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
    logger.info("Initializing NEET PYQ Telegram Bot...")
    from src.telegram_bot.bot import create_application, run_polling

    app = create_application(token)
    run_polling(app)


if __name__ == "__main__":
    main()
