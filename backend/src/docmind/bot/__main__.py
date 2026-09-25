"""Run the Telegram bot: ``python -m docmind.bot``."""

from __future__ import annotations

import asyncio
import logging

from docmind.bot.telegram import run_bot
from docmind.config import get_settings


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    asyncio.run(run_bot(settings))


if __name__ == "__main__":
    main()
