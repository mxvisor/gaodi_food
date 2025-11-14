#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from aiogram.fsm.state import StatesGroup, State
from utils.commands import BotCommands
from utils.keyboards import (
    PasswordAction,
    make_password_management_keyboard,
)
from utils.filters import IsAdmin
from db import orders_db as db

admin_password_router = Router(name="admin_password_router")

class AdminStates(StatesGroup):
    """Состояние для изменения пароля."""
    waiting_for_new_password = State()

@admin_password_router.message(BotCommands.PASSWORD_MENU.filter, IsAdmin())
async def password_menu_handler(message: types.Message):
    """Показывает меню управления паролем для регистрации."""
    pwd = db.get_auth_password()
    text = f"Текущий пароль: `{pwd}`" if pwd else "Пароль не задан."
    await message.answer(text, parse_mode=None, reply_markup=make_password_management_keyboard(has_password=bool(pwd)))

@admin_password_router.callback_query(PasswordAction.filter_action(PasswordAction.ActionType.CHANGE))
async def change_password_callback(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_new_password)
    msg = callback.message
    if isinstance(msg, types.Message):
        await msg.answer("Введите новый пароль для регистрации:", parse_mode=None)
    await callback.answer()

@admin_password_router.callback_query(PasswordAction.filter_action(PasswordAction.ActionType.DELETE))
async def delete_password_callback(callback: types.CallbackQuery):
    db.set_auth_password(None)
    msg = callback.message
    if isinstance(msg, types.Message):
        await msg.edit_text("Пароль удалён. Регистрация будет закрыта до установки пароля.", parse_mode=None)
    await callback.answer()

@admin_password_router.message(AdminStates.waiting_for_new_password, IsAdmin())
async def process_new_password(message: types.Message, state: FSMContext):
    new_password = message.text.strip() if message.text else ""
    if not new_password:
        await message.answer("Пароль не может быть пустым. Попробуйте ещё раз:")
        return
    db.set_auth_password(new_password)
    await message.answer("Пароль установлен.", parse_mode=None)
    await state.clear()
