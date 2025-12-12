#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from typing import Any, List

from aiogram import Router, types, F, Bot
from aiogram.filters import Command

from utils.commands import BotCommands
from utils.keyboards import (
    get_main_keyboard_for,
    OrderAction,
    OrdersViewAction,
    CollectionAction,    
    make_order_done_keyboard,
    make_product_done_keyboard,
    make_orders_view_keyboard,
    make_collection_management_keyboard,
)
from utils.filters import IsAdmin
from db import orders_db as db

# Import from admin_router
from utils.broadcast import broadcast_message

# Import from user_orders_router
from .user_orders_router import make_order_text

admin_orders_router = Router(name="admin_orders_router")

# ========== COLLECTION MANAGEMENT ==========
# Функции для управления сбором заказов (открытие/закрытие)

@admin_orders_router.message(BotCommands.COLLECTION_MENU.filter, IsAdmin())
async def collection_menu_handler(message: types.Message):
    """Показывает меню управления сбором заказов"""
    await message.answer("Управление сбором заказов:", reply_markup=make_collection_management_keyboard())

@admin_orders_router.callback_query(CollectionAction.any())
async def collection_action_callback(callback: types.CallbackQuery, callback_data: CollectionAction):
    """Обрабатывает действия управления сбором заказов (открыть/закрыть)"""

    handlers = {
        CollectionAction.ActionType.NEW: new_collection_handler,
        CollectionAction.ActionType.OPEN: open_collection_handler,
        CollectionAction.ActionType.CLOSE: close_collection_handler,
    }

    handler = handlers.get(callback_data.action)
    if handler:
        await handler(callback.message)

    await callback.answer()

@admin_orders_router.message(BotCommands.COLLECTION_NEW.filter, IsAdmin())
async def new_collection_handler(message: types.Message):
    """Создаёт новый сбор заказов и уведомляет всех пользователей"""
    db.move_orders_to_old()
    db.set_collection_state(True)
    await broadcast_message(message.bot, "🎉 Новый сбор заказов открыт! Можно отправлять новые заказы.", for_admins=False)
    await message.answer("Сбор заказов открыт и всем пользователям отправлено уведомление.", reply_markup=get_main_keyboard_for(message.from_user.id))

@admin_orders_router.message(BotCommands.COLLECTION_OPEN.filter, IsAdmin())
async def open_collection_handler(message: types.Message):
    """Открывает текущий сбор заказов без создания нового"""
    db.set_collection_state(True)
    await broadcast_message(message.bot, "🎉 Сбор заказов снова открыт! Можно отправлять заказы.", for_admins=False)
    await message.answer("Сбор заказов открыт и всем пользователям отправлено уведомление.", reply_markup=get_main_keyboard_for(message.from_user.id))

@admin_orders_router.message(BotCommands.COLLECTION_CLOSE.filter, IsAdmin())
async def close_collection_handler(message: types.Message):
    """Закрывает сбор заказов и уведомляет всех пользователей"""
    db.set_collection_state(False)
    await broadcast_message(message.bot, "⛔ Сбор заказов закрыт. Спасибо за заявки.", for_admins=False)
    await message.answer("Сбор заказов закрыт и уведомления отправлены.", reply_markup=get_main_keyboard_for(message.from_user.id))

# ========== ORDER HELPERS ==========

def make_order_text_by_product(product: db.Product, orders: List[db.UserOrder]) -> tuple[str, bool]:
    """
    Формирует текст для сообщения о заказах, сгруппированных по товару.
    """
    if not orders:
        return "", True
    
    user_lines: list[str] = []
    all_done = True
    total_count = 0
    
    for order in orders:
        name = db.get_username(order.user_id) or "Без имени"
        status_icon = "✅" if order.done else "⏳"
        user_lines.append(f"{status_icon} <b>{name}</b> — {order.count} шт.")
        total_count += order.count
        if not order.done:
            all_done = False

    users_text = "\n".join(user_lines)

    text = (
        f"<b>{product.title} - {product.price} ₽</b>\n"
        f"Всего заказано: <b>{total_count} шт.</b>\n"
        f"Ссылка: {product.link}\n"
        f"Заказы пользователей:\n{users_text}"
    )

    return text, all_done

# ========== ORDER VIEWING ==========
# Функции для просмотра заказов

async def export_for_extension_handler(message: types.Message):
    """Генерирует список ID товаров для Chrome расширения с учётом количества товаров"""
    from utils.config import EXTENSION_URL
    
    grouped_orders = db.get_orders_grouped_by_product()
    
    if not grouped_orders:
        await message.answer("Нет текущих заказов для экспорта.")
        return
    
    product_ids = []
    for product_id, orders in grouped_orders.items():
        product = db.get_product(product_id)
        if not product or not product.product_id:
            continue
        
        # Подсчитываем общее количество заказов этого товара
        total_count = sum(order.count for order in orders)
        
        # Добавляем ID столько раз, сколько заказано
        # product_id на самом деле является seller_id в базе
        for _ in range(total_count):
            product_ids.append(str(product.product_id))
    
    if not product_ids:
        await message.answer("Нет товаров для экспорта (не найдены product_id).")
        return
    
    # Формируем список ID через запятую
    ids_text = ",".join(product_ids)
    
    if EXTENSION_URL:
        extension_url = f"{EXTENSION_URL}?ids={ids_text}&auto=1&clear_basket=1"
        text = (
            f"📋 <b>Список для расширения</b> ({len(product_ids)} шт.)\n\n"
            f"<b>ID товаров:</b>\n<code>{ids_text}</code>\n\n"
            f"<b>Ссылка для расширения:</b>\n<code>{extension_url}</code>\n\n"
            f"💡 <i>Скопируйте ссылку выше и вставьте в адресную строку браузера</i>"
        )
    else:
        text = f"ID товаров ({len(product_ids)} шт.):\n<code>{ids_text}</code>"
    
    await message.answer(text, parse_mode="HTML")

@admin_orders_router.message(BotCommands.ADMIN_ORDERS_MENU.filter, IsAdmin())
async def all_orders_menu_handler(message: types.Message):
    """Показывает меню выбора типа просмотра заказов"""
    await message.answer("Выберите тип просмотра заказов:", reply_markup=make_orders_view_keyboard())

@admin_orders_router.callback_query(OrdersViewAction.any())
async def orders_view_callback(callback: types.CallbackQuery, callback_data: OrdersViewAction):
    """Обрабатывает выбор типа просмотра заказов (по пользователям/по товарам)"""

    handlers = {
        OrdersViewAction.ActionType.BY_USER: all_orders_by_user_handler,
        OrdersViewAction.ActionType.BY_PRODUCT: all_orders_by_product_handler,
        OrdersViewAction.ActionType.EXPORT_EXTENSION: export_for_extension_handler,
    }

    handler = handlers.get(callback_data.action)
    if handler:
        await handler(callback.message)

    await callback.answer()

@admin_orders_router.message(BotCommands.ADMIN_ORDERS_BY_USER.filter, IsAdmin())
async def all_orders_by_user_handler(message: types.Message):
    """Показывает все текущие заказы, сгруппированные по пользователям"""

    # Получаем все заказы, сгруппированные по пользователям
    grouped_orders = db.get_orders_grouped_by_user()

    if not grouped_orders:
        await message.answer("Нет текущих заказов.", reply_markup=get_main_keyboard_for(message.from_user.id))
        return

    # Проходимся по каждому пользователю и его заказам
    for user_id, orders in grouped_orders.items():
        # Заголовок с именем пользователя один раз
        header_name = db.get_username(user_id) or str(user_id)
        await message.answer(f"<b>{header_name}</b>", parse_mode="HTML")
        # Показываем заказы пользователя без имени в каждом заказе
        for order in orders:
            text = make_order_text(order, is_current=True, show_name=False)
            keyboard = make_order_done_keyboard(order.user_id, order.product_id, order.done)
            await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    
    # Показываем пользователей без заказов
    users_without_orders = db.get_users_without_orders()
    if users_without_orders:
        names = [user.name for user in users_without_orders]
        await message.answer(
            f"<b>Пользователи без заказов:</b>\n{', '.join(names)}",
            parse_mode="HTML"
        )
    
    # Добавляем кнопку для экспорта в расширение
    from utils.keyboards import make_export_extension_keyboard
    await message.answer("Экспорт:", reply_markup=make_export_extension_keyboard())



#@admin_orders_router.message(BotCommands.ADMIN_ORDERS_BY_PRODUCT.filter, IsAdmin())
@admin_orders_router.message(BotCommands.ADMIN_ORDERS_BY_PRODUCT.filter, IsAdmin())
async def all_orders_by_product_handler(message: types.Message):
    """Показывает все текущие заказы, сгруппированные по товарам"""

    grouped_orders = db.get_orders_grouped_by_product()

    if not grouped_orders:
        await message.answer("Нет текущих заказов.", reply_markup=get_main_keyboard_for(message.from_user.id))
        return

    for product_id, orders in grouped_orders.items():
        product = db.get_product(product_id)
        if not product:
            continue
        # Формируем текст сообщения через хелпер
        text, all_done = make_order_text_by_product(product, orders)
        # Кнопка для отметки всех заказов этого товара как выполненных
        keyboard = make_product_done_keyboard(product.product_id, all_done)
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    
    # Показываем пользователей без заказов
    users_without_orders = db.get_users_without_orders()
    if users_without_orders:
        names = [user.name for user in users_without_orders]
        await message.answer(
            f"<b>Пользователи без заказов:</b>\n{', '.join(names)}",
            parse_mode="HTML"
        )
    
    # Добавляем кнопку для экспорта в расширение
    from utils.keyboards import make_export_extension_keyboard
    await message.answer("Экспорт:", reply_markup=make_export_extension_keyboard())


@admin_orders_router.callback_query(OrderAction.filter_action(OrderAction.ActionType.DONE_PRODUCT))
async def mark_product_done_callback(callback: types.CallbackQuery, callback_data: OrderAction):
    """Отмечает все заказы конкретного товара как выполненные для всех пользователей"""

    if db.is_collecting():
        await callback.answer("Нельзя отмечать выполненными пока сбор заказов открыт", show_alert=True)
        return

    updated_count = db.mark_product_done_for_all_users(callback_data.product_id)

    # Обновляем текст сообщения с новыми статусами
    product = db.get_product(callback_data.product_id)
    if product and callback.message:
        grouped_orders = db.get_orders_grouped_by_product()
        orders = grouped_orders.get(callback_data.product_id, [])
        text, all_done = make_order_text_by_product(product, orders)
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=None)
        except Exception:
            logging.exception("Failed to edit product message after marking done")

    await callback.answer(f"Отмечено выполненным {updated_count} заказов")

@admin_orders_router.callback_query(OrderAction.filter_action(OrderAction.ActionType.DONE_PRODUCT))
async def mark_order_done_callback(callback: types.CallbackQuery, callback_data: OrderAction):
    """Отмечает конкретный заказ пользователя как выполненный"""

    if db.is_collecting():
        await callback.answer("Нельзя отмечать выполненными пока сбор заказов открыт", show_alert=True)
        return

    owner_id = callback_data.user_id
    product_id = callback_data.product_id

    order = db.get_user_order(owner_id, product_id, is_current=True)
    if order is None:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    order.done = True
    db.upsert_user_order(order)
    text = make_order_text(order, is_current=True, show_name=False)

    try:
        # Обновляем текст заказа с новым статусом
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=None)
    except Exception:
        logging.exception("Failed to edit callback message after marking done")

    await callback.answer("Заказ отмечен как выполненный")