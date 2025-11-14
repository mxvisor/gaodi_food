#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from utils.commands import BotCommands
from utils.keyboards import get_main_keyboard_for
from db import orders_db as db

registration_router = Router(name="registration_router")

# ========== FSM ==========
class UserRegistration(StatesGroup):
    waiting_for_name = State()
    waiting_for_password = State()

# ========== START HANDLER ==========
@registration_router.message(Command(BotCommands.START.command))
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

@registration_router.message(UserRegistration.waiting_for_name)
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

@registration_router.message(UserRegistration.waiting_for_password)
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