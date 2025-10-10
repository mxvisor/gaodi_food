#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import json
import atexit
from pathlib import Path
from typing import Optional

from aiogram import exceptions
from aiogram import Bot, Dispatcher, types, F
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
from config import BOT_TOKEN, WEBAPP_URL, INITIAL_ADMIN  # config.py must provide these keys

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
                DATA = {}
        else:
            DATA = {}

        # ensure required keys
        DATA.setdefault("orders", {})      # { "user_id": [order,...], ... }
        DATA.setdefault("admins", INITIAL_ADMIN if isinstance(INITIAL_ADMIN, list) else [INITIAL_ADMIN])
        DATA.setdefault("users", {})       # { "user_id": "Name" }
        DATA.setdefault("orders_open", False)
        DATA.setdefault("auth_password", None)   # shared password (string) or None
        DATA.setdefault("blacklist", [])        # list of user ids (ints) blocked
        DATA.setdefault("attempts", {})         # per-user attempt counters { "user_id": n }
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

# Helper functions that operate on DATA and call mark_dirty when mutating
def is_admin(user_id: int) -> bool:
    data = load_data()
    return user_id in data.get("admins", [])

def add_admin(user_id: int):
    data = load_data()
    if user_id not in data["admins"]:
        data["admins"].append(user_id)
        mark_dirty()

def del_admin(user_id: int):
    data = load_data()
    if user_id in data["admins"]:
        data["admins"].remove(user_id)
        mark_dirty()

def set_username(user_id: int, name: str):
    data = load_data()
    data["users"][str(user_id)] = name
    mark_dirty()

def get_username(user_id: int) -> str:
    data = load_data()
    return data["users"].get(str(user_id), str(user_id))

def set_collection_state(state: bool):
    data = load_data()
    data["orders_open"] = bool(state)
    mark_dirty()

def is_collecting() -> bool:
    return load_data().get("orders_open", False)

def add_order(user_id: int, order: dict):
    data = load_data()
    order.setdefault("done", False)
    order["current"] = bool(is_collecting())
    data["orders"].setdefault(str(user_id), []).append(order)
    mark_dirty()

def get_user_orders_all(user_id: int) -> list:
    data = load_data()
    return data["orders"].get(str(user_id), [])

def update_order(user_id: int, idx: int, order: dict):
    data = load_data()
    arr = data["orders"].get(str(user_id), [])
    if 0 <= idx < len(arr):
        arr[idx] = order
        mark_dirty()

def remove_order(user_id: int, idx: int):
    data = load_data()
    arr = data["orders"].get(str(user_id), [])
    if 0 <= idx < len(arr):
        arr.pop(idx)
        mark_dirty()

def remove_user(user_id: int):
    data = load_data()
    data["users"].pop(str(user_id), None)
    data["orders"].pop(str(user_id), None)
    if user_id in data["admins"]:
        data["admins"].remove(user_id)
    mark_dirty()

def get_all_orders_dict():
    return load_data().get("orders", {})

# ===== password & blacklist helpers =====
def get_auth_password() -> Optional[str]:
    return load_data().get("auth_password")

def set_auth_password(pwd: Optional[str]):
    data = load_data()
    data["auth_password"] = pwd
    mark_dirty()

def is_blacklisted(user_id: int) -> bool:
    data = load_data()
    return int(user_id) in data.get("blacklist", [])

def add_to_blacklist(user_id: int):
    data = load_data()
    if int(user_id) not in data.get("blacklist", []):
        data["blacklist"].append(int(user_id))
        mark_dirty()

def remove_from_blacklist(user_id: int):
    data = load_data()
    if int(user_id) in data.get("blacklist", []):
        data["blacklist"].remove(int(user_id))
        mark_dirty()

def get_attempts(user_id: int) -> int:
    data = load_data()
    return int(data.get("attempts", {}).get(str(user_id), 0))

def inc_attempts(user_id: int) -> int:
    data = load_data()
    attempts = data.setdefault("attempts", {})
    cur = int(attempts.get(str(user_id), 0))
    cur += 1
    attempts[str(user_id)] = cur
    mark_dirty()
    return cur

def reset_attempts(user_id: int):
    data = load_data()
    attempts = data.setdefault("attempts", {})
    if str(user_id) in attempts:
        attempts.pop(str(user_id))
        mark_dirty()

async def broadcast_to_all_users(bot: Bot, text: str):
    data = load_data()
    users = list(data.get("users", {}).keys())
    for uid_str in users:
        try:
            await bot.send_message(int(uid_str), text, disable_web_page_preview=True)
        except Exception:
            # ignore delivery errors
            continue

# ========== BOT SETUP ==========
bot = Bot(token=BOT_TOKEN)
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
    uid = message.from_user.id

    # blacklist check
    if is_blacklisted(uid):
        await message.answer("⛔ Вы заблокированы и не можете зарегистрироваться. Обратитесь к администратору.")
        return

    if str(uid) not in data["users"]:
        # new user — ask name
        await message.answer("Привет! Как тебя зовут? Введи, пожалуйста, своё имя:")
        await state.set_state(UserRegistration.waiting_for_name)
        return
    name = data["users"].get(str(uid))
    await message.answer(f"Привет, {name}! Выбери действие:", reply_markup=get_main_keyboard_for(uid))

@dp.message(UserRegistration.waiting_for_name)
async def name_handler(message: types.Message, state: FSMContext):
    name = message.text.strip()
    uid = message.from_user.id

    # if user is blacklisted, block
    if is_blacklisted(uid):
        await message.answer("⛔ Вы заблокированы. Обратитесь к администратору.")
        await state.clear()
        return

    if is_admin(uid):
        set_username(uid, name)
        await message.answer(f"✅ Регистрация успешна. Приятно познакомиться, Администратор {name}!", reply_markup=get_main_keyboard_for(uid))
        await state.clear()
    else:
        # store temporary name in state and ask password
        await state.update_data(candidate_name=name)
        await message.answer("Введите пароль для регистрации (у вас 3 попытки):")
        await state.set_state(UserRegistration.waiting_for_password)

@dp.message(UserRegistration.waiting_for_password)
async def password_handler(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    data_state = await state.get_data()
    name = data_state.get("candidate_name", message.from_user.full_name or str(uid))
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
        set_username(uid, name)
        reset_attempts(uid)
        await message.answer(f"✅ Регистрация успешна. Приятно познакомиться, {name}!", reply_markup=get_main_keyboard_for(uid))
        await state.clear()
    else:
        # fail
        attempts = inc_attempts(uid)
        remaining = max(0, 3 - attempts)
        if attempts >= 3:
            add_to_blacklist(uid)
            await message.answer("⛔ Слишком много неверных попыток. Вы добавлены в чёрный список.")
            await state.clear()
        else:
            await message.answer(f"Неверный пароль. Осталось попыток: {remaining}. Попробуйте ещё раз.")

# ========== ORDER TEXT / SENDER ==========
def make_order_text(uid: int, idx: int, order: dict) -> str:
    name = get_username(uid)
    status = "✅ Выполнен" if order.get("done") else ("⏳ Текущий" if order.get("current") else "📦 Прошлый")
    title = order.get("title", "")
    price = order.get("price", "")
    link = order.get("link", "")
    text = (
        f"<b>{name}</b> — заказ #{idx+1}:\n"
        f"{title} - <b>{price} ₽</b>\n"
        f"Ссылка: {link}\n"
        f"Статус: {status}"
    )
    return text

async def send_order_message(uid: int, idx: int, to_user: Optional[int] = None):
    """
    Send a single order message for absolute index idx in user's list.
    If to_user is None => send to owner (uid). If to_user provided and is admin => send to that admin.
    """
    orders = get_user_orders_all(uid)
    if not (0 <= idx < len(orders)):
        return
    order = orders[idx]
    text = make_order_text(uid, idx, order)

    if order.get("current", False):
        # current: owner may cancel, admin may mark done (we'll show both buttons; handler will check permissions)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отменить ❌", callback_data=f"cancel_{uid}_{idx}"),
            # InlineKeyboardButton(text="Выполнен ✅", callback_data=f"done_{uid}_{idx}")
            ]
        ])
    else:
        # past: owner can delete
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Удалить ❌", callback_data=f"deletepast_{uid}_{idx}")]
        ])

    target = uid if to_user is None else to_user
    try:
        await bot.send_message(int(target), text, reply_markup=keyboard, disable_web_page_preview=True, parse_mode="HTML")
    except Exception:
        pass

# ========== WEBAPP HANDLER ==========
@dp.message(lambda m: m.web_app_data is not None)
async def webapp_data_handler(message: types.Message):
    uid = message.from_user.id

    # ensure registered
    if str(uid) not in load_data().get("users", {}):
        await message.answer("Вы не зарегистрированы. Нажмите /start чтобы зарегистрироваться.", disable_web_page_preview=True)
        return

    # check collecting flag
    if not is_collecting():
        await message.answer(
            "⛔ Сбор заказов сейчас закрыт. К сожалению, ваш заказ не был принят. Следите за объявлениями в боте.",
            disable_web_page_preview=True
        )
        return

    try:
        data = json.loads(message.web_app_data.data)
    except Exception:
        await message.answer("Неверные данные из WebApp. Заказ не принят.", disable_web_page_preview=True)
        return

    order = {
        "title": data.get("title", ""),
        "price": data.get("price", ""),
        "link": data.get("link", ""),
        "done": False
    }

    add_order(uid, order)
    all_orders = get_user_orders_all(uid)
    idx = len(all_orders) - 1
    # send owner the created order message
    await send_order_message(uid, idx)
    await message.answer("✅ Заказ успешно добавлен.", disable_web_page_preview=True)

# ========== USER VIEWS ==========

@dp.message(Command("my_current"))
@dp.message(F.text == "Мои текущие заказы")
async def my_current_handler(message: types.Message):
    uid = message.from_user.id
    arr = get_user_orders_all(uid)
    current_indices = [i for i, o in enumerate(arr) if o.get("current", False)]
    if not current_indices:
        await message.answer("У вас нет текущих заказов.", reply_markup=get_main_keyboard_for(uid))
        return
    for idx in current_indices:
        await send_order_message(uid, idx)

@dp.message(Command("my_past"))
@dp.message(F.text == "Мои прошлые заказы")
async def my_past_handler(message: types.Message):
    uid = message.from_user.id
    arr = get_user_orders_all(uid)
    past_indices = [i for i, o in enumerate(arr) if not o.get("current", True)]
    if not past_indices:
        await message.answer("У вас нет прошлых заказов.", reply_markup=get_main_keyboard_for(uid))
        return
    for idx in past_indices:
        await send_order_message(uid, idx)

# ========== ADMIN: start/close collection & all current orders ==========
@dp.message(Command("start_collection"))
@dp.message(F.text == "Начать сбор заказов (админ)")
async def start_collection_handler(message: types.Message):
    uid = message.from_user.id
    if not is_admin(uid):
        await message.answer("У вас нет прав для этой команды.")
        return

    data = load_data()
    # mark existing orders as past
    for uid_str, orders in data.get("orders", {}).items():
        for order in orders:
            order["current"] = False
    data["orders_open"] = True
    mark_dirty()

    await broadcast_to_all_users(bot, "🎉 Сбор заказов открыт! Можно отправлять новые заказы.")
    await message.answer("Сбор заказов открыт и всем пользователям отправлено уведомление.", reply_markup=get_main_keyboard_for(uid))

@dp.message(Command("close_collection"))
@dp.message(F.text == "Закрыть сбор заказов (админ)")
async def close_collection_handler(message: types.Message):
    uid = message.from_user.id
    if not is_admin(uid):
        await message.answer("У вас нет прав для этой команды.")
        return

    set_collection_state(False)
    await broadcast_to_all_users(bot, "⛔ Сбор заказов закрыт. Спасибо за заявки.")
    await message.answer("Сбор заказов закрыт и уведомления отправлены.", reply_markup=get_main_keyboard_for(uid))

@dp.message(Command("all_orders"))
@dp.message(F.text == "Все заказы (админ)")
async def all_orders_handler(message: types.Message):
    uid = message.from_user.id
    if not is_admin(uid):
        await message.answer("У вас нет прав для этой команды.")
        return

    all_orders = get_all_orders_dict()
    any_current = False
    for uid_str, orders in all_orders.items():
        user_total = 0

        for idx, order in enumerate(orders):
            if not order.get("current", False):
                continue
            any_current = True

            text = make_order_text(int(uid_str), idx, order)
            user_total += int(order.get("price", 0))

            keyboard = InlineKeyboardMarkup(inline_keyboard=[])
            if not order.get("done"):
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Отметить выполненным ✅", callback_data=f"done_{uid_str}_{idx}")]
                ])
            await message.answer(text, reply_markup=keyboard, disable_web_page_preview=True, parse_mode="HTML")

        if user_total > 0:
            await message.answer(f"💰 <b>Итого для {get_username(int(uid_str))}: {user_total} ₽</b>\n", parse_mode="HTML")

    if not any_current:
        await message.answer("Нет текущих заказов.", reply_markup=get_main_keyboard_for(uid))

# ========== CALLBACKS ==========
@dp.callback_query()
async def cb_handler(callback: types.CallbackQuery):
    data = callback.data or ""
    parts = data.split("_")
    if len(parts) < 3:
        await callback.answer()
        return

    action = parts[0]
    try:
        uid = int(parts[1])
        idx = int(parts[2])
    except Exception:
        await callback.answer("Неверные данные", show_alert=True)
        return

    orders = get_user_orders_all(uid)
    if not (0 <= idx < len(orders)):
        await callback.answer("Заказ не найден", show_alert=True)
        return

    order = orders[idx]

    # Cancel: owner or admin
    if action == "cancel":
        requester = callback.from_user.id
        if requester != uid and not is_admin(requester):
            await callback.answer("Нельзя отменить чужой заказ", show_alert=True)
            return
        if order.get("done"):
            await callback.answer("Нельзя отменить выполненный заказ", show_alert=True)
            return
        remove_order(uid, idx)
        await callback.message.edit_text(f"{get_username(uid)} — заказ #{idx+1} отменён ✅")
        await callback.answer("Заказ отменён")

    # Done: admin only
    elif action == "done":
        requester = callback.from_user.id
        if not is_admin(requester):
            await callback.answer("Только админ может отмечать заказ выполненным", show_alert=True)
            return
        order["done"] = True
        update_order(uid, idx, order)
        await callback.message.edit_text(f"{get_username(uid)} — заказ #{idx+1} отмечен как выполненный ✅")
        await callback.answer("Заказ отмечен как выполненный")

    # delete past: owner only
    elif action == "deletepast":
        requester = callback.from_user.id
        if requester != uid:
            await callback.answer("Нельзя удалять чужую запись", show_alert=True)
            return
        if order.get("current", True):
            await callback.answer("Нельзя удалить текущий заказ", show_alert=True)
            return
        remove_order(uid, idx)
        await callback.message.edit_text(f"{get_username(uid)} — прошлый заказ #{idx+1} удалён ❌")
        await callback.answer("Заказ удалён")

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
        await message.answer("Использование: /add_admin <user_id>")
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
        await message.answer("Использование: /del_admin <user_id>")
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
        await message.answer("Использование: /del_user <user_id>")
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
        await message.answer("Использование: /rename_user <user_id> <новое_имя>")
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
    users = data.get("users", {})
    if not users:
        await message.answer("Пользователей пока нет.")
        return
    lines = []
    for uid_str, name in users.items():
        uid = int(uid_str)
        flag = "⭐" if uid in data.get("admins", []) else ""
        lines.append(f"{uid}: {name} {flag}")
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
        await message.answer("Использование: /password_set <password> (пустая строка удалит пароль)")
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
        # show masked but allow admin to view full if wants
        masked = pwd[0] + "*"*(len(pwd)-1) if len(pwd) > 1 else "*"
        await message.answer(f"Текущий пароль (маска): {masked}\n(админ может /password_set чтобы изменить)")

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
    for uid in bl:
        name = data.get("users", {}).get(str(uid), "")
        lines.append(f"{uid} — {name}")
    await message.answer("Чёрный список:\n" + "\n".join(lines))

@dp.message(Command("users_remove_blacklist"))
async def users_remove_blacklist_cmd(message: types.Message):
    caller = message.from_user.id
    if not is_admin(caller):
        await message.answer("У вас нет прав.")
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Использование: /users_remove_blacklist <user_id>")
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
    uid = message.from_user.id

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

    if is_admin(uid):
        await message.answer(admin_help, disable_web_page_preview=True)
    else:
        await message.answer(user_help, disable_web_page_preview=True)

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
