#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from typing import Optional
from enum import Enum

from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, WebAppInfo,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters.callback_data import CallbackData
from aiogram import F
from aiogram.filters import or_f

from utils.commands import BotCommands
import db.orders_db as db

from utils.config import WEBAPP_URL

# ========== BASE CLASSES ==========

class BaseActionCallback:
    """
    Базовый класс для CallbackData, у которых есть поле `action` (Enum)
    """

    @classmethod
    def filter_action(cls, action: Enum):
        """Фильтр на конкретное действие"""
        return cls.filter(F.action == action)

    @classmethod
    def any(cls):
        """Фильтр на любое действие"""
        return cls.filter(F.action.is_not(None))

# ========== CALLBACK DATA CLASSES ==========

class OrderAction(CallbackData, BaseActionCallback, prefix="order"):
    class ActionType(Enum):
        INCREASE = "increase"
        DECREASE = "decrease"
        CANCEL = "cancel"
        DELETE_PAST = "deletepast"
        DONE = "done"
        DONE_PRODUCT = "done_product"

    @classmethod
    def adjust(cls):
        return or_f(cls.filter_action(OrderAction.ActionType.INCREASE), cls.filter_action(OrderAction.ActionType.DECREASE))

    action: ActionType
    product_id: int
    user_id: int | None = None


class UserAction(CallbackData, BaseActionCallback, prefix="user"):
    class ActionType(Enum):
        RENAME = "rename"
        SHOW = "show"
        ADD_USER = "add_user"
        ADD_TO_ADMINS = "add_admin"
        REMOVE_FROM_ADMINS = "remove_admin"
        SHOW_BLACKLISTED_USER = "show_blacklist_user"
        ADD_TO_BLACKLIST = "add_to_blacklist"
        REMOVE_FROM_BLACKLIST = "remove_from_blacklist"
        DELETE = "delete"

    action: ActionType
    target_user_id: Optional[int] = None


class PasswordAction(CallbackData, BaseActionCallback, prefix="password"):
    class ActionType(Enum):
        CHANGE = "change"
        DELETE = "delete"

    action: ActionType


class OrderTypeAction(CallbackData, BaseActionCallback, prefix="ordertype"):
    class ActionType(Enum):
        CURRENT = "current"
        PAST = "past"

    action: ActionType


class CollectionAction(CallbackData, BaseActionCallback, prefix="collection"):
    class ActionType(Enum):
        NEW = "new"
        CLOSE = "close"
        OPEN = "open"

    action: ActionType


class UpdateAction(CallbackData, BaseActionCallback, prefix="update"):
    class ActionType(Enum):
        DO_UPDATE = "do_update"

    action: ActionType


class OrdersViewAction(CallbackData, BaseActionCallback, prefix="ordersview"):
    class ActionType(Enum):
        BY_USER = "by_user"
        BY_PRODUCT = "by_product"

    action: ActionType


class UsersPageAction(CallbackData, prefix="userspage"):
    """Callback data for users list pagination."""
    page: int


class BlacklistPageAction(CallbackData, prefix="blpage"):
    """Callback data for blacklist pagination."""
    page: int


def get_main_keyboard_for(user_id: Optional[int] = None) -> ReplyKeyboardMarkup:
    """Формирует главную клавиатуру для пользователя"""
    base = []

    # Add WebApp button only when WEBAPP_URL configured; otherwise, omit it gracefully
    if WEBAPP_URL:
        base.append([KeyboardButton(text=BotCommands.OPEN_WEBAPP.button_text, web_app=WebAppInfo(url=WEBAPP_URL))])

    # Always include current/past order buttons
    base.append([KeyboardButton(text=BotCommands.ORDERS_CURRENT.button_text), KeyboardButton(text=BotCommands.ORDERS_PAST.button_text)])

    if user_id is not None and db.is_admin(user_id):
        if db.is_collecting():
            base.append([KeyboardButton(text=BotCommands.COLLECTION_CLOSE.button_text)])
        else:
            base.append([KeyboardButton(text=BotCommands.COLLECTION_NEW.button_text), 
                         KeyboardButton(text=BotCommands.COLLECTION_OPEN.button_text)])

        base.append([KeyboardButton(text=BotCommands.ADMIN_ORDERS_BY_USER.button_text), 
                     KeyboardButton(text=BotCommands.ADMIN_ORDERS_BY_PRODUCT.button_text)])
        base.append([KeyboardButton(text=BotCommands.ADMIN_HELP.button_text)])

    return ReplyKeyboardMarkup(keyboard=base, resize_keyboard=True)

def make_order_keyboard(owner_id: int, order: db.UserOrder, is_current: bool) -> Optional[InlineKeyboardMarkup]:
    """Create an InlineKeyboardMarkup for an order or return None when no buttons should be shown.
    Uses order.user_id when available (preferred), falling back to owner_id parameter.
    """
    if is_current and db.is_collecting() and not order.done:
        buttons = [
            InlineKeyboardButton(text="Увеличить ➕", callback_data=OrderAction(action=OrderAction.ActionType.INCREASE, product_id=order.product_id, user_id=order.user_id).pack())
        ]
        if order.count > 1:
            buttons.append(InlineKeyboardButton(text="Уменьшить ➖", callback_data=OrderAction(action=OrderAction.ActionType.DECREASE, product_id=order.product_id, user_id=order.user_id).pack()))
        buttons.append(InlineKeyboardButton(text="Отменить ❌", callback_data=OrderAction(action=OrderAction.ActionType.CANCEL, product_id=order.product_id, user_id=order.user_id).pack()))
        return InlineKeyboardMarkup(inline_keyboard=[buttons])
    if not is_current:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Удалить ❌", callback_data=OrderAction(action=OrderAction.ActionType.DELETE_PAST, product_id=order.product_id, user_id=order.user_id).pack())]
        ])
    return None

def make_order_done_keyboard(user_id: int, product_id: int, is_done: bool) -> Optional[InlineKeyboardMarkup]:
    """Create keyboard for marking individual order as done."""
    if db.is_collecting():
        return None
    if is_done:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отметить выполненным ✅", callback_data=OrderAction(action=OrderAction.ActionType.DONE, product_id=product_id, user_id=user_id).pack())]
    ])

def make_product_done_keyboard(product_id: int, all_done: bool) -> Optional[InlineKeyboardMarkup]:
    """Create keyboard for marking all orders of a product as done."""
    if db.is_collecting():
        return None
    if all_done:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отметить все выполненными ✅", callback_data=OrderAction(action=OrderAction.ActionType.DONE_PRODUCT, product_id=product_id).pack())]
    ])

def make_user_management_keyboard(user_id: int, is_admin: bool) -> InlineKeyboardMarkup:
    """Create keyboard for user management actions."""
    admin_button_text = "Удалить из админов ❌" if is_admin else "Сделать админом ⭐"
    admin_action = UserAction.ActionType.REMOVE_FROM_ADMINS if is_admin else UserAction.ActionType.ADD_TO_ADMINS
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Переименовать ✏️", callback_data=UserAction(action=UserAction.ActionType.RENAME, target_user_id=user_id).pack())],
        [InlineKeyboardButton(text=admin_button_text, callback_data=UserAction(action=admin_action, target_user_id=user_id).pack())],
        [InlineKeyboardButton(text="Удалить 🗑️", callback_data=UserAction(action=UserAction.ActionType.DELETE, target_user_id=user_id).pack())]
    ])

def make_password_management_keyboard(has_password: bool = False) -> InlineKeyboardMarkup:
    """Create keyboard for password management."""
    buttons = [[InlineKeyboardButton(text="Изменить пароль ✏️", callback_data=PasswordAction(action=PasswordAction.ActionType.CHANGE).pack())]]
    
    if has_password:
        buttons.append([InlineKeyboardButton(text="Удалить пароль 🗑️", callback_data=PasswordAction(action=PasswordAction.ActionType.DELETE).pack())])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Removed obsolete make_users_management_menu (unused)






def make_users_list_page(users: list[db.User], page: int, page_size: int = 10) -> InlineKeyboardMarkup:
    """Build paginated inline keyboard with users as buttons and ◀️/▶️ navigation.
    Each user button opens per-user management via UserAction.SHOW.
    """
    total = len(users)
    max_page = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, max_page))

    start = (page - 1) * page_size
    end = min(start + page_size, total)

    rows: list[list[InlineKeyboardButton]] = []
    for u in users[start:end]:
        status_icon = "⭐" if getattr(u, "is_admin", False) else "👤"
        name = (u.name or "Без имени") if hasattr(u, "name") else ""
        text = f"{status_icon} {u.user_id}: {name}"
        rows.append([
            InlineKeyboardButton(
                text=text,
                callback_data=UserAction(action=UserAction.ActionType.SHOW, target_user_id=u.user_id).pack(),
            )
        ])

    # Navigation row
    nav: list[InlineKeyboardButton] = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=UsersPageAction(page=page - 1).pack()))
    if page < max_page:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=UsersPageAction(page=page + 1).pack()))
    if nav:
        rows.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def make_users_list_with_menu_keyboard(users: list[db.User], page: int) -> InlineKeyboardMarkup:
    """Unified builder returning display text and keyboard for users list or empty state.
    """
    menu_kb = make_users_menu_keyboard(page=page)

    if not users:
        return menu_kb

    list_kb = make_users_list_page(users, page=page)
    list_kb.inline_keyboard.extend(menu_kb.inline_keyboard)
    return list_kb



def make_users_menu_keyboard(page: int = 1) -> InlineKeyboardMarkup:
    """Create keyboard with add user and refresh buttons for users list."""
    add_row = [InlineKeyboardButton(text="Добавить пользователя", callback_data=UserAction(action=UserAction.ActionType.ADD_USER).pack())]
    refresh_row = [InlineKeyboardButton(text="🔄 Обновить", callback_data=UsersPageAction(page=page).pack())]
    return InlineKeyboardMarkup(inline_keyboard=[add_row, refresh_row])






def make_blacklist_list_page(user_ids: list[int], page: int, page_size: int = 10) -> InlineKeyboardMarkup:
    """Build paginated inline keyboard for blacklist with remove buttons and navigation."""
    total = len(user_ids)
    max_page = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, max_page))

    start = (page - 1) * page_size
    end = min(start + page_size, total)

    rows: list[list[InlineKeyboardButton]] = []
    # Sort by name if available, else by user_id
    slice_ids = user_ids[:]
    # we'll only sort the full list before slicing to ensure stable pages
    def sort_key(uid: int):
        u = db.get_user(uid)
        return ((u.name or "") if u else "", uid)
    slice_ids.sort(key=sort_key)
    for uid in slice_ids[start:end]:
        u = db.get_user(uid)
        name = (u.name if u and u.name else "Без имени")
        text = f"🚫 {uid}: {name}"
        rows.append([
            InlineKeyboardButton(
                text=text,
                callback_data=UserAction(action=UserAction.ActionType.SHOW_BLACKLISTED_USER, target_user_id=uid).pack(),
            )
        ])

    # Navigation row
    nav: list[InlineKeyboardButton] = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=BlacklistPageAction(page=page - 1).pack()))
    if page < max_page:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=BlacklistPageAction(page=page + 1).pack()))
    if nav:
        rows.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=rows)


# Removed obsolete make_blacklist_management_menu (unused)


def make_blacklisted_user_management_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Create keyboard with remove from blacklist button for a specific user."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Убрать из чёрного списка", callback_data=UserAction(action=UserAction.ActionType.REMOVE_FROM_BLACKLIST, target_user_id=user_id).pack())]
    ])


def make_order_type_selection_keyboard() -> InlineKeyboardMarkup:
    """Create keyboard for selecting order type (current or past)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Текущие заказы", callback_data=OrderTypeAction(action=OrderTypeAction.ActionType.CURRENT).pack())],
        [InlineKeyboardButton(text="Прошлые заказы", callback_data=OrderTypeAction(action=OrderTypeAction.ActionType.PAST).pack())]
    ])


def make_collection_management_keyboard() -> InlineKeyboardMarkup:
    """Create keyboard for collection management (start/stop collection)."""
    buttons = []
    if db.is_collecting():
        buttons.append([InlineKeyboardButton(text="Закрыть сбор", callback_data=CollectionAction(action=CollectionAction.ActionType.CLOSE).pack())])
    else:
        buttons.append([InlineKeyboardButton(text="Новый сбор", callback_data=CollectionAction(action=CollectionAction.ActionType.NEW).pack()),
                        InlineKeyboardButton(text="Открыть сбор", callback_data=CollectionAction(action=CollectionAction.ActionType.OPEN).pack())])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def make_orders_view_keyboard() -> InlineKeyboardMarkup:
    """Create keyboard for selecting orders view type."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Все заказы по пользователям", callback_data=OrdersViewAction(action=OrdersViewAction.ActionType.BY_USER).pack())],
        [InlineKeyboardButton(text="Все заказы по товарам", callback_data=OrdersViewAction(action=OrdersViewAction.ActionType.BY_PRODUCT).pack())]
    ])



def make_blacklist_list_with_menu_keyboard(user_ids: list[int], page: int) -> InlineKeyboardMarkup:
    """Unified builder for blacklist list with menu buttons."""
    menu_kb = make_blacklist_menu_keyboard(page=page)

    if not user_ids:
        return menu_kb

    list_kb = make_blacklist_list_page(user_ids, page=page)
    list_kb.inline_keyboard.extend(menu_kb.inline_keyboard)
    return list_kb


def make_blacklist_menu_keyboard(page: int = 1) -> InlineKeyboardMarkup:
    """Create keyboard with add to blacklist and refresh buttons for blacklist."""
    add_row = [InlineKeyboardButton(text="Добавить в чёрный список", callback_data=UserAction(action=UserAction.ActionType.ADD_TO_BLACKLIST, target_user_id=None).pack())]
    refresh_row = [InlineKeyboardButton(text="🔄 Обновить", callback_data=BlacklistPageAction(page=page).pack())]
    return InlineKeyboardMarkup(inline_keyboard=[add_row, refresh_row])


def make_update_keyboard() -> InlineKeyboardMarkup:
    """Create keyboard for update confirmation."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Обновить ✅", callback_data=UpdateAction(action=UpdateAction.ActionType.DO_UPDATE).pack())]
    ])