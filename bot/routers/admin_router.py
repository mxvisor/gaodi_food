#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from typing import Optional, List

from aiogram import Router, types, F, Bot, exceptions
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from utils.commands import BotCommands, generate_admin_help, setup_admin_commands, reset_admin_commands
from utils.keyboards import (
    get_main_keyboard_for,
    make_order_done_keyboard,
    make_product_done_keyboard,
    OrderAction,
    UserAction,
    make_user_management_keyboard,
    make_password_menu,
    PasswordAction,
    make_users_management_menu,
    make_blacklist_management_menu,
    make_remove_from_blacklist_keyboard,
    make_remove_admin_keyboard,
    CollectionAction,
    make_collection_management_menu,
    OrdersViewAction,
    make_orders_view_menu,
    make_users_list_page,
    UsersPageAction,
    make_blacklist_list_page,
    BlacklistPageAction,
)
from utils.filters import IsAdmin
from db.orders_db import UserOrder, OrderSummary, User, Product
from db import orders_db as db

# Import from user_router
from .user_router import get_main_keyboard_for, make_order_text

admin_router = Router(name="admin_router")

# ========== ADMIN STATES ==========
class AdminStates(StatesGroup):
    """Состояния для многошаговых операций администратора"""
    waiting_for_new_name = State()
    waiting_for_new_password = State()
    waiting_for_user_id_add_user = State()
    waiting_for_user_id_add_admin = State()
    waiting_for_user_id_del_admin = State()
    waiting_for_user_id_del_user = State()
    waiting_for_user_id_rename_user = State()
    waiting_for_user_id_add_to_blacklist = State()
    waiting_for_user_id_remove_from_blacklist = State()

# ========== UTILITY FUNCTIONS ==========

async def broadcast_to_all_users(bot, text: str):
    """Отправляет сообщение всем пользователям бота"""
    users = db.get_users()
    for user in users:
        try:
            await bot.send_message(user.user_id, text)
        except Exception as e:
            if "chat not found" in str(e).lower():
                # User has blocked the bot or deleted chat, remove from db
                db.remove_user(user.user_id)
                logging.info(f"Removed user {user.user_id} due to chat not found")
            else:
                logging.exception(f"Failed to broadcast to user {user.user_id}")


def make_order_text_by_product(product: Product, orders: List[UserOrder]) -> tuple[str, bool]:
    """
    Формирует текст для сообщения о заказах, сгруппированных по товару.

    Возвращает кортеж (text, all_done), где all_done указывает, выполнены ли все заказы по этому товару.
    orders: список UserOrder
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


def safe_can_edit(message: Optional[types.Message]) -> bool:
    """Return True if we can safely call edit_text on this message object."""
    return bool(message) and hasattr(message, "edit_text")


async def safe_edit_text(message: Optional[types.Message], text: str, **kwargs):
    """Try to edit a message; fall back to sending a new message if editing isn't available.

    kwargs may include reply_markup, parse_mode etc.
    """
    if safe_can_edit(message):
        try:
            return await message.edit_text(text, **kwargs)
        except Exception:
            logging.exception("safe_edit_text: edit failed, fallback to answer")
    if message and hasattr(message, "answer"):
        try:
            return await message.answer(text, **kwargs)
        except Exception:
            logging.exception("safe_edit_text: answer failed")
    return None


# ========== COLLECTION MANAGEMENT ==========
# Функции для управления сбором заказов (открытие/закрытие)

@admin_router.message(Command(BotCommands.COLLECTION_NEW.command), IsAdmin())
@admin_router.message(F.text == BotCommands.COLLECTION_NEW.button_text, IsAdmin())
async def new_collection_handler(message: types.Message):
    """Открывает сбор заказов и уведомляет всех пользователей"""
    db.move_orders_to_old()
    db.set_collection_state(True)
    await broadcast_to_all_users(message.bot, "🎉 Новый сбор заказов открыт! Можно отправлять новые заказы.")
    await message.answer("Сбор заказов открыт и всем пользователям отправлено уведомление.", reply_markup=get_main_keyboard_for(message.from_user.id))

@admin_router.message(Command(BotCommands.COLLECTION_CLOSE.command), IsAdmin())
@admin_router.message(F.text == BotCommands.COLLECTION_CLOSE.button_text, IsAdmin())
async def close_collection_handler(message: types.Message):
    """Закрывает сбор заказов и уведомляет всех пользователей"""
    db.set_collection_state(False)
    await broadcast_to_all_users(message.bot, "⛔ Сбор заказов закрыт. Спасибо за заявки.")
    await message.answer("Сбор заказов закрыт и уведомления отправлены.", reply_markup=get_main_keyboard_for(message.from_user.id))

@admin_router.message(Command(BotCommands.COLLECTION_OPEN.command), IsAdmin())
@admin_router.message(F.text == BotCommands.COLLECTION_OPEN.button_text, IsAdmin())
async def open_collection_handler(message: types.Message):
    """Открывает текущий сбор заказов без создания нового"""
    db.set_collection_state(True)
    await broadcast_to_all_users(message.bot, "🎉 Сбор заказов снова открыт! Можно отправлять заказы.")
    await message.answer("Сбор заказов открыт и всем пользователям отправлено уведомление.", reply_markup=get_main_keyboard_for(message.from_user.id))

@admin_router.message(Command(BotCommands.COLLECTION_MENU.command), IsAdmin())
async def collection_cmd(message: types.Message):
    """Показывает меню управления сбором заказов"""
    await message.answer("Управление сбором заказов:", reply_markup=make_collection_management_menu())

@admin_router.callback_query(CollectionAction.filter())
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


# ========== ORDER VIEWING ==========
# Функции для просмотра заказов

@admin_router.message(Command(BotCommands.ADMIN_ORDERS_BY_USER.command), IsAdmin())
@admin_router.message(F.text == BotCommands.ADMIN_ORDERS_BY_USER.button_text, IsAdmin())
async def all_orders_handler(message: types.Message):
    """Показывает все текущие заказы, сгруппированные по пользователям"""

    # Получаем все заказы, сгруппированные по пользователям
    grouped_orders = db.get_orders_grouped_by_user()

    if not grouped_orders:
        await message.answer("Нет текущих заказов.", reply_markup=get_main_keyboard_for(message.from_user.id))
        return

    # Проходимся по каждому пользователю и его заказам
    for user_id, orders in grouped_orders.items():
        # Отправляем заказы пользователя
        for order in orders:
            text = make_order_text(order, is_current=True)
            # Use order.user_id to ensure correct ownership in callbacks
            keyboard = make_order_done_keyboard(order.user_id, order.product_id, order.done)
            await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

@admin_router.message(Command(BotCommands.ADMIN_ORDERS_BY_PRODUCT.command), IsAdmin())
@admin_router.message(F.text == BotCommands.ADMIN_ORDERS_BY_PRODUCT.button_text, IsAdmin())
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

@admin_router.callback_query(OrdersViewAction.filter())
async def orders_view_callback(callback: types.CallbackQuery, callback_data: OrdersViewAction):
    """Обрабатывает выбор типа просмотра заказов (по пользователям/по товарам)"""

    view_type = callback_data.view_type

    if view_type == OrdersViewAction.ActionType.BY_USER:
        # Вызываем существующий обработчик для просмотра заказов по пользователям
        await all_orders_handler(callback.message)
    elif view_type == OrdersViewAction.ActionType.BY_PRODUCT:
        # Вызываем существующий обработчик для просмотра заказов по товарам
        await all_orders_by_product_handler(callback.message)

    await callback.answer()


# ========== ADMIN MENU COMMANDS ==========
# Команды для отображения меню управления

@admin_router.message(Command(BotCommands.ADMIN_ORDERS_MENU.command), IsAdmin())
async def all_orders_menu_cmd(message: types.Message):
    """Показывает меню выбора типа просмотра заказов"""
    await message.answer("Выберите тип просмотра заказов:", reply_markup=make_orders_view_menu())


# ========== HELP AND INFO ==========
# Справка и информационные команды

@admin_router.message(Command(BotCommands.ADMIN_HELP.command), IsAdmin())
async def admin_help_handler(message: types.Message):
    """Показывает справку по командам администратора"""

    await message.answer(generate_admin_help(), parse_mode=None)


# ========== ORDER MANAGEMENT CALLBACKS ==========
# Callback'и для управления заказами (отметка как выполненные)

@admin_router.callback_query(OrderAction.filter(F.action == OrderAction.ActionType.DONE_PRODUCT))
async def mark_product_done_callback(callback: types.CallbackQuery, callback_data: OrderAction):
    """Отмечает все заказы конкретного товара как выполненные для всех пользователей"""

    if db.is_collecting():
        await callback.answer("Нельзя отмечать выполненными пока сбор заказов открыт", show_alert=True)
        return

    updated_count = db.mark_product_done_for_all_users(callback_data.product_id)

    if callback.message and hasattr(callback.message, "edit_reply_markup"):
        # Убираем кнопку после выполнения
        await callback.message.edit_reply_markup(reply_markup=None)

    await callback.answer(f"Отмечено выполненным {updated_count} заказов")

@admin_router.callback_query(OrderAction.filter(F.action == OrderAction.ActionType.DONE))
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

    if callback.message and hasattr(callback.message, "edit_text"):
        try:
            name = db.get_username(owner_id) or str(owner_id)
            await callback.message.edit_text(f"{name} — заказ отмечен как выполненный ✅")
        except Exception:
            logging.exception("Failed to edit callback message after marking done")

    await callback.answer("Заказ отмечен как выполненный")


# ========== USER MANAGEMENT CALLBACKS ==========
# Callback'и для управления пользователями

@admin_router.message(Command(BotCommands.USERS_MENU.command), IsAdmin())
async def list_users_cmd(message: types.Message):
    """Сразу показывает список пользователей (стр. 1) с пагинацией и кнопкой Добавить."""
    users = db.get_users()
    if not users:
        # Пустой список: показать кнопки Обновить и Добавить пользователя
        add_row = [types.InlineKeyboardButton(text="Добавить пользователя", callback_data=UserAction(action=UserAction.ActionType.ADD_USER).pack())]
        refresh_row = [types.InlineKeyboardButton(text="🔄 Обновить", callback_data=UsersPageAction(page=1).pack())]
        empty_kb = types.InlineKeyboardMarkup(inline_keyboard=[add_row, refresh_row])
        await message.answer("Пользователей пока нет.", reply_markup=empty_kb)
        return

    # Админов показываем первыми
    users_sorted = sorted(users, key=lambda u: (not u.is_admin, u.user_id))

    kb = make_users_list_page(users_sorted, page=1)
    # Добавляем кнопку под списком
    add_row = [types.InlineKeyboardButton(text="Добавить пользователя", callback_data=UserAction(action=UserAction.ActionType.ADD_USER).pack())]
    refresh_row = [types.InlineKeyboardButton(text="🔄 Обновить", callback_data=UsersPageAction(page=1).pack())]
    full_kb = types.InlineKeyboardMarkup(inline_keyboard=kb.inline_keyboard + [add_row, refresh_row])

    await message.answer("Список пользователей (стр. 1):", reply_markup=full_kb)

@admin_router.callback_query(UserAction.filter(F.action == UserAction.ActionType.RENAME))
async def rename_user_callback(callback: types.CallbackQuery, callback_data: UserAction, state: FSMContext):
    """Начинает процесс переименования пользователя"""

    target_user_id = callback_data.target_user_id
    user = db.get_user(target_user_id)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    # Сохраняем ID пользователя для переименования в состоянии
    await state.update_data(target_user_id=target_user_id, old_name=user.name)
    await state.set_state(AdminStates.waiting_for_new_name)

    await callback.message.answer(f"Введите новое имя для пользователя {user.name} (ID: {target_user_id}):", parse_mode=None)
    await callback.answer()

@admin_router.message(AdminStates.waiting_for_new_name, IsAdmin())
async def process_new_name(message: types.Message, state: FSMContext):
    """Обрабатывает ввод нового имени пользователя"""

    new_name = message.text.strip() if message.text else ""
    if not new_name:
        await message.answer("Имя не может быть пустым. Попробуйте ещё раз:")
        return

    # Получаем данные из состояния
    data = await state.get_data()
    target_user_id = data.get('target_user_id')
    old_name = data.get('old_name')

    if not target_user_id:
        await state.clear()
        await message.answer("Ошибка: не найден ID пользователя для переименования.")
        return

    # Переименовываем пользователя
    db.set_username(target_user_id, new_name)
    await message.answer(f"✅ Пользователь переименован: {old_name} → {new_name} (ID: {target_user_id})", parse_mode=None)

    await state.clear()

@admin_router.callback_query(UserAction.filter(F.action == UserAction.ActionType.LIST_USERS))
async def list_users_callback(callback: types.CallbackQuery):
    """Показывает список всех пользователей с кнопками управления"""
    users = db.get_users()
    if not users:
        if callback.message:
            add_row = [types.InlineKeyboardButton(text="Добавить пользователя", callback_data=UserAction(action=UserAction.ActionType.ADD_USER).pack())]
            refresh_row = [types.InlineKeyboardButton(text="🔄 Обновить", callback_data=UsersPageAction(page=1).pack())]
            empty_kb = types.InlineKeyboardMarkup(inline_keyboard=[add_row, refresh_row])
            await callback.message.answer("Пользователей пока нет.", reply_markup=empty_kb)
        await callback.answer()
        return

    # Админов показываем первыми
    users_sorted = sorted(users, key=lambda u: (not u.is_admin, u.user_id))

    kb = make_users_list_page(users_sorted, page=1)
    if callback.message:
        add_row = [types.InlineKeyboardButton(text="Добавить пользователя", callback_data=UserAction(action=UserAction.ActionType.ADD_USER).pack())]
        refresh_row = [types.InlineKeyboardButton(text="🔄 Обновить", callback_data=UsersPageAction(page=1).pack())]
        full_kb = types.InlineKeyboardMarkup(inline_keyboard=kb.inline_keyboard + [add_row, refresh_row])
        await callback.message.answer("Список пользователей (стр. 1):", reply_markup=full_kb)
    await callback.answer()

@admin_router.callback_query(UsersPageAction.filter())
async def paginate_users_callback(callback: types.CallbackQuery, callback_data: UsersPageAction):
    """Обработка навигации по страницам списка пользователей."""
    users = db.get_users()
    page = callback_data.page
    if not users:
        if not callback.message:
            await callback.answer()
            return
        try:
            add_row = [types.InlineKeyboardButton(text="Добавить пользователя", callback_data=UserAction(action=UserAction.ActionType.ADD_USER).pack())]
            refresh_row = [types.InlineKeyboardButton(text="🔄 Обновить", callback_data=UsersPageAction(page=1).pack())]
            empty_kb = types.InlineKeyboardMarkup(inline_keyboard=[add_row, refresh_row])
            await callback.message.edit_text("Пользователей пока нет.", reply_markup=empty_kb)
        except Exception:
            logging.exception("Failed to show empty users list on refresh")
            try:
                await callback.message.answer("Пользователей пока нет.", reply_markup=empty_kb)
            except Exception:
                logging.exception("Failed to send empty users list message")
        await callback.answer()
        return
    # Админов показываем первыми
    users_sorted = sorted(users, key=lambda u: (not u.is_admin, u.user_id))
    kb = make_users_list_page(users_sorted, page=page)
    if not callback.message:
        await callback.answer()
        return
    try:
        add_row = [types.InlineKeyboardButton(text="Добавить пользователя", callback_data=UserAction(action=UserAction.ActionType.ADD_USER).pack())]
        refresh_row = [types.InlineKeyboardButton(text="🔄 Обновить", callback_data=UsersPageAction(page=page).pack())]
        full_kb = types.InlineKeyboardMarkup(inline_keyboard=kb.inline_keyboard + [add_row, refresh_row])
        await callback.message.edit_text(f"Список пользователей (стр. {page}):", reply_markup=full_kb)
    except exceptions.TelegramBadRequest as e:
        # Ignore harmless case when nothing changed
        if "message is not modified" in str(e).lower():
            pass
        else:
            logging.exception("Failed to edit users page message; sending new one")
            try:
                add_row = [types.InlineKeyboardButton(text="Добавить пользователя", callback_data=UserAction(action=UserAction.ActionType.ADD_USER).pack())]
                refresh_row = [types.InlineKeyboardButton(text="🔄 Обновить", callback_data=UsersPageAction(page=page).pack())]
                full_kb = types.InlineKeyboardMarkup(inline_keyboard=kb.inline_keyboard + [add_row, refresh_row])
                await callback.message.answer(f"Список пользователей (стр. {page}):", reply_markup=full_kb)
            except Exception:
                logging.exception("Failed to send users page message")
    except Exception:
        logging.exception("Failed to edit users page message (unexpected)")
        try:
            add_row = [types.InlineKeyboardButton(text="Добавить пользователя", callback_data=UserAction(action=UserAction.ActionType.ADD_USER).pack())]
            refresh_row = [types.InlineKeyboardButton(text="🔄 Обновить", callback_data=UsersPageAction(page=page).pack())]
            full_kb = types.InlineKeyboardMarkup(inline_keyboard=kb.inline_keyboard + [add_row, refresh_row])
            await callback.message.answer(f"Список пользователей (стр. {page}):", reply_markup=full_kb)
        except Exception:
            logging.exception("Failed to send users page message")
    await callback.answer()

@admin_router.callback_query(UserAction.filter(F.action == UserAction.ActionType.SHOW))
async def show_user_manage_callback(callback: types.CallbackQuery, callback_data: UserAction):
    """Показать управление для выбранного пользователя из списка."""
    user_id = callback_data.target_user_id
    if user_id is None:
        await callback.answer("Не найден пользователь", show_alert=True)
        return
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

@admin_router.callback_query(UserAction.filter(F.action == UserAction.ActionType.ADD_USER))
async def add_user_by_id_callback(callback: types.CallbackQuery, state: FSMContext):
    """Начинает процесс добавления пользователя по ID"""

    await state.set_state(AdminStates.waiting_for_user_id_add_user)
    await callback.message.answer("Введите ID пользователя, которого хотите добавить:", parse_mode=None)
    await callback.answer()

@admin_router.callback_query(UserAction.filter(F.action == UserAction.ActionType.DEL_USER))
async def del_user_by_id_callback(callback: types.CallbackQuery, state: FSMContext):
    """Начинает процесс удаления пользователя"""

    await state.set_state(AdminStates.waiting_for_user_id_del_user)
    await callback.message.answer("Введите ID пользователя, которого хотите удалить:", parse_mode=None)
    await callback.answer()

@admin_router.callback_query(UserAction.filter(F.action == UserAction.ActionType.RENAME_USER))
async def rename_user_by_id_callback(callback: types.CallbackQuery, state: FSMContext):
    """Начинает процесс переименования пользователя по ID"""

    await state.set_state(AdminStates.waiting_for_user_id_rename_user)
    await callback.message.answer("Введите ID пользователя, которого хотите переименовать:", parse_mode=None)
    await callback.answer()

@admin_router.message(AdminStates.waiting_for_user_id_rename_user, IsAdmin())
async def process_rename_user_by_id(message: types.Message, state: FSMContext):
    """Обрабатывает ввод ID пользователя для переименования"""

    if not message.from_user:
        await state.clear()
        return

    try:
        target = int(message.text.strip() if message.text else "")
    except ValueError:
        await message.answer("Неверный ID пользователя. Введите число:")
        return

    user = db.get_user(target)
    if not user:
        await message.answer("Пользователь не найден.")
        await state.clear()
        return

    # Сохраняем ID пользователя для переименования в состоянии
    await state.update_data(target_user_id=target, old_name=user.name)
    await state.set_state(AdminStates.waiting_for_new_name)

    await message.answer(f"Введите новое имя для пользователя {user.name} (ID: {target}):", parse_mode=None)

@admin_router.callback_query(UserAction.filter(F.action == UserAction.ActionType.ADD_ADMIN))
async def add_user_to_admins_callback(callback: types.CallbackQuery, callback_data: UserAction, state: FSMContext):
    """Добавляет пользователя в администраторы"""

    if callback_data.target_user_id:
        db.add_admin(callback_data.target_user_id)
        await setup_admin_commands(callback.bot, callback_data.target_user_id)
        await callback.message.answer(f"Пользователь {callback_data.target_user_id} добавлен в админы.")
    else:
        await state.set_state(AdminStates.waiting_for_user_id_add_admin)
        await callback.message.answer("Введите ID пользователя, которого хотите сделать администратором:")
    await callback.answer()

@admin_router.callback_query(UserAction.filter(F.action == UserAction.ActionType.REMOVE_ADMIN))
async def remove_user_from_admins_callback(callback: types.CallbackQuery, callback_data: UserAction, state: FSMContext):
    """Удаляет пользователя из администраторов"""

    if callback_data.target_user_id:
        if callback_data.target_user_id == callback.from_user.id:
            await callback.answer("Нельзя удалить себя из админов", show_alert=True)
            return
        db.del_admin(callback_data.target_user_id)
        await reset_admin_commands(callback.bot, callback_data.target_user_id)
        await callback.message.answer(f"Пользователь {callback_data.target_user_id} удалён из админов.")
    else:
        await state.set_state(AdminStates.waiting_for_user_id_del_admin)
        await callback.message.answer("Введите ID пользователя, которого хотите удалить из администраторов:")
    await callback.answer()

@admin_router.callback_query(UserAction.filter(F.action == UserAction.ActionType.LIST_ADMINS))
async def list_admins_callback(callback: types.CallbackQuery):
    """Показывает список всех администраторов с кнопками управления"""

    users = db.get_users()
    admins = [user for user in users if user.is_admin]
    if not admins:
        await callback.message.answer("Администраторов пока нет.")
        await callback.answer()
        return

    await callback.message.answer("Список администраторов:")
    for admin in admins:
        keyboard = make_remove_admin_keyboard(admin.user_id)
        name = admin.name or "Без имени"
        text = f"⭐ {admin.user_id} — {name}"
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=None)

    await callback.answer()

@admin_router.callback_query(UserAction.filter(F.action == UserAction.ActionType.REMOVE_ADMIN_DIRECT))
async def remove_admin_direct_callback(callback: types.CallbackQuery, callback_data: UserAction):
    """Удаляет пользователя из администраторов напрямую (без подтверждения)"""

    target_user_id = callback_data.target_user_id
    if target_user_id == callback.from_user.id:
        await callback.answer("Нельзя удалить себя из админов", show_alert=True)
        return

    db.del_admin(target_user_id)
    # Reset commands to user level for the removed admin
    await reset_admin_commands(callback.bot, target_user_id)

    # Обновляем сообщение с кнопкой
    name = db.get_username(target_user_id) or "Без имени"
    text = f"❌ {target_user_id} — {name} удалён из админов"
    await callback.message.edit_text(text, reply_markup=None, parse_mode=None)
    await callback.answer()


# ========== BLACKLIST MANAGEMENT CALLBACKS ==========
# Callback'и для управления черным списком

@admin_router.message(Command(BotCommands.BLACKLIST_MENU.command), IsAdmin())
async def blacklist_cmd(message: types.Message):
    """Сразу показывает чёрный список (страница 1) с пагинацией и кнопкой добавления."""
    bl = db.get_blacklist()
    if not bl:
        add_row = [types.InlineKeyboardButton(text="Добавить в чёрный список", callback_data=UserAction(action=UserAction.ActionType.ADD_TO_BLACKLIST, target_user_id=None).pack())]
        refresh_row = [types.InlineKeyboardButton(text="🔄 Обновить", callback_data=BlacklistPageAction(page=1).pack())]
        empty_kb = types.InlineKeyboardMarkup(inline_keyboard=[add_row, refresh_row])
        await message.answer("Чёрный список пуст.", reply_markup=empty_kb)
        return
    kb = make_blacklist_list_page(bl, page=1)
    add_row = [types.InlineKeyboardButton(text="Добавить в чёрный список", callback_data=UserAction(action=UserAction.ActionType.ADD_TO_BLACKLIST, target_user_id=None).pack())]
    refresh_row = [types.InlineKeyboardButton(text="🔄 Обновить", callback_data=BlacklistPageAction(page=1).pack())]
    full_kb = types.InlineKeyboardMarkup(inline_keyboard=kb.inline_keyboard + [add_row, refresh_row])
    await message.answer("Чёрный список (стр. 1):", reply_markup=full_kb)

@admin_router.callback_query(UserAction.filter(F.action == UserAction.ActionType.SHOW_BLACKLIST))
async def show_blacklist_callback(callback: types.CallbackQuery):
    """Показывает чёрный список (страница 1) с пагинацией."""
    bl = db.get_blacklist()
    if not bl:
        if callback.message:
            add_row = [types.InlineKeyboardButton(text="Добавить в чёрный список", callback_data=UserAction(action=UserAction.ActionType.ADD_TO_BLACKLIST, target_user_id=None).pack())]
            refresh_row = [types.InlineKeyboardButton(text="🔄 Обновить", callback_data=BlacklistPageAction(page=1).pack())]
            empty_kb = types.InlineKeyboardMarkup(inline_keyboard=[add_row, refresh_row])
            await callback.message.answer("Чёрный список пуст.", reply_markup=empty_kb)
        await callback.answer()
        return
    kb = make_blacklist_list_page(bl, page=1)
    add_row = [types.InlineKeyboardButton(text="Добавить в чёрный список", callback_data=UserAction(action=UserAction.ActionType.ADD_TO_BLACKLIST, target_user_id=None).pack())]
    refresh_row = [types.InlineKeyboardButton(text="🔄 Обновить", callback_data=BlacklistPageAction(page=1).pack())]
    full_kb = types.InlineKeyboardMarkup(inline_keyboard=kb.inline_keyboard + [add_row, refresh_row])
    if callback.message:
        await callback.message.answer("Чёрный список (стр. 1):", reply_markup=full_kb)
    await callback.answer()

@admin_router.callback_query(BlacklistPageAction.filter())
async def paginate_blacklist_callback(callback: types.CallbackQuery, callback_data: BlacklistPageAction):
    """Обработка навигации по страницам чёрного списка."""
    bl = db.get_blacklist()
    page = callback_data.page
    if not callback.message:
        await callback.answer()
        return
    if not bl:
        try:
            add_row = [types.InlineKeyboardButton(text="Добавить в чёрный список", callback_data=UserAction(action=UserAction.ActionType.ADD_TO_BLACKLIST, target_user_id=None).pack())]
            refresh_row = [types.InlineKeyboardButton(text="🔄 Обновить", callback_data=BlacklistPageAction(page=page).pack())]
            empty_kb = types.InlineKeyboardMarkup(inline_keyboard=[add_row, refresh_row])
            await callback.message.edit_text("Чёрный список пуст.", reply_markup=empty_kb)
        except exceptions.TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                pass
            else:
                logging.exception("Failed to show empty blacklist")
                try:
                    await callback.message.answer("Чёрный список пуст.", reply_markup=empty_kb)
                except Exception:
                    logging.exception("Failed to send empty blacklist message")
        except Exception:
            logging.exception("Failed to show empty blacklist (unexpected)")
            try:
                await callback.message.answer("Чёрный список пуст.", reply_markup=empty_kb)
            except Exception:
                logging.exception("Failed to send empty blacklist message")
        await callback.answer()
        return
    kb = make_blacklist_list_page(bl, page=page)
    add_row = [types.InlineKeyboardButton(text="Добавить в чёрный список", callback_data=UserAction(action=UserAction.ActionType.ADD_TO_BLACKLIST, target_user_id=None).pack())]
    refresh_row = [types.InlineKeyboardButton(text="🔄 Обновить", callback_data=BlacklistPageAction(page=page).pack())]
    full_kb = types.InlineKeyboardMarkup(inline_keyboard=kb.inline_keyboard + [add_row, refresh_row])
    try:
        await callback.message.edit_text(f"Чёрный список (стр. {page}):", reply_markup=full_kb)
    except exceptions.TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            pass
        else:
            logging.exception("Failed to edit blacklist page; sending new message")
            try:
                await callback.message.answer(f"Чёрный список (стр. {page}):", reply_markup=full_kb)
            except Exception:
                logging.exception("Failed to send blacklist page message")
    except Exception:
        logging.exception("Failed to edit blacklist page (unexpected)")
        try:
            await callback.message.answer(f"Чёрный список (стр. {page}):", reply_markup=full_kb)
        except Exception:
            logging.exception("Failed to send blacklist page message")
    await callback.answer()

@admin_router.callback_query(UserAction.filter(F.action == UserAction.ActionType.ADD_TO_BLACKLIST))
async def add_to_blacklist_callback(callback: types.CallbackQuery, state: FSMContext):
    """Начинает процесс добавления пользователя в черный список"""

    await state.set_state(AdminStates.waiting_for_user_id_add_to_blacklist)
    await callback.message.answer("Введите ID пользователя, которого хотите добавить в чёрный список:", parse_mode=None)
    await callback.answer()

@admin_router.callback_query(UserAction.filter(F.action == UserAction.ActionType.REMOVE_FROM_BLACKLIST))
async def remove_from_blacklist_callback(callback: types.CallbackQuery, callback_data: UserAction, state: FSMContext):
    """Удаляет пользователя из черного списка"""

    if callback_data.target_user_id:
        db.reg_set_blacklisted(callback_data.target_user_id, False)
        db.reg_reset_attempts(callback_data.target_user_id)

        # Обновляем сообщение с кнопкой
        name = db.get_username(callback_data.target_user_id) or "Без имени"
        text = f"✅ {callback_data.target_user_id} — {name} удалён из чёрного списка"
        await callback.message.edit_text(text, reply_markup=None, parse_mode=None)
    else:
        await state.set_state(AdminStates.waiting_for_user_id_remove_from_blacklist)
        await callback.message.answer("Введите ID пользователя, которого хотите удалить из чёрного списка:")
    await callback.answer()

@admin_router.callback_query(UserAction.filter(F.action == UserAction.ActionType.SHOW_BLACKLIST_USER))
async def show_blacklisted_user_callback(callback: types.CallbackQuery, callback_data: UserAction):
    """Показывает карточку конкретного пользователя из чёрного списка с кнопкой удаления."""
    uid = callback_data.target_user_id
    if uid is None:
        await callback.answer("ID не найден", show_alert=True)
        return
    name = db.get_username(uid) or "Без имени"
    kb = make_remove_from_blacklist_keyboard(uid)
    if callback.message:
        await callback.message.answer(f"🚫 {uid}: {name}", reply_markup=kb)
    await callback.answer()

@admin_router.message(AdminStates.waiting_for_user_id_add_to_blacklist, IsAdmin())
async def process_add_to_blacklist(message: types.Message, state: FSMContext):
    """Обрабатывает добавление пользователя в черный список"""

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

@admin_router.message(AdminStates.waiting_for_user_id_remove_from_blacklist, IsAdmin())
async def process_remove_from_blacklist(message: types.Message, state: FSMContext):
    """Обрабатывает удаление пользователя из черного списка"""

    if not message.from_user:
        await state.clear()
        return

    try:
        target = int(message.text.strip() if message.text else "")
    except ValueError:
        await message.answer("Неверный ID пользователя. Введите число:")
        return

    db.reg_set_blacklisted(target, False)
    db.reg_reset_attempts(target)
    name = db.get_username(target) or "Без имени"
    await message.answer(f"Пользователь {target} ({name}) удалён из чёрного списка (если был).")
    await state.clear()


# ========== PASSWORD MANAGEMENT CALLBACKS ==========
# Callback'и для управления паролем

@admin_router.message(Command(BotCommands.PASSWORD_MENU.command), IsAdmin())
async def password_cmd(message: types.Message):
    """Показывает меню управления паролем для регистрации"""

    pwd = db.get_auth_password()
    if not pwd:
        await message.answer("Пароль не задан.", reply_markup=make_password_menu(has_password=False))
    else:
        await message.answer(f"Текущий пароль: `{pwd}`", parse_mode="Markdown", reply_markup=make_password_menu(has_password=True))

@admin_router.callback_query(PasswordAction.filter(F.action == PasswordAction.ActionType.CHANGE))
async def change_password_callback(callback: types.CallbackQuery, state: FSMContext):
    """Начинает процесс изменения пароля для регистрации"""

    await state.set_state(AdminStates.waiting_for_new_password)
    await callback.message.answer("Введите новый пароль для регистрации:", parse_mode=None)
    await callback.answer()

@admin_router.callback_query(PasswordAction.filter(F.action == PasswordAction.ActionType.DELETE))
async def delete_password_callback(callback: types.CallbackQuery):
    """Удаляет пароль для регистрации (открывает регистрацию для всех)"""

    db.set_auth_password(None)
    await callback.message.edit_text("Пароль удалён. Регистрация будет закрыта до установки пароля.", parse_mode=None)
    await callback.answer()

@admin_router.message(AdminStates.waiting_for_new_password, IsAdmin())
async def process_new_password(message: types.Message, state: FSMContext):
    """Обрабатывает установку нового пароля для регистрации"""

    new_password = message.text.strip() if message.text else ""
    if not new_password:
        await message.answer("Пароль не может быть пустым. Попробуйте ещё раз:")
        return

    db.set_auth_password(new_password)
    await message.answer("Пароль установлен.", parse_mode=None)

    await state.clear()


# ========== USER CRUD CALLBACKS ==========
# Callback'и для создания, чтения, обновления и удаления пользователей

@admin_router.message(AdminStates.waiting_for_user_id_add_admin, IsAdmin())
async def process_add_admin(message: types.Message, state: FSMContext):
    """Обрабатывает добавление пользователя в администраторы"""

    if not message.from_user:
        await state.clear()
        return

    try:
        new_id = int(message.text.strip() if message.text else "")
    except ValueError:
        await message.answer("Неверный ID пользователя. Введите число:")
        return

    user = db.get_user(new_id)
    if not user:
        await message.answer("Пользователь не найден. Сначала добавьте пользователя в систему.")
        await state.clear()
        return

    db.add_admin(new_id)
    # Setup admin commands for the new admin
    await setup_admin_commands(message.bot, new_id)
    await message.answer(f"Пользователь {new_id} добавлен в админы.", parse_mode=None)
    await state.clear()

@admin_router.message(AdminStates.waiting_for_user_id_del_admin, IsAdmin())
async def process_del_admin(message: types.Message, state: FSMContext):
    """Обрабатывает удаление пользователя из администраторов"""

    if not message.from_user:
        await state.clear()
        return

    try:
        user_id = int(message.text.strip() if message.text else "")
    except ValueError:
        await message.answer("Неверный ID пользователя. Введите число:")
        return

    if user_id == message.from_user.id:
        await message.answer("Нельзя удалить себя из админов.")
        await state.clear()
        return

    db.del_admin(user_id)
    # Reset commands to user level for the removed admin
    await reset_admin_commands(message.bot, user_id)
    await message.answer(f"Пользователь {user_id} удалён из админов (если был).")
    await state.clear()

@admin_router.message(AdminStates.waiting_for_user_id_del_user, IsAdmin())
async def process_del_user(message: types.Message, state: FSMContext):
    """Обрабатывает полное удаление пользователя из системы"""

    if not message.from_user:
        await state.clear()
        return

    try:
        user_id = int(message.text.strip() if message.text else "")
    except ValueError:
        await message.answer("Неверный ID пользователя. Введите число:")
        return

    db.remove_user(user_id)
    await message.answer(f"Пользователь {user_id} удалён (имя, заказы, роли).")
    await state.clear()

@admin_router.message(AdminStates.waiting_for_user_id_add_user, IsAdmin())
async def process_add_user(message: types.Message, state: FSMContext):
    """Обрабатывает добавление пользователя по ID (имя = ID по умолчанию)"""

    if not message.from_user:
        await state.clear()
        return

    try:
        user_id = int(message.text.strip() if message.text else "")
    except ValueError:
        await message.answer("Неверный ID пользователя. Введите число:")
        return

    # Если пользователь уже есть — не меняем роль, только убеждаемся что имя задано
    # Если нет — создаём с именем по умолчанию (строка ID)
    if not db.user_exists(user_id):
        db.add_user(user_id, "")
    else:
        db.set_username(user_id, "")
    await message.answer(f"Пользователь {user_id} добавлен.", parse_mode=None)
    await state.clear()

@admin_router.callback_query(UserAction.filter(F.action == UserAction.ActionType.DELETE))
async def delete_user_callback(callback: types.CallbackQuery, callback_data: UserAction):
    """Удаляет пользователя из системы (с подтверждением через кнопку)"""

    target_user_id = callback_data.target_user_id
    if target_user_id == callback.from_user.id:
        await callback.answer("Нельзя удалить себя", show_alert=True)
        return

    user = db.get_user(target_user_id)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    db.remove_user(target_user_id)
    await callback.message.edit_text(f"🗑️ Пользователь {user.name} (ID: {target_user_id}) удалён")
    await callback.answer("Пользователь удалён")



