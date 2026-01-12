@echo off
setlocal
chcp 65001 > nul

echo [INFO] OryxLab-Pro 환경 설정을 시작합니다...

:: 1. Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python이 설치되어 있지 않거나 PATH에 추가되지 않았습니다.
    echo [GUIDE] https://www.python.org/downloads/ 에서 Python 3.9 이상을 설치해주세요.
    echo [GUIDE] 설치 시 "Add Python to PATH" 옵션을 반드시 체크해야 합니다.
    pause
    exit /b 1
)

:: 2. Create Virtual Environment
if not exist ".venv" (
    echo [INFO] 가상 환경(.venv)을 생성합니다...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] 가상 환경 생성 실패.
        pause
        exit /b 1
    )
) else (
    echo [INFO] 기존 가상 환경을 발견했습니다.
)

:: 3. Install Dependencies
echo [INFO] 필요한 라이브러리를 설치합니다...
call .venv\Scripts\activate.bat
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] 라이브러리 설치 실패.
    pause
    exit /b 1
)

echo.
echo [SUCCESS] 설정이 완료되었습니다!
echo [INFO] 이제 'run_app.bat'을 실행하여 서버를 시작할 수 있습니다.
echo.
pause
