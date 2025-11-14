#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging

from aiogram import exceptions, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

logging.basicConfig(level=logging.INFO)

# ========== CONFIG ==========
from utils.config import BOT_TOKEN, BOT_OWNER

# ========== DATABASE IMPORTS ==========
import db.orders_db as db
import db.autosave as db_auto

# ========== ROUTERS ==========
from routers.admin_router import admin_router
from routers.admin_users_router import admin_users_router
from routers.admin_blacklist_router import admin_blacklist_router
from routers.admin_password_router import admin_password_router
from routers.admin_orders_router import admin_orders_router
from routers.user_orders_router import user_orders_router
from routers.registration_router import registration_router


# ========== COMMANDS ==========
from utils.commands import setup_bot_commands, setup_admin_commands

# ========== START ==========
async def safe_start_polling(dp, bot, retries=5, delay=10):
    """
    Запускаем polling с обработкой ошибок сети.
    Если сеть недоступна — повторяем попытку `retries` раз с задержкой `delay` секунд.
    """
    attempt = 0
    while attempt < retries:
        try:
            logging.info(f"Polling attempt {attempt+1}/{retries}...")
            await dp.start_polling(bot)
            break  # если polling завершился нормально, выходим
        except exceptions.TelegramNetworkError as e:
            attempt += 1
            logging.warning(f"Network error: {e}. Попытка {attempt}/{retries} через {delay}s")
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            # Propagate cancellation so shutdown can proceed cleanly
            break
        except Exception as e:
            logging.exception(f"Неожиданная ошибка: {e}")
            await asyncio.sleep(delay)
    else:
        logging.error("Все попытки подключения к Telegram API исчерпаны. Бот не запущен.")

async def main():
    try:
        logging.info("Bot preparing...")        
        # load data into memory
        db.load_data()
        # ensure initial admin
        db.ensure_initial_admin()
         # bot setup
        bot = Bot(
            token=BOT_TOKEN,
            default=DefaultBotProperties(
                parse_mode=ParseMode.HTML,
                link_preview_is_disabled=True,  
            ),
        )
        dp = Dispatcher()
        # Include routers
        dp.include_router(admin_router)
        dp.include_router(admin_users_router)
        dp.include_router(admin_blacklist_router)
        dp.include_router(admin_password_router)
        dp.include_router(admin_orders_router)
        dp.include_router(user_orders_router)
        dp.include_router(registration_router)

        # Use bot as async context manager to ensure HTTP session closes on shutdown
        async with bot:
            # setup bot commands
            await setup_bot_commands(bot)
            # setup admin commands for all existing admins
            for user in db.get_users():
                if user.is_admin:
                    await setup_admin_commands(bot, user.user_id)
            # start autosave loop
            asyncio.create_task(db_auto.autosave_loop())
            logging.info("Bot starting...")
            await safe_start_polling(dp, bot)
    except KeyboardInterrupt:
        logging.info("Bot stopped by user")
    except Exception as e:
        logging.exception(f"Unexpected error: {e}")
    finally:
        # Always persist data even on interruptions or errors
        db.save_data(force=True)

if __name__ == "__main__":
    asyncio.run(main())
