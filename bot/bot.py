#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import json
import atexit
import time

from pathlib import Path
from typing import Optional, Tuple

from aiogram import exceptions
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, WebAppInfo,
    InlineKeyboardMarkup, InlineKeyboardButton
)

import logging
logging.basicConfig(level=logging.INFO)

# ========== CONFIG ==========
# config.py must define BOT_TOKEN (str), WEBAPP_URL (str), INITIAL_ADMIN (int or list[int])
from config import BOT_TOKEN, WEBAPP_URL, INITIAL_ADMIN

DATA_FILE = Path("data.json")

# ========== GLOBAL DATA (in-memory) ==========
DATA = None
DATA_DIRTY = False

# ========== DATA LAYER ==========
def load_data():
    """
    Load data once into global DATA. If file missing or corrupt, create defaults.
    """
    global DATA, INITIAL_ADMIN

    if DATA is None:
        if DATA_FILE.exists():
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    DATA = json.load(f)
            except Exception:
                logging.exception("Corrupt data.json, starting with empty dataset")
                DATA = {}
        else:
            DATA = {}

        # ensure required keys
        DATA.setdefault("users", [])        # list of {"user_id": int, "name": str, "is_admin": bool}
        DATA.setdefault("orders", [])       # list of {"user_id": int, "user_orders": [current orders], "old_user_orders": [past orders]}
        DATA.setdefault("orders_open", False)
        DATA.setdefault("auth_password", None)
        DATA.setdefault("blacklist", [])    # list of user_id ints
        DATA.setdefault("attempts", {})     # { user_id (int): n }

        # ensure user_orders and old_user_orders, migrate remove "current"
        for entry in DATA["orders"]:
            entry.setdefault("user_orders", [])
            entry.setdefault("old_user_orders", [])
            # migrate: remove "current" from all orders
            for order in entry["user_orders"] + entry["old_user_orders"]:
                if "current" in order:
                    del order["current"]

        # ensure INITIAL_ADMIN is present as admin
        if INITIAL_ADMIN is not None:
            if not isinstance(INITIAL_ADMIN, list):
                init_list = [INITIAL_ADMIN]
            else:
                init_list = INITIAL_ADMIN
            for a in init_list:
                try:
                    uid = int(a)
                except Exception:
                    continue
                found = False
                for entry in DATA["users"]:
                    if entry.get("user_id") == uid:
                        entry["is_admin"] = True
                        found = True
                        break
                if not found:
                    DATA["users"].append({"user_id": uid, "name": "", "is_admin": True})

    return DATA

def mark_dirty():
    global DATA_DIRTY
    DATA_DIRTY = True

def save_data(force: bool = False):
    """
    Save global DATA to disk only if dirty or force=True.
    """
    global DATA, DATA_DIRTY
    if DATA is None:
        return
    if DATA_DIRTY or force:
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(DATA, f, ensure_ascii=False, indent=2)
            DATA_DIRTY = False
            logging.info("Data saved to %s", DATA_FILE)
        except Exception as e:
            logging.exception("Error saving data: %s", e)

async def autosave_loop():
    """
    Background task to periodically save data.
    """
    while True:
        await asyncio.sleep(300)  # 5 minutes
        save_data()

atexit.register(lambda: save_data(force=True))

# ===== user helpers =====

def _get_users() -> list[dict]:
    """Возвращает список пользователей."""
    return load_data().setdefault("users", [])

def _find_user(user_id: int) -> Optional[dict]:
    """Находит запись пользователя по user_id."""
    return next((u for u in _get_users() if u.get("user_id") == user_id), None)

def is_admin(user_id: int) -> bool:
    user = _find_user(user_id)
    return bool(user and user.get("is_admin"))

def add_admin(user_id: int):
    user = _find_user(user_id)
    if user:
        if not user.get("is_admin"):
            user["is_admin"] = True
            mark_dirty()
    else:
        _get_users().append({"user_id": user_id, "name": str(user_id), "is_admin": True})
        mark_dirty()

def del_admin(user_id: int):
    user = _find_user(user_id)
    if user and user.get("is_admin"):
        user["is_admin"] = False
        mark_dirty()

def set_username(user_id: int, name: str):
    user = _find_user(user_id)
    if user:
        if user.get("name") != name:
            user["name"] = name
            mark_dirty()
    else:
        _get_users().append({"user_id": user_id, "name": name, "is_admin": False})
        mark_dirty()

def get_username(user_id: int) -> str:
    user = _find_user(user_id)
    return user.get("name") if user else str(user_id)

def user_exists(user_id: int) -> bool:
    return _find_user(user_id) is not None

def get_user_entry(user_id: int) -> Optional[dict]:
    return _find_user(user_id)

def remove_user(user_id: int):
    data = load_data()
    data["users"] = [u for u in data.get("users", []) if u.get("user_id") != user_id]
    data["orders"] = [o for o in data.get("orders", []) if o.get("user_id") != user_id]
    mark_dirty()


#===== order helpers =====

def _get_user_order_entry(user_id: int) -> Optional[dict]:
    """Возвращает запись заказов пользователя или None."""
    return next((e for e in load_data().setdefault("orders", []) if e.get("user_id") == user_id), None)

def _get_user_orders(user_id: int) -> list[dict]:
    """Возвращает список заказов пользователя."""
    entry = _get_user_order_entry(user_id)
    return entry.get("user_orders", []) if entry else []

def add_user_order(user_id: int, order: dict) -> dict:
    """
    Добавляет заказ пользователю.
    Если запись пользователя отсутствует — создаёт её.
    Если у пользователя уже есть такой товар в текущих заказах, то увеличивать количество.
    Возвращает добавленный или обновлённый заказ.
    """
    order.setdefault("done", False)
    data_orders = load_data().setdefault("orders", [])
    entry = _get_user_order_entry(user_id)
    
    if entry:
        user_orders = entry.setdefault("user_orders", [])
    else:
        user_orders = []
        data_orders.append({"user_id": user_id, "user_orders": user_orders, "old_user_orders": []})
    
    # Check if there's already a current order for this product_id
    product_id = order.get("product_id")
    existing_order = None
    for o in user_orders:
        if o.get("product_id") == product_id:
            existing_order = o
            break
    
    if existing_order:
        # Increase the count
        existing_count = existing_order.get("count", 1)
        new_count = order.get("count", 1)
        existing_order["count"] = existing_count + new_count
        mark_dirty()
        return existing_order
    else:
        # Add new order
        user_orders.append(order)
        mark_dirty()
        return order

def get_user_orders(user_id: int, is_current: bool) -> list[dict]:
    entry = _get_user_order_entry(user_id)
    if not entry:
        return []
    if is_current:
        return entry.get("user_orders", [])
    else:
        return entry.get("old_user_orders", [])

def get_user_order(user_id: int, product_id: int, is_current: bool) -> Tuple[Optional[dict], int]:
    """Возвращает пару (заказ, display_idx) или (None, 0) если не найден."""
    orders = get_user_orders(user_id, is_current)
    for idx, o in enumerate(orders):
        if o.get("product_id") == product_id:
            return o, idx + 1
    return None, 0

def update_user_order(user_id: int, product_id: int, updates: dict) -> bool:
    """
    Обновляет поля заказа конкретного пользователя по product_id.
    Возвращает True, если заказ найден и обновлён, иначе False.
    """
    orders = get_user_orders(user_id, True)
    for o in orders:
        if o.get("product_id") == product_id:
            o.update(updates)
            mark_dirty()
            return True
    return False

def remove_user_order(user_id: int, product_id: int, is_current: bool = True) -> bool:
    """
    Удаляет заказ конкретного пользователя по product_id.
    Возвращает True, если заказ найден и удалён.
    """
    orders = get_user_orders(user_id, is_current)
    for i, o in enumerate(orders):
        if o.get("product_id") == product_id:
            orders.pop(i)
            mark_dirty()
            return True
    return False

def get_all_orders_dict() -> list[dict]:
    """Возвращает все записи заказов всех пользователей."""
    return load_data().get("orders", [])


#===== collection state helpers =====

def set_collection_state(state: bool):
    data = load_data()
    data["orders_open"] = bool(state)
    mark_dirty()

def is_collecting() -> bool:
    return load_data().get("orders_open", False)

# ===== password helpers =====

def get_auth_password() -> Optional[str]:
    return load_data().get("auth_password")

def set_auth_password(pwd: Optional[str]):
    data = load_data()
    data["auth_password"] = pwd
    mark_dirty()

# ===== blacklist helpers =====

def is_blacklisted(user_id: int) -> bool:
    return user_id in load_data().get("blacklist", [])

def add_to_blacklist(user_id: int):
    data = load_data()
    if user_id not in data.get("blacklist", []):
        data["blacklist"].append(user_id)
        mark_dirty()

def remove_from_blacklist(user_id: int):
    data = load_data()
    if user_id in data.get("blacklist", []):
        data["blacklist"].remove(user_id)
        mark_dirty()


# ===== attempts helpers =====

def get_attempts(user_id: int) -> int:
    return load_data().get("attempts", {}).get(user_id, 0)

def inc_attempts(user_id: int) -> int:
    data = load_data()
    attempts = data.setdefault("attempts", {})
    cur = attempts.get(user_id, 0) + 1
    attempts[user_id] = cur
    mark_dirty()
    return cur

def reset_attempts(user_id: int):
    data = load_data()
    attempts = data.setdefault("attempts", {})
    if user_id in attempts:
        attempts.pop(user_id)
        mark_dirty()


# ========== BOT SETUP ==========
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML,
        link_preview_is_disabled=True,  
    ),
)
dp = Dispatcher()

# ========== FSM ==========
class UserRegistration(StatesGroup):
    waiting_for_name = State()
    waiting_for_password = State()

# ========== Keyboards ==========
def get_main_keyboard_for(user_id: Optional[int] = None) -> ReplyKeyboardMarkup:
    base = [
        [KeyboardButton(text="Открыть меню 🍔", web_app=WebAppInfo(url=WEBAPP_URL))],
        [KeyboardButton(text="Мои текущие заказы"), KeyboardButton(text="Мои прошлые заказы")],
    ]
    if user_id is not None and is_admin(user_id):
        # show only one start/stop admin button depending on state
        if is_collecting():
            base.append([KeyboardButton(text="Закрыть сбор заказов (админ)")])
        else:
            base.append([KeyboardButton(text="Начать сбор заказов (админ)")])
        base.append([KeyboardButton(text="Все заказы (админ)")])
    return ReplyKeyboardMarkup(keyboard=base, resize_keyboard=True)

# ========== START HANDLER ==========
@dp.message(Command("start"))
async def start_handler(message: types.Message, state: FSMContext):
    data = load_data()
    user_id = message.from_user.id

    # blacklist check
    if is_blacklisted(user_id):
        await message.answer("⛔ Вы заблокированы и не можете зарегистрироваться. Обратитесь к администратору.")
        return

    if not user_exists(user_id):
        # new user — ask name
        await message.answer("Привет! Как тебя зовут? Введи, пожалуйста, своё имя:")
        await state.set_state(UserRegistration.waiting_for_name)
        return
    # If user entry exists but has no name, ask for it
    entry = get_user_entry(user_id)
    if not entry or not entry.get("name") or str(entry.get("name")).strip() == "":
        await message.answer("Привет! Как тебя зовут? Введи, пожалуйста, своё имя:")
        await state.set_state(UserRegistration.waiting_for_name)
        return
    name = get_username(user_id)
    await message.answer(f"Привет, {name}! Выбери действие:", reply_markup=get_main_keyboard_for(user_id))

@dp.message(UserRegistration.waiting_for_name)
async def name_handler(message: types.Message, state: FSMContext):
    name = message.text.strip()
    user_id = message.from_user.id

    # if user is blacklisted, block
    if is_blacklisted(user_id):
        await message.answer("⛔ Вы заблокированы. Обратитесь к администратору.")
        await state.clear()
        return

    if is_admin(user_id):
        set_username(user_id, name)
        await message.answer(f"✅ Регистрация успешна. Приятно познакомиться, Администратор {name}!", reply_markup=get_main_keyboard_for(user_id))
        await state.clear()
    else:
        # store temporary name in state and ask password
        await state.update_data(candidate_name=name)
        await message.answer("Введите пароль для регистрации (у вас 3 попытки):")
        await state.set_state(UserRegistration.waiting_for_password)

@dp.message(UserRegistration.waiting_for_password)
async def password_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data_state = await state.get_data()
    name = data_state.get("candidate_name", message.from_user.full_name or str(user_id))
    entered = message.text.strip()

    # get current auth password
    pwd = get_auth_password()
    if pwd is None:
        # no password set by admin -> deny registration (or allow auto? here deny)
        await message.answer("Регистрация временно закрыта — пароль не настроен. Обратитесь к администратору.")
        await state.clear()
        return

    if entered == pwd:
        # success
        set_username(user_id, name)
        reset_attempts(user_id)
        await message.answer(f"✅ Регистрация успешна. Приятно познакомиться, {name}!", reply_markup=get_main_keyboard_for(user_id))
        await state.clear()
    else:
        # fail
        attempts = inc_attempts(user_id)
        remaining = max(0, 3 - attempts)
        if attempts >= 3:
            add_to_blacklist(user_id)
            await message.answer("⛔ Слишком много неверных попыток. Вы добавлены в чёрный список.")
            await state.clear()
        else:
            await message.answer(f"Неверный пароль. Осталось попыток: {remaining}. Попробуйте ещё раз.")

# ========== ORDER TEXT / SENDER ==========
def make_order_text(user_id: int, display_idx: Optional[int], order: dict, is_current: bool) -> str:
    name = get_username(user_id)
    status = "✅ Выполнен" if order.get("done") else ("⏳ Текущий" if is_current else "📦 Прошлый")
    title = order.get("title", "")
    price = order.get("price", "")
    count = order.get("count", 1)
    link = order.get("link", "")
    idx_part = f"#{display_idx}" if display_idx is not None else ""
    text = (
        f"<b>{name}</b> — заказ {idx_part}:\n"
        f"{title} - <b>{price} ₽</b>\n"
        f"Количество: <b>{count}</b>\n"
        f"Ссылка: {link}\n"
        f"Статус: {status}"
    )
    return text


def make_order_keyboard(owner_id: int, order: dict, is_current: bool) -> Optional[InlineKeyboardMarkup]:
    """Create an InlineKeyboardMarkup for an order or return None when no buttons should be shown.

    Buttons are shown only for current orders while collection is open.
    For past orders a single delete button is shown.
    """
    product_id = order.get("product_id", "")
    if is_current and is_collecting():
        buttons = [
            InlineKeyboardButton(text="Увеличить ➕", callback_data=f"increase:{owner_id}:{product_id}")
        ]
        if order.get("count", 1) > 1:
            buttons.append(InlineKeyboardButton(text="Уменьшить ➖", callback_data=f"decrease:{owner_id}:{product_id}"))
        buttons.append(InlineKeyboardButton(text="Отменить ❌", callback_data=f"cancel:{owner_id}:{product_id}"))
        return InlineKeyboardMarkup(inline_keyboard=[buttons])
    if not is_current:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Удалить ❌", callback_data=f"deletepast:{owner_id}:{product_id}")]
        ])
    return None

async def send_order_message(owner_id: int, order: dict, to_user: Optional[int] = None, display_idx: Optional[int] = None, is_current: bool = True):
    text = make_order_text(owner_id, display_idx, order, is_current)
    keyboard = make_order_keyboard(owner_id, order, is_current)

    target = owner_id if to_user is None else to_user
    try:
        # reply_markup accepts None
        await bot.send_message(int(target), text, reply_markup=keyboard)
    except Exception:
        logging.exception("Failed to send order message to %s", target)

# =========== ORDER TOTAL ==========

def get_orders_total(orders: list) -> int:
    """Возвращает сумму по переданному списку заказов"""
    return sum(int(o.get("price", 0)) * int(o.get("count", 1)) for o in orders)

async def send_updated_total(owner_id: int, is_current: bool = True):
    """Отправляет пользователю обновленную сумму по заказам."""
    orders = get_user_orders(owner_id, is_current=is_current)
    await send_total_message(owner_id, orders, is_current)

async def update_order_count(owner_id: int, product_id_int: int, is_increase: bool) -> tuple[bool, int]:
    order, _ = get_user_order(owner_id, product_id_int, is_current=True)
    if not order:
        return False, 0
    delta = 1 if is_increase else -1
    new_count = order.get("count", 1) + delta
    if new_count < 1:
        return False, order.get("count", 1)
    order["count"] = new_count
    update_user_order(owner_id, product_id_int, {"count": new_count})
    return True, new_count

async def send_total_message(user_id: int, orders: list, is_current: bool):
    """Отправляет сообщение с суммой заказов."""
    total = get_orders_total(orders)
    label = "текущим" if is_current else "прошлым"
    text = f"💰 <b>Итого по {label} заказам: {total} ₽</b>"
    await bot.send_message(user_id, text)

# ========== WEBAPP HANDLER ==========
@dp.message(lambda m: m.web_app_data is not None)
async def webapp_data_handler(message: types.Message):
    user_id = message.from_user.id

    # ensure registered
    if not user_exists(user_id):
        await message.answer("Вы не зарегистрированы. Нажмите /start чтобы зарегистрироваться.")
        return

    # check collecting flag
    if not is_collecting():
        await message.answer(
            "⛔ Сбор заказов сейчас закрыт. К сожалению, ваш заказ не был принят. Следите за объявлениями в боте."
        )
        return

    try:
        data = json.loads(message.web_app_data.data)
    except Exception:
        await message.answer("Неверные данные из WebApp. Заказ не принят.")
        return

    order = {
        # product_id and price are stored as integers (remove backward compatibility)
        "product_id": int(data.get("product_id", -1)),
        "title": data.get("title", ""),
        "price": int(data.get("price", 0) or 0),
        "count": int(data.get("count", 1) or 1),
        "link": data.get("link", ""),
        "done": False
    }

    added_order = add_user_order(user_id, order)

    all_orders = get_user_orders(user_id, True)
    # send owner the created order message and compute display index via enumerate
    for idx, o in enumerate(all_orders):
        if o.get("product_id") == added_order.get("product_id"):
            await send_order_message(user_id, added_order, display_idx=idx+1, is_current=True)
            break
    # show confirmation and the user's total for current orders

    await message.answer("✅ Заказ успешно добавлен.")
    await send_total_message(user_id, all_orders, True)

# ========== USER VIEWS ==========
@dp.message(Command("my_current"))
@dp.message(F.text == "Мои текущие заказы")
async def my_current_handler(message: types.Message):
    user_id = message.from_user.id
    current_orders = get_user_orders(user_id, True)
    if not current_orders:
        await message.answer("У вас нет текущих заказов.", reply_markup=get_main_keyboard_for(user_id))
        return
    for idx, order in enumerate(current_orders):
        await send_order_message(user_id, order, display_idx=idx+1, is_current=True)
    # show total for current orders
    await send_total_message(user_id, current_orders, True)

@dp.message(Command("my_past"))
@dp.message(F.text == "Мои прошлые заказы")
async def my_past_handler(message: types.Message):
    user_id = message.from_user.id
    past_orders = get_user_orders(user_id, False)
    if not past_orders:
        await message.answer("У вас нет прошлых заказов.", reply_markup=get_main_keyboard_for(user_id))
        return
    for idx, order in enumerate(past_orders):
        await send_order_message(user_id, order, display_idx=idx+1, is_current=False)
    await send_total_message(user_id, past_orders, False)

# ========== ADMIN: start/close collection & all current orders ==========


async def broadcast_to_all_users(bot: Bot, text: str):
    data = load_data()
    for entry in data.get("users", []):
        user_id = entry.get("user_id")
        await bot.send_message(user_id, text)


@dp.message(Command("start_collection"))
@dp.message(F.text == "Начать сбор заказов (админ)")
async def start_collection_handler(message: types.Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.answer("У вас нет прав для этой команды.")
        return

    data = load_data()
    # mark existing orders as past (move user_orders to old_user_orders)
    for entry in data.get("orders", []):
        entry["old_user_orders"] = entry.get("user_orders", [])
        entry["user_orders"] = []
    data["orders_open"] = True
    mark_dirty()

    await broadcast_to_all_users(bot, "🎉 Сбор заказов открыт! Можно отправлять новые заказы.")
    await message.answer("Сбор заказов открыт и всем пользователям отправлено уведомление.", reply_markup=get_main_keyboard_for(user_id))

@dp.message(Command("close_collection"))
@dp.message(F.text == "Закрыть сбор заказов (админ)")
async def close_collection_handler(message: types.Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.answer("У вас нет прав для этой команды.")
        return

    set_collection_state(False)
    await broadcast_to_all_users(bot, "⛔ Сбор заказов закрыт. Спасибо за заявки.")
    await message.answer("Сбор заказов закрыт и уведомления отправлены.", reply_markup=get_main_keyboard_for(user_id))

@dp.message(Command("all_orders"))
@dp.message(F.text == "Все заказы (админ)")
async def all_orders_handler(message: types.Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.answer("У вас нет прав для этой команды.")
        return

    all_orders = get_all_orders_dict()
    any_current = False
    # all_orders is a list of entries: {"user_id": int, "user_orders": [...]}
    for entry in all_orders:
        user_id = entry.get("user_id") if isinstance(entry, dict) else None
        if user_id is None:
            continue
        display_idx = 0
        for order in entry.get("user_orders", []):
            display_idx += 1
            any_current = True
            text = make_order_text(int(user_id), display_idx, order, is_current=True)
            product_id = order.get("product_id", "")
            keyboard = InlineKeyboardMarkup(inline_keyboard=[])
            if not order.get("done"):
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Отметить выполненным ✅", callback_data=f"done:{user_id}:{product_id}")]
                ])
            await message.answer(text, reply_markup=keyboard)

    if not any_current:
        await message.answer("Нет текущих заказов.", reply_markup=get_main_keyboard_for(user_id))

# ========== CALLBACKS ==========
@dp.callback_query()
async def cb_handler(callback: types.CallbackQuery):
    data = callback.data or ""
    parts = data.split(":", 2)
    if len(parts) != 3:
        await callback.answer()
        return
    action, owner_str, product_id_str = parts
    try:
        owner_id = int(owner_str)
    except Exception:
        await callback.answer("Неверные данные", show_alert=True)
        return
    # locate the order object and compute its index among the appropriate
    # set (current or past). Indexing for current and past orders is separate.
    # product_id from callback is expected to be integer (no backward compatibility)
    try:
        product_id_int = int(product_id_str)
    except Exception:
        await callback.answer("Неверный идентификатор заказа", show_alert=True)
        return

    #изменять можно только текущие заказы
    is_current = action in ("cancel", "increase", "decrease", "done")

    order, display_idx = get_user_order(owner_id, product_id_int, is_current=is_current)
    if order is None:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    # Cancel: owner or admin
    if action == "cancel":
        requester = callback.from_user.id
        if requester != owner_id and not is_admin(requester):
            await callback.answer("Нельзя отменить чужой заказ", show_alert=True)
            return
        if order.get("done"):
            await callback.answer("Нельзя отменить выполненный заказ", show_alert=True)
            return
        removed = remove_user_order(owner_id, product_id_int, is_current=True)
        if removed:
            if callback.message and hasattr(callback.message, "edit_text"):
                try:
                    await callback.message.edit_text(f"{get_username(owner_id)} — заказ #{display_idx} отменён ✅")
                except Exception:
                    logging.exception("Failed to edit callback message after cancel")
            await callback.answer("Заказ отменён")
            await send_updated_total(owner_id, is_current=True)
        else:
            await callback.answer("Не удалось отменить заказ", show_alert=True)

    # Done: admin only
    elif action == "done":
        requester = callback.from_user.id
        if not is_admin(requester):
            await callback.answer("Только админ может отмечать заказ выполненным", show_alert=True)
            return
        order["done"] = True
        # update stored order by its UID
        update_user_order(owner_id, product_id_int, {"done": True})
        if callback.message and hasattr(callback.message, "edit_text"):
            try:
                await callback.message.edit_text(f"{get_username(owner_id)} — заказ #{display_idx} отмечен как выполненный ✅")
            except Exception:
                logging.exception("Failed to edit callback message after marking done")
        await callback.answer("Заказ отмечен как выполненный")

    # delete past: owner only
    elif action == "deletepast":
        requester = callback.from_user.id
        if requester != owner_id:
            await callback.answer("Нельзя удалять чужую запись", show_alert=True)
            return
        removed = remove_user_order(owner_id, product_id_int, is_current=False)
        if removed:
            if callback.message and hasattr(callback.message, "edit_text"):
                try:
                    await callback.message.edit_text(f"{get_username(owner_id)} — прошлый заказ #{display_idx} удалён ❌")
                except Exception:
                    logging.exception("Failed to edit callback message after deletepast")
            await callback.answer("Заказ удалён")
            await send_updated_total(owner_id, is_current=False)
        else:
            await callback.answer("Не удалось удалить заказ", show_alert=True)

    # increase/decrease count: owner only
    elif action in ("increase", "decrease"):
        if not is_collecting():
            await callback.answer("Сбор заказов закрыт, изменения невозможны.", show_alert=True)
            return
        requester = callback.from_user.id
        if requester != owner_id:
            await callback.answer("Нельзя изменять чужой заказ", show_alert=True)
            return
        is_increase = action == "increase"
        success, new_count = await update_order_count(owner_id, product_id_int, is_increase)
        if success:
            text = make_order_text(owner_id, display_idx, order, is_current)
            keyboard = make_order_keyboard(owner_id, order, is_current)
            if callback.message and hasattr(callback.message, "edit_text"):
                try:
                    await callback.message.edit_text(text, reply_markup=keyboard)
                except Exception:
                    logging.exception(f"Failed to edit message after {action}")
            action_text = "увеличено" if is_increase else "уменьшено"
            await callback.answer(f"Количество {action_text}")
            await send_updated_total(owner_id, is_current=True)
        else:
            error_text = "Не удалось увеличить" if is_increase else "Нельзя уменьшить до 0"
            await callback.answer(error_text, show_alert=True)

    else:
        await callback.answer()

# ========== ADMIN UTILITIES ==========
@dp.message(Command("add_admin"))
async def add_admin_cmd(message: types.Message):
    caller = message.from_user.id
    if not is_admin(caller):
        await message.answer("У вас нет прав добавлять админов.")
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Использование: /add_admin <user_id>", parse_mode=None)
        return
    try:
        new_id = int(parts[1])
    except Exception:
        await message.answer("Неверный user_id")
        return
    add_admin(new_id)
    await message.answer(f"Пользователь {new_id} добавлен в админы.")

@dp.message(Command("del_admin"))
async def del_admin_cmd(message: types.Message):
    caller = message.from_user.id
    if not is_admin(caller):
        await message.answer("У вас нет прав удалять админов.")
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Использование: /del_admin <user_id>", parse_mode=None)
        return
    try:
        target = int(parts[1])
    except Exception:
        await message.answer("Неверный user_id")
        return
    if target == caller:
        await message.answer("Нельзя удалить себя из админов.")
        return
    del_admin(target)
    await message.answer(f"Пользователь {target} удалён из админов (если был).")

@dp.message(Command("del_user"))
async def del_user_cmd(message: types.Message):
    caller = message.from_user.id
    if not is_admin(caller):
        await message.answer("У вас нет прав удалять пользователей.")
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Использование: /del_user <user_id>", parse_mode=None)
        return
    try:
        target = int(parts[1])
    except Exception:
        await message.answer("Неверный user_id")
        return
    remove_user(target)
    await message.answer(f"Пользователь {target} удалён (имя, заказы, роли).")

@dp.message(Command("rename_user"))
async def rename_user_cmd(message: types.Message):
    caller = message.from_user.id
    if not is_admin(caller):
        await message.answer("У вас нет прав переименовывать пользователей.")
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Использование: /rename_user <user_id> <новое_имя>", parse_mode=None)
        return
    try:
        target = int(parts[1])
    except Exception:
        await message.answer("Неверный user_id")
        return
    new_name = parts[2].strip()
    set_username(target, new_name)
    await message.answer(f"Имя пользователя {target} изменено на: {new_name}")

@dp.message(Command("list_users"))
async def list_users_cmd(message: types.Message):
    caller = message.from_user.id
    if not is_admin(caller):
        await message.answer("У вас нет прав смотреть список пользователей.")
        return
    data = load_data()
    users = data.get("users", [])
    if not users:
        await message.answer("Пользователей пока нет.")
        return
    lines = []
    for entry in users:
        if isinstance(entry, dict):
            user_id = int(entry.get("user_id", 0))
            flag = "⭐" if entry.get("is_admin") else ""
            name = entry.get("name", str(user_id))
        else:
            # legacy string entry
            try:
                user_id = int(entry)
            except Exception:
                user_id = 0
            flag = ""
            name = str(entry)
        lines.append(f"{user_id}: {name} {flag}")
    await message.answer("Список пользователей:\n" + "\n".join(lines))

# ========== PASSWORD & BLACKLIST ADMIN ==========
@dp.message(Command("password_set"))
async def password_set_cmd(message: types.Message):
    caller = message.from_user.id
    if not is_admin(caller):
        await message.answer("У вас нет прав менять пароль.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Использование: /password_set <password> (пустая строка удалит пароль)", parse_mode=None)
        return
    new_pwd = parts[1].strip()
    if new_pwd == "":
        set_auth_password(None)
        await message.answer("Пароль удалён. Регистрация будет закрыта до установки пароля.")
    else:
        set_auth_password(new_pwd)
        await message.answer("Пароль установлен.")

@dp.message(Command("password"))
async def password_cmd(message: types.Message):
    caller = message.from_user.id
    if not is_admin(caller):
        await message.answer("У вас нет прав просматривать пароль.")
        return
    pwd = get_auth_password()
    if not pwd:
        await message.answer("Пароль не задан.")
    else:
        # show full password
        await message.answer(f"Текущий пароль: {pwd}\n(админ может /password_set чтобы изменить)")

@dp.message(Command("users_blacklist"))
async def users_blacklist_cmd(message: types.Message):
    caller = message.from_user.id
    if not is_admin(caller):
        await message.answer("У вас нет прав.")
        return
    data = load_data()
    bl = data.get("blacklist", [])
    if not bl:
        await message.answer("Чёрный список пуст.")
        return
    lines = []
    for user_id in bl:
        name = get_username(user_id)
        lines.append(f"{user_id} — {name}")
    await message.answer("Чёрный список:\n" + "\n".join(lines))

@dp.message(Command("users_remove_blacklist"))
async def users_remove_blacklist_cmd(message: types.Message):
    caller = message.from_user.id
    if not is_admin(caller):
        await message.answer("У вас нет прав.")
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Использование: /users_remove_blacklist <user_id>", parse_mode=None)
        return
    try:
        target = int(parts[1])
    except Exception:
        await message.answer("Неверный user_id")
        return
    remove_from_blacklist(target)
    reset_attempts(target)
    await message.answer(f"Пользователь {target} удалён из чёрного списка (если был).")

# ========== HELP ==========

@dp.message(Command("help"))
async def help_handler(message: types.Message):
    """
    /help — показывает справку. Для админов — расширенный список команд.
    """
    user_id = message.from_user.id

    user_help = (
        "📘 Помощь — пользователь:\n\n"
        "/start — начать / зарегистрироваться (ввести имя и пароль при первой регистрации)\n"
        "Кнопка в клавиатуре: «Открыть меню 🍔» — открыть WebApp с меню\n\n"
        "После выбора товара в WebApp нажмите «Заказать» — бот получит данные о товаре.\n\n"
        "Команды для пользователя:\n"
        "/my_current — Мои текущие заказы (можно отменить, если не выполнены)\n"
        "/my_past — Мои прошлые (архивные) заказы (можно удалить)\n\n"
        "Примечания:\n"
        "- При регистрации у вас есть 3 попытки ввести пароль. После 3 неверных попыток вы автоматически попадёте в чёрный список.\n"
        "- Если сбор заказов закрыт, попытки заказать не принимаются.\n"
        "- Вопросы и проблемы — пишите администратору."
    )

    admin_help = (
        "🔧 Помощь — администратор:\n\n"
        "Команды управления пользователями и паролем:\n"
        "/password_set <pwd> — установить общий пароль для регистрации (пустая строка удаляет пароль)\n"
        "/password — показать маску текущего пароля (полный пароль не показывается в чате)\n"
        "/add_admin <user_id> — добавить администратора\n"
        "/del_admin <user_id> — удалить администратора\n"
        "/del_user <user_id> — удалить пользователя (имя, заказы, роль)\n"
        "/rename_user <user_id> <new_name> — изменить имя пользователя\n"
        "/list_users — показать список пользователей (id, имя, отметка администратора)\n\n"
        "Чёрный список:\n"
        "/users_blacklist — показать чёрный список\n"
        "/users_remove_blacklist <user_id> — удалить пользователя из чёрного списка\n\n"
        "Сбор заказов:\n"
        "/start_collection — начать сбор заказов (все старые заказы пометятся как прошлые)\n"
        "/close_collection — закрыть сбор заказов\n"
        "Кнопки в клавиатуре: «Начать/Закрыть сбор заказов (админ)», «Все заказы (админ)»\n\n"
        "Работа с заказами:\n"
        "/all_orders — показать все ТЕКУЩИЕ заказы (админ видит текущие заказы всех пользователей)\n"
        "В сообщениях заказов админ может пометить заказ как выполненный (кнопка «Выполнен ✅»).\n\n"
        "Прочее:\n"
        "- После добавления/закрытия сбора бот рассылает уведомление всем зарегистрированным пользователям.\n"
        "- Данные сохраняются регулярно; изменения, требующие вмешательства (пароль, чёрный список), применяются сразу.\n"
    )

    if is_admin(user_id):
        await message.answer(admin_help, parse_mode=None)
    else:
        await message.answer(user_help)

# ========== START ==========

async def safe_start_polling(dp, bot, retries=5, delay=10):
    """
    Запускаем polling с обработкой ошибок сети.
    Если сеть недоступна — повторяем попытку `retries` раз с задержкой `delay` секунд.
    """
    attempt = 0
    while attempt < retries:
        try:
            logging.info(f"Polling attempt {attempt+1}/{retries}...")
            await dp.start_polling(bot)
            break  # если polling завершился нормально, выходим
        except exceptions.TelegramNetworkError as e:
            attempt += 1
            logging.warning(f"Network error: {e}. Попытка {attempt}/{retries} через {delay}s")
            await asyncio.sleep(delay)
        except Exception as e:
            logging.exception(f"Неожиданная ошибка: {e}")
            # можно решать: break или continue
            await asyncio.sleep(delay)
    else:
        logging.error("Все попытки подключения к Telegram API исчерпаны. Бот не запущен.")

async def main():
    # load data into memory
    load_data()
    # start autosave loop
    asyncio.create_task(autosave_loop())
#    print("Bot starting...")
#    await dp.start_polling(bot)
    logging.info("Bot starting...")
    await safe_start_polling(dp, bot)

if __name__ == "__main__":
    asyncio.run(main())
