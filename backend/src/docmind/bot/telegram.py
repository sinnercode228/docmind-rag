"""aiogram 3 adapter: thin glue between Telegram updates and ``BotService``."""

from __future__ import annotations

import contextlib
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from docmind.bot.client import DocMindClient
from docmind.bot.service import BotService
from docmind.config import Settings

log = logging.getLogger(__name__)

WELCOME = (
    "<b>DocMind</b> — ask questions about your team's documents.\n"
    "Задавайте вопросы по документам вашей команды.\n\n"
    "/new — start a new conversation / новый диалог\n"
    "/help — help / помощь\n\n"
    "<i>Demo project / Демо-проект</i>"
)


def build_router(service: BotService, allowed_chats: set[int] | None = None) -> Router:
    router = Router(name="docmind")

    def allowed(message: Message) -> bool:
        return not allowed_chats or message.chat.id in allowed_chats

    @router.message(CommandStart())
    @router.message(Command("help"))
    async def on_start(message: Message) -> None:
        await message.answer(WELCOME)

    @router.message(Command("new"))
    async def on_new(message: Message) -> None:
        service.reset(message.chat.id)
        await message.answer("New conversation started. / Новый диалог начат.")

    @router.message(F.text & ~F.text.startswith("/"))
    async def on_question(message: Message, bot: Bot) -> None:
        if not allowed(message):
            await message.answer("This bot is private. / Это приватный бот.")
            return
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        placeholder = await message.answer("…")

        async def progress(text: str) -> None:
            with contextlib.suppress(TelegramBadRequest):
                await placeholder.edit_text(text, parse_mode=None)

        reply = await service.answer(message.chat.id, message.text or "", progress)
        try:
            await placeholder.edit_text(reply)
        except TelegramBadRequest:  # malformed HTML from the model: fall back to plain text
            await placeholder.edit_text(reply, parse_mode=None)

    return router


async def run_bot(settings: Settings) -> None:
    if not settings.telegram_bot_token or not settings.telegram_api_key:
        raise SystemExit("Set DOCMIND_TELEGRAM_BOT_TOKEN and DOCMIND_TELEGRAM_API_KEY")
    client = DocMindClient(settings.telegram_api_url, settings.telegram_api_key.get_secret_value())
    service = BotService(client)
    bot = Bot(
        settings.telegram_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    allowed = set(settings.telegram_allowed_chat_ids) or None
    dispatcher.include_router(build_router(service, allowed))
    log.info("DocMind Telegram bot started (API: %s)", settings.telegram_api_url)
    try:
        await dispatcher.start_polling(bot)
    finally:
        await client.aclose()
        await bot.session.close()
