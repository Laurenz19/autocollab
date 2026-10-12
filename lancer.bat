@echo off
rem Double-cliquez sur ce fichier pour démarrer l'assistant, puis ouvrez http://127.0.0.1:8800
cd /d "%~dp0"
start "" http://127.0.0.1:8800
.venv\Scripts\python.exe run.py
pause
