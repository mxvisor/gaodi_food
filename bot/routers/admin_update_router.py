#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
from aiogram import Router, types, F
from aiogram.filters.command import Command

from utils.keyboards import make_update_keyboard, UpdateAction

import db.orders_db as db
from utils.commands import BotCommands


router = Router()

async def _run_git(*args: str, timeout: int = 30) -> str:
    """Асинхронно запускает git команду и возвращает stdout (decoded).
    Поднимает RuntimeError при ненулевом коде выхода. stderr включается в сообщение.
    """
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"git {' '.join(args)} timed out after {timeout}s")
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (exit {proc.returncode}): {stderr.decode(errors='ignore').strip()}"
        )
    return stdout.decode(errors='ignore')

# --- Текущий коммит одной строкой
async def get_current_commit_line() -> str:
    """Возвращает строку лога текущего коммита (HEAD) в формате "<short_hash> <subject>".
    В случае ошибки возвращает "UNKNOWN".
    """
    try:
        return (await _run_git("log", "-1", "--oneline", "--no-decorate")).strip()
    except Exception:
        return "UNKNOWN"

# --- Асинхронная проверка обновлений и сбор истории коммитов
async def get_update_info() -> str | None:
    try:
        # Скачиваем обновления (тихо)
        await _run_git("fetch", "--quiet")
        # Текущий локальный хеш
        local = (await _run_git("rev-parse", "HEAD")).strip()
        # Пытаемся получить upstream. Если не настроен - считаем, что обновлений нет.
        try:
            remote = (await _run_git("rev-parse", "@{u}")).strip()
        except Exception:
            return None
        if local == remote:
            return None  # обновлений нет
        # Коммиты между локальным и удалённым
        commits = (await _run_git("log", f"{local}..{remote}", "--oneline", "--no-decorate")).strip()
        return commits or None
    except Exception as e:
        # Логируем в консоль, но не падаем
        print("Ошибка при проверке обновлений:", e)
        return None

# --- Команда /check_update
@router.message(BotCommands.CHECK_UPDATE.filter)
async def check_update(message: types.Message):
    """Проверяет наличие обновлений и всегда показывает текущий локальный коммит.

    Поведение:
    - Если есть новые коммиты в upstream: показывает список и кнопку обновления.
    - Если нет обновлений или upstream не настроен: сообщает об отсутствии и выводит текущий HEAD.
    """
    if not message.from_user or not db.is_admin(message.from_user.id):
        return
    await message.answer("Проверяю обновления…")

    # Всегда получаем строку лога текущего коммита.
    current_line = await get_current_commit_line()

    commits = await get_update_info()
    if commits:
        text = (
            "Доступны новые коммиты.\n"
            f"Текущий HEAD: {current_line}\n\n"
            f"{commits}\n\n"
            "Нажмите 'Обновить ✅' чтобы применить."
        )
        kb = make_update_keyboard()
        await message.answer(text, reply_markup=kb)
    else:
        await message.answer(
            f"Обновлений нет.\nТекущий коммит: {current_line}"
        )

# --- Обработчик кнопки обновления
@router.callback_query(UpdateAction.filter_action(UpdateAction.ActionType.DO_UPDATE))
async def do_update(call: types.CallbackQuery, callback_data: UpdateAction):
    if not call.from_user or not db.is_admin(call.from_user.id):
        return await call.answer("Нет доступа", show_alert=True)
    if not call.message:
        await call.answer()
        return
    msg = call.message
    if not isinstance(msg, types.Message):
        await call.answer()
        return
    await msg.edit_text("Выполняю обновление…")
    try:
        # Быстрый безопасный fast-forward pull
        await _run_git("pull", "--ff-only")
    except Exception as e:
        await msg.answer(f"Ошибка при обновлении: {e}")
        return
    await msg.answer("Обновление завершено. Бот перезапустится автоматически.")
    # Для тестирования перезапуска
    #import os
    #os.system("touch bot.py")