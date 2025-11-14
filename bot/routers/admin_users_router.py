#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from aiogram.fsm.state import StatesGroup, State
from utils.commands import BotCommands, setup_admin_commands
from utils.keyboards import (
    UserAction,
    UsersPageAction,
    make_user_management_keyboard,
    make_users_list_with_menu_keyboard,
)
from utils.filters import IsAdmin
from db import orders_db as db

admin_users_router = Router(name="admin_users_router")

class AdminStates(StatesGroup):
    """Состояния, относящиеся к управлению пользователями."""
    waiting_for_new_name = State()
    waiting_for_user_id_add_user = State()

# ===== users page helpers =====

def _build_users_page(page: int) -> tuple[str, types.InlineKeyboardMarkup]:
    users = db.get_users() or []
    text = f"Список пользователей (стр. {page}):" if users else "Пользователей пока нет."
    users_sorted = sorted(users, key=lambda u: (not u.is_admin, u.user_id))
    full_kb = make_users_list_with_menu_keyboard(users_sorted, page=page)
    return text, full_kb

@admin_users_router.message(BotCommands.USERS_LIST.filter, IsAdmin())
async def list_users_handler(message: types.Message):
    text, kb = _build_users_page(page=1)
    await message.answer(text, reply_markup=kb)

@admin_users_router.callback_query(UsersPageAction.filter())
async def paginate_users_callback(callback: types.CallbackQuery, callback_data: UsersPageAction):
    if not callback.message:
        await callback.answer()
        return
    text, kb = _build_users_page(page=callback_data.page)
    msg = callback.message
    if isinstance(msg, types.Message):
        current_text = msg.text or ""
        current_kb = msg.reply_markup
        if current_text != text or current_kb != kb:
            await msg.edit_text(text, reply_markup=kb)
    await callback.answer()

# ===== users CRUD =====

@admin_users_router.message(AdminStates.waiting_for_user_id_add_user, IsAdmin())
async def process_add_user(message: types.Message, state: FSMContext):
    if not message.from_user:
        await state.clear()
        return
    try:
        user_id = int(message.text.strip() if message.text else "")
    except ValueError:
        await message.answer("Неверный ID пользователя. Введите число:")
        return
    if not db.user_exists(user_id):
        db.add_user(user_id, "")
    else:
        db.set_username(user_id, "")
    await message.answer(f"Пользователь {user_id} добавлен.", parse_mode=None)
    await state.clear()

@admin_users_router.callback_query(UserAction.filter_action(UserAction.ActionType.ADD_USER))
async def add_user_by_id_callback(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_user_id_add_user)
    if callback.message:
        await callback.message.answer("Введите ID пользователя, которого хотите добавить:", parse_mode=None)
    await callback.answer()

@admin_users_router.callback_query(UserAction.filter_action(UserAction.ActionType.SHOW))
async def show_user_manage_callback(callback: types.CallbackQuery, callback_data: UserAction):
    user_id = callback_data.target_user_id
    assert user_id is not None
    user = db.get_user(user_id)
    if not user:
        await callback.answer("Пользователь не существует", show_alert=True)
        return
    kb = make_user_management_keyboard(user.user_id, user.is_admin)
    status_icon = "⭐" if user.is_admin else "👤"
    name = user.name or "Без имени"
    if callback.message:
        try:
            await callback.message.answer(f"{status_icon} {user.user_id}: {name}", reply_markup=kb)
        except Exception:
            logging.exception("Failed to send user manage keyboard")
    await callback.answer()

@admin_users_router.callback_query(UserAction.filter_action(UserAction.ActionType.ADD_TO_ADMINS))
async def add_user_to_admins_callback(callback: types.CallbackQuery, callback_data: UserAction, state: FSMContext):
    user_id = callback_data.target_user_id
    assert user_id is not None
    db.add_admin(user_id)
    await setup_admin_commands(callback.bot, user_id)
    if callback.message:
        await callback.message.answer(f"Пользователь {user_id} добавлен в админы.")
    await callback.answer()

@admin_users_router.callback_query(UserAction.filter_action(UserAction.ActionType.REMOVE_FROM_ADMINS))
async def remove_user_from_admins_callback(callback: types.CallbackQuery, callback_data: UserAction, state: FSMContext):
    user_id = callback_data.target_user_id
    assert user_id is not None
    if user_id == callback.from_user.id:
        if callback.message:
            await callback.message.answer("Нельзя удалить себя из админов.")
        await callback.answer()
        return
    db.del_admin(user_id)
    if callback.message:
        await callback.message.answer(f"Пользователь {user_id} удалён из админов.")
    await callback.answer()

@admin_users_router.callback_query(UserAction.filter_action(UserAction.ActionType.DELETE))
async def delete_user_callback(callback: types.CallbackQuery, callback_data: UserAction):
    target_user_id = callback_data.target_user_id
    assert target_user_id is not None
    if target_user_id == callback.from_user.id:
        await callback.answer("Нельзя удалить себя", show_alert=True)
        return
    user = db.get_user(target_user_id)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    db.remove_user(target_user_id)
    msg = callback.message
    if isinstance(msg, types.Message):
        try:
            await msg.edit_text(f"🗑️ Пользователь {user.name} (ID: {target_user_id}) удалён")
        except Exception:
            logging.exception("Failed to edit deletion message")
    await callback.answer("Пользователь удалён")

@admin_users_router.callback_query(UserAction.filter_action(UserAction.ActionType.RENAME))
async def rename_user_callback(callback: types.CallbackQuery, callback_data: UserAction, state: FSMContext):
    target_user_id = callback_data.target_user_id
    assert target_user_id is not None
    user = db.get_user(target_user_id)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    await state.update_data(target_user_id=target_user_id, old_name=user.name)
    await state.set_state(AdminStates.waiting_for_new_name)
    if callback.message:
        await callback.message.answer(f"Введите новое имя для пользователя {user.name} (ID: {target_user_id}):", parse_mode=None)
    await callback.answer()

@admin_users_router.message(AdminStates.waiting_for_new_name, IsAdmin())
async def process_new_name(message: types.Message, state: FSMContext):
    new_name = message.text.strip() if message.text else ""
    if not new_name:
        await message.answer("Имя не может быть пустым. Попробуйте ещё раз:")
        return
    data = await state.get_data()
    target_user_id = data.get('target_user_id')
    old_name = data.get('old_name')
    if not target_user_id:
        await state.clear()
        await message.answer("Ошибка: не найден ID пользователя для переименования.")
        return
    db.set_username(target_user_id, new_name)
    await message.answer(f"✅ Пользователь переименован: {old_name} → {new_name} (ID: {target_user_id})", parse_mode=None)
    await state.clear()
