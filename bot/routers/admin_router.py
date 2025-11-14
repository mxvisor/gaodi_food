#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from aiogram import Router, types
from aiogram.filters import Command
from utils.commands import BotCommands, generate_admin_help
from utils.filters import IsAdmin

admin_router = Router(name="admin_router")

@admin_router.message(Command(BotCommands.ADMIN_HELP.command), IsAdmin())
async def admin_help_handler(message: types.Message):
    """Показывает справку по командам администратора"""
    await message.answer(generate_admin_help(), parse_mode=None)


