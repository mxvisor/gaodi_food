# config.py
import json
from pathlib import Path

CONFIG_FILE = Path("config.json")

# если файла нет — создаём с шаблоном
if not CONFIG_FILE.exists():
    default_config = {
        "BOT_TOKEN": "ваш_токен_здесь",
        "WEBAPP_URL": "https://ваш-webapp-url",
        "INITIAL_ADMIN": 0
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(default_config, f, ensure_ascii=False, indent=2)
    print(f"Создан файл {CONFIG_FILE}. Заполните его перед запуском бота.")
    exit(1)  # завершаем, чтобы пользователь вписал данные

# загружаем конфиг
with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    cfg = json.load(f)

BOT_TOKEN = cfg.get("BOT_TOKEN")
WEBAPP_URL = cfg.get("WEBAPP_URL")
INITIAL_ADMIN = cfg.get("INITIAL_ADMIN")

if not BOT_TOKEN or not WEBAPP_URL or not INITIAL_ADMIN:
    print("В config.json должны быть заполнены BOT_TOKEN, WEBAPP_URL и INITIAL_ADMIN")
    exit(1)
