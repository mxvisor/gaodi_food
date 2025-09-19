if [ ! -d ".venv" ]; then
    echo "Creating python env..."
    python -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    pip install -r requirements.txt
else
    source .venv/bin/activate
fi

exec ./.venv/bin/uvicorn main:app --reload --host 0.0.0.0 --port 8000