#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import db.orders_db as db

async def broadcast_message(bot, text: str, for_admins: bool = False):
    """Отправляет сообщение всем пользователям или только администраторам."""
    users = db.get_users()
    for user in users:
        if for_admins and not user.is_admin:
            continue
        try:
            await bot.get_chat(user.user_id)
            await bot.send_message(user.user_id, text)
        except Exception as e:
            if "chat not found" in str(e).lower():
                #db.remove_user(user.user_id)
                logging.info(f"Removed user {user.user_id} due to chat not found")
            else:
                logging.exception(f"Failed to broadcast to user {user.user_id}")

# Backward compatibility
async def broadcast_to_all_admins(bot, text: str):
    await broadcast_message(bot, text, for_admins=True)

async def broadcast_to_all_users(bot, text: str):
    await broadcast_message(bot, text, for_admins=False)