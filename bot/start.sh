#!/usr/bin/env bash
set -e

if [ ! -d ".venv" ]; then
    echo "Creating python env..."
    python3.12 -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
else
    source .venv/bin/activate
fi

echo "Checking installed packages..."
# Получаем список установленных пакетов с версиями
INSTALLED=$(pip list --format=freeze)
# Инициализируем список отсутствующих
MISSING=$(awk '!/^#/ && NF {print}' requirements.txt | while read -r line; do
    if [[ $line == *"=="* ]]; then
        grep -iq "^$line\$" <<<"$INSTALLED" || echo "$line"
    else
        grep -iq "^${line}==" <<<"$INSTALLED" || echo "$line"
    fi
done)

if [ -n "$MISSING" ]; then
    echo -e "Missing or outdated packages:\n$MISSING\nInstalling required packages..."
#    pip install -r requirements.txt || { echo "❌ Failed to install dependencies"; exit 1; }
else
    echo "All packages are already installed."
fi

exec ./.venv/bin/watchmedo auto-restart --pattern="*.py" --recursive -- python3 bot.py

#python3 bot.py