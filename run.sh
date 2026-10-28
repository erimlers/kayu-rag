#!/bin/bash
# KAYÜ Mevzuat Asistanı Başlatma Scripti
PYTHON_BIN=$(command -v python3 || echo "/opt/anaconda3/bin/python3")
"$PYTHON_BIN" -m uvicorn src.api:app --host 127.0.0.1 --port 8000 --reload
