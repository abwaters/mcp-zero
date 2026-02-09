@echo off
cd /d %~dp0..
call .venv\Scripts\activate.bat
ruff format src/ tests/ %*
