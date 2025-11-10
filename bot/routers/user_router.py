#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
from typing import Optional

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from utils.commands import BotCommands, generate_user_help
from utils.keyboards import get_main_keyboard_for, make_order_keyboard, set_webapp_url, OrderAction, OrderTypeAction, make_order_type_selection_keyboard
from utils.filters import RequireCollecting
from db.orders_db import UserOrder, User
from db import orders_db as db

# Import from main bot file (will be set by bot.py)
# Bot instance no longer needed - using message.bot and callback.bot instead

user_router = Router(name="user_router")

# Dictionary to store last total message ID for each chat
last_total_message_ids = {}

# ========== FSM ==========
class UserRegistration(StatesGroup):
    waiting_for_name = State()
    waiting_for_password = State()

# ========== Keyboards ==========
# (moved to keyboards.py)

# ========== ORDER HELPERS ==========
def make_order_text(order: UserOrder, is_current: bool) -> str:
    name = db.get_username(order.user_id) or str(order.user_id)
    status = "✅ Выполнен" if order.done else ("⏳ Текущий" if is_current else "📦 Прошлый")
    # Получаем данные товара из каталога
    product = db.get_product(order.product_id)
    title = product.title if product else f"Товар #{order.product_id}"
    price = product.price if product else 0
    link = product.link if product else ""
    text = (
        f"<b>{name}</b>\n"
        f"{title} - <b>{price} ₽</b>\n"
        f"Количество: <b>{order.count}</b>\n"
        f"Ссылка: {link}\n"
        f"Статус: {status}"
    )
    return text


async def send_order_message(message, owner_id: int, order: UserOrder, is_current: bool = True):
    text = make_order_text(order, is_current)
    keyboard = make_order_keyboard(order.user_id, order, is_current)
    try:
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        logging.exception("Failed to send order message")

async def send_total_message(message, orders: list, is_current: bool, update_if_exists: bool = False):
    """Отправляет сообщение с суммой заказов, при необходимости обновляет существующее."""
    chat_id = message.chat.id
    total = db.get_orders_total(orders)
    label = "текущим" if is_current else "прошлым"
    text = f"💰 <b>Итого по {label} заказам: {total} ₽</b>"

    msg_id = last_total_message_ids.get(chat_id)

    if update_if_exists and msg_id:
        try:
            await message.bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=msg_id,
                parse_mode="HTML"
            )
            return
        except Exception:
            pass

    sent = await message.answer(text, parse_mode="HTML")
    last_total_message_ids[chat_id] = sent.message_id

async def send_updated_total(message, owner_id: int, is_current: bool = True):
    """Отправляет пользователю обновленную сумму по заказам."""
    orders = db.get_user_orders(owner_id, is_current=is_current)
    await send_total_message(message, orders, is_current, update_if_exists=True)

# ========== START HANDLER ==========
@user_router.message(Command(BotCommands.START.command))
async def start_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id

    # blacklist check
    if db.reg_is_blacklisted(user_id):
        await message.answer("⛔ Вы заблокированы и не можете зарегистрироваться. Обратитесь к администратору.")
        return

    if not db.user_exists(user_id):
        # new user — ask name
        await message.answer("Привет! Как тебя зовут? Введи, пожалуйста, своё имя:")
        await state.set_state(UserRegistration.waiting_for_name)
        return
    # If user entry exists but has no name, ask for it
    user = db.get_user(user_id)
    if not user or not user.name or str(user.name).strip() == "":
        await message.answer("Привет! Как тебя зовут? Введи, пожалуйста, своё имя:")
        await state.set_state(UserRegistration.waiting_for_name)
        return
    name = db.get_username(user_id)
    await message.answer(f"Привет, {name}! Выбери действие:", reply_markup=get_main_keyboard_for(user_id))

@user_router.message(UserRegistration.waiting_for_name)
async def name_handler(message: types.Message, state: FSMContext):
    name = message.text.strip()
    user_id = message.from_user.id

    # if user is blacklisted, block
    if db.reg_is_blacklisted(user_id):
        await message.answer("⛔ Вы заблокированы. Обратитесь к администратору.")
        await state.clear()
        return

    if db.is_admin(user_id):
        db.set_username(user_id, name)
        await message.answer(f"✅ Регистрация успешна. Приятно познакомиться, Администратор {name}!", reply_markup=get_main_keyboard_for(user_id))
        await state.clear()
    else:
        # store temporary name in state and ask password
        await state.update_data(candidate_name=name)
        await message.answer("Введите пароль для регистрации (у вас 3 попытки):")
        await state.set_state(UserRegistration.waiting_for_password)

@user_router.message(UserRegistration.waiting_for_password)
async def password_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data_state = await state.get_data()
    name = data_state.get("candidate_name", message.from_user.full_name or str(user_id))
    entered = message.text.strip()

    # get current auth password
    pwd = db.get_auth_password()
    if pwd is None:
        await message.answer("Регистрация временно закрыта — пароль не настроен. Обратитесь к администратору.")
        await state.clear()
        return

    if entered == pwd:
        # success
        db.add_user(user_id, name)
        db.reg_reset_attempts(user_id)
        await message.answer(f"✅ Регистрация успешна. Приятно познакомиться, {name}!", reply_markup=get_main_keyboard_for(user_id))
        await state.clear()
    else:
        # fail
        attempts = db.reg_increment_attempts(user_id)
        remaining = max(0, 3 - attempts)
        if attempts >= 3:
            db.reg_set_blacklisted(user_id, True)
            await message.answer("⛔ Слишком много неверных попыток. Вы добавлены в чёрный список.")
            await state.clear()
        else:
            await message.answer(f"Неверный пароль. Осталось попыток: {remaining}. Попробуйте ещё раз.")

# ========== WEBAPP HANDLER ==========
@user_router.message(lambda m: m.web_app_data is not None, RequireCollecting())
async def webapp_data_handler(message: types.Message):
    user_id = message.from_user.id

    # ensure registered
    if not db.user_exists(user_id):
        await message.answer(f"Вы не зарегистрированы. Нажмите /{BotCommands.START.command} чтобы зарегистрироваться.")
        return

    try:
        data = json.loads(message.web_app_data.data)
    except Exception:
        await message.answer("Неверные данные из WebApp. Заказ не принят.")
        return

    # Обновляем/добавляем товар в каталог продуктов
    pid = int(data.get("product_id", 0) or 0)
    title = data.get("title", "")
    price = int(data.get("price", 0) or 0)
    link = data.get("link", "")
    if pid:
        db.upsert_product(db.Product(product_id=pid, title=title, price=price, link=link))

    order = UserOrder(
        user_id=user_id,
        product_id=pid,
        count=int(data.get("count", 1) or 1),
        done=False
    )

    added_order = db.add_user_order(order)

    # send owner the created order message
    await send_order_message(message, user_id, added_order, is_current=True)

    await message.answer("✅ Заказ успешно добавлен.")
    
    # Send total after adding order
    all_orders = db.get_user_orders(user_id, True)
    await send_total_message(message, all_orders, True)

async def send_user_orders(message, user_id: int, is_current: bool):
    """Helper function to send user orders of specified type."""
    orders = db.get_user_orders(user_id, is_current)
    if not orders:
        order_type = "текущих" if is_current else "прошлых"
        await message.answer(f"У вас нет {order_type} заказов.", reply_markup=get_main_keyboard_for(user_id))
        return
    for order in orders:
        await send_order_message(message, user_id, order, is_current=is_current)
    await send_total_message(message, orders, is_current)

# ========== USER VIEWS ==========
@user_router.message(Command(BotCommands.ORDERS_CURRENT.command))
@user_router.message(F.text == BotCommands.ORDERS_CURRENT.button_text)
async def my_current_handler(message: types.Message):
    user_id = message.from_user.id
    await send_user_orders(message, user_id, True)

@user_router.message(Command(BotCommands.ORDERS_PAST.command))
@user_router.message(F.text == BotCommands.ORDERS_PAST.button_text)
async def user_past_handler(message: types.Message):
    user_id = message.from_user.id
    await send_user_orders(message, user_id, False)

@user_router.message(Command(BotCommands.ORDERS_MENU.command))
async def user_orders_handler(message: types.Message):
    user_id = message.from_user.id
    keyboard = make_order_type_selection_keyboard()
    await message.answer("Выберите тип заказов для просмотра:", reply_markup=keyboard)

# ========== CALLBACKS ==========
@user_router.callback_query(OrderAction.filter(F.action == OrderAction.ActionType.CANCEL))
async def cancel_order_callback(callback: types.CallbackQuery, callback_data: OrderAction):
    owner_id = callback_data.user_id
    product_id = callback_data.product_id
    
    if owner_id is None:
        await callback.answer("Неверные данные", show_alert=True)
        return

    order = db.get_user_order(owner_id, product_id, is_current=True)
    if order is None:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    # Cancel: owner or admin
    requester = callback.from_user.id
    if requester != owner_id and not db.is_admin(requester):
        await callback.answer("Нельзя отменить чужой заказ", show_alert=True)
        return
    if order.done:
        await callback.answer("Нельзя отменить выполненный заказ", show_alert=True)
        return
    removed = db.remove_user_order(owner_id, product_id, is_current=True)
    if removed:
        if callback.message and hasattr(callback.message, "edit_text"):
            try:
                name = db.get_username(owner_id) or str(owner_id)
                await callback.message.edit_text(f"{name} — заказ отменён ✅")
            except Exception:
                logging.exception("Failed to edit callback message after cancel")
        await callback.answer("Заказ отменён")
        await send_updated_total(callback.message, owner_id, is_current=True)
    else:
        await callback.answer("Не удалось отменить заказ", show_alert=True)

@user_router.callback_query(OrderAction.filter(F.action == OrderAction.ActionType.DELETE_PAST))
async def delete_past_order_callback(callback: types.CallbackQuery, callback_data: OrderAction):
    owner_id = callback_data.user_id
    product_id = callback_data.product_id
    
    if owner_id is None:
        await callback.answer("Неверные данные", show_alert=True)
        return

    order = db.get_user_order(owner_id, product_id, is_current=False)
    if order is None:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    # delete past: owner only
    requester = callback.from_user.id
    if requester != owner_id:
        await callback.answer("Нельзя удалять чужую запись", show_alert=True)
        return
    removed = db.remove_user_order(owner_id, product_id, is_current=False)
    if removed:
        if callback.message and hasattr(callback.message, "edit_text"):
            try:
                name = db.get_username(owner_id) or str(owner_id)
                await callback.message.edit_text(f"{name} — прошлый заказ удалён ❌")
            except Exception:
                logging.exception("Failed to edit callback message after deletepast")
        await callback.answer("Заказ удалён")
        await send_updated_total(callback.message, owner_id, is_current=False)
    else:
        await callback.answer("Не удалось удалить заказ", show_alert=True)

@user_router.callback_query(OrderAction.filter(F.action.in_([OrderAction.ActionType.INCREASE, OrderAction.ActionType.DECREASE])), RequireCollecting())
async def change_order_count_callback(callback: types.CallbackQuery, callback_data: OrderAction):
    owner_id = callback_data.user_id
    product_id = callback_data.product_id
    action = callback_data.action
    
    if owner_id is None:
        await callback.answer("Неверные данные", show_alert=True)
        return
    
    requester = callback.from_user.id
    if requester != owner_id:
        await callback.answer("Нельзя изменять чужой заказ", show_alert=True)
        return
    
    order = db.get_user_order(owner_id, product_id, is_current=True)
    if order is None:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    
    if order.done:
        await callback.answer("Нельзя изменять выполненный заказ", show_alert=True)
        return
    
    is_increase = action == OrderAction.ActionType.INCREASE
    delta = 1 if is_increase else -1
    new_count = order.count + delta
    if new_count < 1:
        await callback.answer("Нельзя уменьшить до 0", show_alert=True)
        return
    order.count = new_count
    if not db.upsert_user_order(order):
        await callback.answer("Не удалось обновить заказ", show_alert=True)
        return
    text = make_order_text(order, True)
    keyboard = make_order_keyboard(order.user_id, order, True)
    if callback.message and hasattr(callback.message, "edit_text"):
        try:
            await callback.message.edit_text(text, reply_markup=keyboard)
        except Exception:
            logging.exception(f"Failed to edit message after {action}")
    action_text = "увеличено" if is_increase else "уменьшено"
    await callback.answer(f"Количество {action_text}")
    await send_updated_total(callback.message, owner_id, is_current=True)

# ========== ORDER TYPE SELECTION ==========
@user_router.callback_query(OrderTypeAction.filter())
async def order_type_callback(callback: types.CallbackQuery, callback_data: OrderTypeAction):
    user_id = callback.from_user.id
    order_type = callback_data.order_type
    
    if order_type == OrderTypeAction.OrderType.CURRENT:
        await send_user_orders(callback.message, user_id, True)
    elif order_type == OrderTypeAction.OrderType.PAST:
        await send_user_orders(callback.message, user_id, False)
    
    await callback.answer()

# ========== HELP ==========
@user_router.message(Command(BotCommands.HELP.command))
async def help_handler(message: types.Message):
    """Show user help information."""
    await message.answer(generate_user_help())

