@echo off
REM Lance NexTask (installe les dépendances au premier lancement)
cd /d "%~dp0"
python -m pip install -r requirements.txt --quiet
python main.py
