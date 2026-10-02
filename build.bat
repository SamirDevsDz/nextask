@echo off
REM Construit NexTask.exe (dossier dist\NexTask) — demande les droits admin au lancement
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller --quiet
pyinstaller --noconfirm --windowed --name NexTask --uac-admin --icon nextask.ico ^
  --add-data "core;core" --add-data "pages;pages" --add-data "nextask.ico;." main.py
echo.
echo Termine : dist\NexTask\NexTask.exe
pause
