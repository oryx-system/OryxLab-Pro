@echo off
setlocal
chcp 65001 > nul

if not exist ".venv" (
    echo [ERROR] 가상 환경이 없습니다. 먼저 'setup_env.bat'을 실행해주세요.
    pause
    exit /b 1
)

echo [INFO] OryxLab-Pro 서버를 시작합니다...
call .venv\Scripts\activate.bat

:: Set environment variables if needed
set FLASK_APP=app.py
set FLASK_ENV=development

:: Run the app
python app.py
pause
