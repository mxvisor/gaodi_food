#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
from typing import Optional

from aiogram import Router, types, F
from aiogram.filters import Command

from utils.commands import BotCommands, generate_user_help
from utils.keyboards import (
    get_main_keyboard_for, 
    OrderAction, 
    OrderTypeAction,    
    make_order_keyboard,
    make_order_type_selection_keyboard,
)
from utils.filters import RequireCollecting
from db import orders_db as db

# Import from main bot file (will be set by bot.py)
# Bot instance no longer needed - using message.bot and callback.bot instead

user_orders_router = Router(name="user_orders_router")

# Dictionary to store last total message ID for each chat
last_total_message_ids = {}

# ========== Keyboards ==========
# (moved to keyboards.py)

# ========== ORDER HELPERS ==========
def make_order_text(order: db.UserOrder, is_current: bool, show_name: bool = True) -> str:
    name = db.get_username(order.user_id) or str(order.user_id)
    status = "✅ Выполнен" if order.done else ("⏳ Текущий" if is_current else "📦 Прошлый")
    # Получаем данные товара из каталога
    product = db.get_product(order.product_id)
    title = product.title if product else f"Товар #{order.product_id}"
    price = product.price if product else 0
    link = product.link if product else ""
    header = f"<b>{name}</b>\n" if show_name else ""
    text = (
        f"{header}"
        f"{title} - <b>{price} ₽</b>\n"
        f"Количество: <b>{order.count}</b>\n"
        f"Ссылка: {link}\n"
        f"Статус: {status}"
    )
    return text

async def send_order_message(message, owner_id: int, order: db.UserOrder, is_current: bool = True, show_name: bool = True):
    text = make_order_text(order, is_current, show_name=show_name)
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

async def send_user_orders(message, user_id: int, is_current: bool):
    """Helper function to send user orders of specified type."""
    orders = db.get_user_orders(user_id, is_current)
    if not orders:
        order_type = "текущих" if is_current else "прошлых"
        await message.answer(f"У вас нет {order_type} заказов.", reply_markup=get_main_keyboard_for(user_id))
        return
    # Header with user name printed once
    header_name = db.get_username(user_id) or str(user_id)
    await message.answer(f"<b>{header_name}</b>", parse_mode="HTML")
    for order in orders:
        await send_order_message(message, user_id, order, is_current=is_current, show_name=False)
    await send_total_message(message, orders, is_current)

# ========== WEBAPP HANDLER ==========
@user_orders_router.message(lambda m: m.web_app_data is not None, RequireCollecting())
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

    # Поддержка массива заказов или одного заказа
    if isinstance(data, list):
        orders_list = data
    else:
        orders_list = [data]

    added_orders = []
    for order_data in orders_list:
        # Обновляем/добавляем товар в каталог продуктов
        pid = int(order_data.get("selled_id", 0) or 0) # Это не ошибка, берётся реально seller_id!
        title = order_data.get("title", "")
        price = int(order_data.get("price", 0) or 0)
        link = order_data.get("link", "")
        if pid:
            db.upsert_product(db.Product(product_id=pid, title=title, price=price, link=link))

        order = db.UserOrder(
            user_id=user_id,
            product_id=pid,
            count=int(order_data.get("count", 1) or 1),
            done=False
        )

        added_order = db.add_user_order(order)
        added_orders.append(added_order)

    await message.answer(f"✅ {len(added_orders)} заказ(ов) успешно добавлен(ы).")

    # send owner the created order messages
    for added_order in added_orders:
        await send_order_message(message, user_id, added_order, is_current=True)
    
    # Send total after adding order
    all_orders = db.get_user_orders(user_id, True)
    await send_total_message(message, all_orders, True)

# ========== USER VIEWS ==========

@user_orders_router.message(BotCommands.ORDERS_CURRENT.filter)
async def my_current_handler(message: types.Message):
    user_id = message.from_user.id
    await send_user_orders(message, user_id, True)

@user_orders_router.message(BotCommands.ORDERS_PAST.filter)
async def user_past_handler(message: types.Message):
    user_id = message.from_user.id
    await send_user_orders(message, user_id, False)

@user_orders_router.message(BotCommands.ORDERS_MENU.filter)
async def user_orders_handler(message: types.Message):
    user_id = message.from_user.id
    keyboard = make_order_type_selection_keyboard()
    await message.answer("Выберите тип заказов для просмотра:", reply_markup=keyboard)

# ========== CALLBACKS ==========
@user_orders_router.callback_query(OrderAction.filter_action(OrderAction.ActionType.CANCEL))
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
                await callback.message.edit_text("Заказ отменён ✅")
            except Exception:
                logging.exception("Failed to edit callback message after cancel")
        await callback.answer("Заказ отменён")
        await send_updated_total(callback.message, owner_id, is_current=True)
    else:
        await callback.answer("Не удалось отменить заказ", show_alert=True)

@user_orders_router.callback_query(OrderAction.filter_action(OrderAction.ActionType.DELETE_PAST))
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
                await callback.message.edit_text("Прошлый заказ удалён ❌")
            except Exception:
                logging.exception("Failed to edit callback message after deletepast")
        await callback.answer("Заказ удалён")
        await send_updated_total(callback.message, owner_id, is_current=False)
    else:
        await callback.answer("Не удалось удалить заказ", show_alert=True)

@user_orders_router.callback_query(OrderAction.adjust(), RequireCollecting())
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
    text = make_order_text(order, True, show_name=False)
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
@user_orders_router.callback_query(OrderTypeAction.any())
async def order_type_callback(callback: types.CallbackQuery, callback_data: OrderTypeAction):
    user_id = callback.from_user.id
    order_type = callback_data.order_type
    
    if order_type == OrderTypeAction.OrderType.CURRENT:
        await send_user_orders(callback.message, user_id, True)
    elif order_type == OrderTypeAction.OrderType.PAST:
        await send_user_orders(callback.message, user_id, False)
    
    await callback.answer()

# ========== HELP ==========
# Moved to help_router.py

