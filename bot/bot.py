#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging

from aiogram import exceptions, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

logging.basicConfig(level=logging.INFO)

# ========== CONFIG ==========
from utils.config import BOT_TOKEN, WEBAPP_URL, BOT_OWNER

# ========== DATABASE IMPORTS ==========
from db.orders_db import load_data, save_data, ensure_initial_admin, get_users
from db.autosave import autosave_loop

# ========== ROUTERS ==========
from routers.user_router import user_router
from routers.admin_router import admin_router
from utils.keyboards import set_webapp_url

# ========== COMMANDS ==========
from utils.commands import setup_bot_commands, setup_admin_commands

# ========== BOT SETUP ==========
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML,
        link_preview_is_disabled=True,  
    ),
)
dp = Dispatcher()

# Include routers
dp.include_router(user_router)
dp.include_router(admin_router)

set_webapp_url(WEBAPP_URL)

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
        except Exception as e:
            logging.exception(f"Неожиданная ошибка: {e}")
            await asyncio.sleep(delay)
    else:
        logging.error("Все попытки подключения к Telegram API исчерпаны. Бот не запущен.")

async def main():
    try:
        # load data into memory
        load_data()
        # ensure initial admin
        ensure_initial_admin(BOT_OWNER)
        # setup bot commands
        await setup_bot_commands(bot)
        # setup admin commands for all existing admins
        for user in get_users():
            if user.is_admin:
                await setup_admin_commands(bot, user.user_id)
        # start autosave loop
        asyncio.create_task(autosave_loop())
        logging.info("Bot starting...")
        await safe_start_polling(dp, bot)
    except KeyboardInterrupt:
        logging.info("Bot stopped by user")
        save_data(force=True)
    except Exception as e:
        logging.exception(f"Unexpected error: {e}")
        save_data(force=True)

if __name__ == "__main__":
    asyncio.run(main())
