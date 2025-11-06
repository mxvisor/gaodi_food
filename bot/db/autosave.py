#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
from .orders_db import save_data

async def autosave_loop():
    """
    Background task to periodically save data.
    """
    while True:
        await asyncio.sleep(300)  # 5 minutes
        try:
            save_data()
            logging.info("Autosave completed successfully")
        except Exception as e:
            logging.error(f"Autosave failed: {e}")