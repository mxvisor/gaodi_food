#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from aiogram.fsm.state import StatesGroup, State
from utils.commands import BotCommands
from utils.keyboards import (
    UserAction,
    BlacklistPageAction,
    make_blacklisted_user_management_keyboard,
    make_blacklist_list_with_menu_keyboard,
)
from utils.filters import IsAdmin
from db import orders_db as db

admin_blacklist_router = Router(name="admin_blacklist_router")

class AdminStates(StatesGroup):
    """Состояние для добавления пользователя в чёрный список."""
    waiting_for_user_id_add_to_blacklist = State()

# ===== blacklist helpers =====

def _build_blacklist_page(page: int) -> tuple[str, types.InlineKeyboardMarkup]:
    bl = db.get_blacklist() or []
    text = f"Чёрный список (стр. {page}):" if bl else "Чёрный список пуст."
    full_kb = make_blacklist_list_with_menu_keyboard(bl, page=page)
    return text, full_kb

@admin_blacklist_router.message(BotCommands.BLACKLIST_MENU.filter, IsAdmin())
async def blacklist_menu_handler(message: types.Message):
    text, kb = _build_blacklist_page(page=1)
    await message.answer(text, reply_markup=kb)

@admin_blacklist_router.callback_query(BlacklistPageAction.filter())
async def paginate_blacklist_callback(callback: types.CallbackQuery, callback_data: BlacklistPageAction):
    if not callback.message:
        await callback.answer()
        return
    text, kb = _build_blacklist_page(page=callback_data.page)
    msg = callback.message
    if isinstance(msg, types.Message):
        current_text = msg.text or ""
        current_kb = msg.reply_markup
        if current_text != text or current_kb != kb:
            await msg.edit_text(text, reply_markup=kb)
    await callback.answer()

# ===== blacklist CRUD =====

@admin_blacklist_router.message(AdminStates.waiting_for_user_id_add_to_blacklist, IsAdmin())
async def process_add_to_blacklist(message: types.Message, state: FSMContext):
    if not message.from_user:
        await state.clear()
        return
    try:
        target = int(message.text.strip() if message.text else "")
    except ValueError:
        await message.answer("Неверный ID пользователя. Введите число:")
        return
    db.reg_set_blacklisted(target, True)
    name = db.get_username(target) or "Без имени"
    await message.answer(f"Пользователь {target} ({name}) добавлен в чёрный список.")
    await state.clear()

@admin_blacklist_router.callback_query(UserAction.filter_action(UserAction.ActionType.ADD_TO_BLACKLIST))
async def add_to_blacklist_callback(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_user_id_add_to_blacklist)
    if callback.message:
        await callback.message.answer("Введите ID пользователя, которого хотите добавить в чёрный список:", parse_mode=None)
    await callback.answer()

@admin_blacklist_router.callback_query(UserAction.filter_action(UserAction.ActionType.SHOW_BLACKLISTED_USER))
async def show_blacklisted_user_callback(callback: types.CallbackQuery, callback_data: UserAction):
    uid = callback_data.target_user_id
    assert uid is not None
    name = db.get_username(uid) or "Без имени"
    kb = make_blacklisted_user_management_keyboard(uid)
    if callback.message:
        await callback.message.answer(f"🚫 {uid}: {name}", reply_markup=kb)
    await callback.answer()

@admin_blacklist_router.callback_query(UserAction.filter_action(UserAction.ActionType.REMOVE_FROM_BLACKLIST))
async def remove_from_blacklist_callback(callback: types.CallbackQuery, callback_data: UserAction, state: FSMContext):
    user_id = callback_data.target_user_id
    assert user_id is not None
    db.reg_set_blacklisted(user_id, False)
    db.reg_reset_attempts(user_id)
    name = db.get_username(user_id) or "Без имени"
    text = f"✅ {user_id} — {name} удалён из чёрного списка"
    msg = callback.message
    if isinstance(msg, types.Message):
        try:
            await msg.edit_text(text, reply_markup=None, parse_mode=None)
        except Exception:
            logging.exception("Failed to edit blacklist removal message")
    await callback.answer()
