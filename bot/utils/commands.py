#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import asyncio  # may still be used elsewhere; safe to keep
from aiogram import exceptions
from enum import Enum

from aiogram.filters import Command, or_f
from aiogram import F


class BotCommands(Enum):
    """Bot commands enum with command, button_text, and description."""
    # (command, button_text, description)
    
    # ========== USER COMMANDS ==========
    START = ("start", "", "Начать / зарегистрироваться (ввести имя и пароль при первой регистрации)")
    ORDERS_MENU = ("orders", "", "Показать меню выбора заказов (текущие/прошлые)")
    ORDERS_CURRENT = ("", "Мои текущие заказы", "Мои текущие заказы (можно отменить, если не выполнены)")
    ORDERS_PAST = ("", "Мои прошлые заказы", "Мои прошлые (архивные) заказы (можно удалить)")
    HELP = ("help", "", "Показать справку")

    # ========== ADMIN COMMANDS ==========
    # Collection management
    COLLECTION_MENU = ("collection", "", "Показать меню управления сбором заказов")

    # Collection management menu
    COLLECTION_NEW = ("", "Новый сбор заказов (админ)", "Новый сбор заказов")
    COLLECTION_CLOSE = ("", "Закрыть сбор заказов (админ)", "Закрыть сбор заказов")
    COLLECTION_OPEN = ("", "Открыть сбор заказов (админ)", "Открыть текущий сбор заказов")
    
    # Orders view
    ADMIN_ORDERS_MENU = ("all_orders", "", "Показать меню выбора просмотра заказов")
    ADMIN_ORDERS_BY_USER = ("", "Все заказы (админ)", "Просмотр всех заказов (сгруппированы по пользователям)")
    ADMIN_ORDERS_BY_PRODUCT = ("", "По товарам (админ)", "Просмотр заказов по товарам (массовое выполнение)")
    
    # User management
    USERS_LIST = ("users", "", "Управление пользователями")
    
    # Password management
    PASSWORD_MENU = ("password", "", "Управление паролем")
    
    # Blacklist management
    BLACKLIST_MENU = ("blacklist", "", "Управление чёрным списком")
    
    # Update management
    CHECK_UPDATE = ("check_update", "", "Проверить обновления бота")
    
    # Admin help
    ADMIN_HELP = ("admin_help", "Помощь (админ)", "Показать справку для администратора")
    
    # ========== SPECIAL BUTTONS ==========
    OPEN_WEBAPP = ("", "Открыть меню 🍔", "Открыть WebApp с меню для выбора блюд")

    @property
    def command(self) -> str:
        """Get command name."""
        return self.value[0]

    @property
    def button_text(self) -> str:
        """Get button text (empty string if no button)."""
        return self.value[1]

    @property
    def description(self) -> str:
        """Get command description."""
        return self.value[2]

    @property
    def filter(self):
        """Фильтр, который срабатывает и на команду, и на текст кнопки."""
        cmd_filter = Command(self.command)
        btn_filter = F.text == self.button_text
        return or_f(cmd_filter, btn_filter)

    def __str__(self) -> str:
        """String representation."""
        if self.command:
            return f"/{self.command}"
        return self.button_text


# Helper functions for easy access
def get_user_commands() -> list['BotCommands']:
    """Get list of user commands."""
    return [
        BotCommands.START,
        BotCommands.ORDERS_CURRENT,
        BotCommands.ORDERS_PAST,
        BotCommands.ORDERS_MENU,
        BotCommands.HELP,
    ]


def get_admin_commands() -> list['BotCommands']:
    """Get list of admin commands."""
    return [
        BotCommands.START,
        BotCommands.ORDERS_MENU,
        BotCommands.ORDERS_CURRENT,
        BotCommands.ORDERS_PAST,
        BotCommands.HELP,
        BotCommands.COLLECTION_NEW,
        BotCommands.COLLECTION_CLOSE,
        BotCommands.COLLECTION_OPEN,
        BotCommands.ADMIN_ORDERS_MENU,
        BotCommands.ADMIN_ORDERS_BY_USER,
        BotCommands.ADMIN_ORDERS_BY_PRODUCT,
        BotCommands.USERS_LIST,
        BotCommands.PASSWORD_MENU,
        BotCommands.BLACKLIST_MENU,
        BotCommands.CHECK_UPDATE,
        BotCommands.COLLECTION_MENU,     
        BotCommands.ADMIN_HELP,
    ]


# Removed unused helper functions:
# - get_commands_with_buttons
# - get_admin_buttons
# - get_user_buttons


def generate_user_help() -> str:
    """Generate user help text from commands enum."""
    help_text = "📘 Помощь — пользователь:\n\n"
    
    # Start command
    help_text += f"/{BotCommands.START.command} — {BotCommands.START.description}\n"
    
    # Menu button
    help_text += f"Кнопка в клавиатуре: «{BotCommands.OPEN_WEBAPP.button_text}» — {BotCommands.OPEN_WEBAPP.description}\n\n"
    
    help_text += "После выбора товара в WebApp нажмите «Заказать» — бот получит данные о товаре.\n\n"
    
    help_text += "Команды для пользователя:\n"
    for cmd in get_user_commands():
        if cmd.command:  # только команды с непустым command
            help_text += f"/{cmd.command} — {cmd.description}\n"
    help_text += "\n"
    
    help_text += "Примечания:\n"
    help_text += "- При регистрации у вас есть 3 попытки ввести пароль. После 3 неверных попыток вы автоматически попадёте в чёрный список.\n"
    help_text += "- Если сбор заказов закрыт, попытки заказать не принимаются.\n"
    help_text += "- Вопросы и проблемы — пишите администратору."
    
    return help_text


def generate_admin_help() -> str:
    """Generate admin help text from commands enum."""
    help_text = "📕 Помощь — администратор:\n\n"
    
    help_text += "Команды для администратора:\n"
    for cmd in get_admin_commands():
        if cmd.command:  # только команды с непустым command
            help_text += f"/{cmd.command} — {cmd.description}\n"
    help_text += "\n"
    
    help_text += "Примечания:\n"
    help_text += "- После выполнения команды все данные автоматически сохраняются."
    
    return help_text


# ========== BOT COMMANDS SETUP ==========

async def setup_bot_commands(bot):
    """
    Устанавливает команды бота для меню "/" в Telegram.
    Устанавливает команды для обычных пользователей (по умолчанию для всех).
    
    Args:
        bot: Экземпляр aiogram.Bot
    """
    from aiogram.types import BotCommand, BotCommandScopeDefault
    
    # Команды для обычных пользователей (показываются всем по умолчанию)
    user_commands_list = [
        BotCommand(command=cmd.command, description=cmd.description)
        for cmd in get_user_commands()
        if cmd.command  # только команды с непустым command
    ]
    
    # Однократная установка команд для всех пользователей
    try:
        await bot.set_my_commands(user_commands_list, scope=BotCommandScopeDefault(), request_timeout=10)
        logging.info(f"Set {len(user_commands_list)} user commands")
    except Exception as e:
        logging.debug(f"Failed to set global user commands: {e.__class__.__name__}: {e}")


# Track which admins have had their commands set
_admins_with_commands = set()

async def reset_admin_commands(bot, admin_id: int):
    """
    Сбрасывает команды администратора к пользовательским.
    Удаляет из списка админов с установленными командами.
    
    Args:
        bot: Экземпляр aiogram.Bot
        admin_id: ID бывшего администратора
    """
    from aiogram.types import BotCommandScopeChat
    
    try:
        # Remove from tracking set
        _admins_with_commands.discard(admin_id)
        
        # Delete commands for this chat to reset to default user commands
        await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=admin_id))
        logging.info(f"Reset commands for former admin {admin_id}")
    except Exception as e:
        logging.error(f"Failed to reset admin commands for {admin_id}: {e}")

async def setup_admin_commands(bot, admin_id: int):
    """
    Устанавливает расширенный список команд для администратора.
    Вызывается при первом обращении администратора к боту.
    
    Args:
        bot: Экземпляр aiogram.Bot
        admin_id: ID администратора
    """
    from aiogram.types import BotCommand, BotCommandScopeChat
    
    if admin_id in _admins_with_commands:
        return  # Already set
    
    try:
        admin_commands_list = [
            BotCommand(command=cmd.command, description=cmd.description)
            for cmd in get_admin_commands()
            if cmd.command  # только команды с непустым command
        ]
        
        # Устанавливаем команды только для этого чата (администратора)
        # Проверяем существование приватного чата. Если бот не "видел" пользователя — пропускаем.
        try:
            await bot.get_chat(admin_id)
        except exceptions.TelegramBadRequest as e:
            if "chat not found" in str(e).lower():
                # Тихо пропускаем фиктивного / неактивного пользователя
                logging.debug(f"Skip setting admin commands for inactive user {admin_id} (chat not found)")
                return
            # Другие ошибки — логируем warning
            logging.warning(f"get_chat failed for admin {admin_id}: {e.__class__.__name__}: {e}")
            return
        except Exception as e:
            logging.warning(f"Unexpected error during get_chat for {admin_id}: {e.__class__.__name__}: {e}")
            return

        try:
            await bot.set_my_commands(
                admin_commands_list,
                scope=BotCommandScopeChat(chat_id=admin_id),
                request_timeout=10  # Уменьшенный таймаут до 10s
            )
            _admins_with_commands.add(admin_id)
            logging.info(f"Set {len(admin_commands_list)} admin commands for user {admin_id}")
        except Exception as e:
            logging.debug(f"Failed to set admin commands for {admin_id}: {e.__class__.__name__}: {e}")
    except Exception as e:
        logging.error(f"Unexpected error building admin commands list for {admin_id}: {e.__class__.__name__}: {e}")
