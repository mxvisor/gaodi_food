from aiogram.filters import BaseFilter, Command, or_f
from aiogram.types import Message
from aiogram import F

from db import orders_db as db
from utils.commands import BotCommands


class IsAdmin(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        res = db.is_admin(message.from_user.id)
        if not res:
            await message.answer("У вас нет прав.")
            return False
        return True


class RequireCollecting(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        if not db.is_collecting():
            await message.answer(
                "⛔ Сбор заказов сейчас закрыт."
            )
            return False
        return True


