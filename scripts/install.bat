@echo off
cd /d %~dp0..
python -m venv .venv
call .venv\Scripts\activate.bat
pip install -e ".[dev]"
