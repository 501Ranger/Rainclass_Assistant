@echo off
call conda activate rainclass
cd /d "%~dp0"
python main.py
pause