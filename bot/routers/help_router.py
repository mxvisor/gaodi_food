#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from aiogram import Router, types
from aiogram.filters import Command
from utils.commands import BotCommands, generate_admin_help, generate_user_help
from utils.filters import IsAdmin

help_router = Router(name="help_router")

@help_router.message(BotCommands.ADMIN_HELP.filter, IsAdmin())
async def admin_help_handler(message: types.Message):
    """Показывает справку по командам администратора"""
    await message.answer(generate_admin_help(), parse_mode=None)

@help_router.message(BotCommands.HELP.filter)
async def help_handler(message: types.Message):
    """Show user help information."""
    await message.answer(generate_user_help())