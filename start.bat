@echo off
cd /d %~dp0
if not exist .venv (
    py -m venv .venv
    .venv\Scripts\python -m pip install -r requirements.txt
)
.venv\Scripts\python main.py
