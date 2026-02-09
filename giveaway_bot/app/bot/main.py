import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError
from .config import BOT_TOKEN
from .handlers import router
from ..db import Base, engine
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode


log = logging.getLogger(__name__)

async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is empty. Put BOT_TOKEN into .env or environment variables.")

    Base.metadata.create_all(bind=engine)

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    dp = Dispatcher()
    dp.include_router(router)

    # If webhook was ever set, remove it so polling works everywhere (PC + server)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass

    try:
        await dp.start_polling(
            bot,
            skip_updates=True,
            allowed_updates=dp.resolve_used_update_types(),
            polling_timeout=60,
        )
    except TelegramNetworkError as e:
        # Let the process manager (systemd/pm2/docker) restart it, but keep message clear in logs.
        log.exception("TelegramNetworkError (polling). Check network / proxy / Telegram доступність: %s", e)
        raise
    finally:
        await bot.session.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
