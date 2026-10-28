#!/bin/bash
# KAYÜ Mevzuat Asistanı Başlatma Scripti
/opt/anaconda3/bin/python3 -m uvicorn src.api:app --host 127.0.0.1 --port 8000 --reload
