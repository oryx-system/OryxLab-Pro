@echo off
chcp 65001 > nul
echo [INFO] 관리자 권한을 확인하고 있습니다...

:: Check for Admin rights
net session >nul 2>&1
if %errorLevel% == 0 (
    echo [OK] 관리자 권한이 확인되었습니다.
) else (
    echo [ERROR] 관리자 권한이 필요합니다.
    echo.
    echo 이 파일을 마우스 오른쪽 버튼으로 클릭하고
    echo **"관리자 권한으로 실행"**을 선택해주세요.
    echo.
    pause
    exit /b
)

echo [INFO] OryxLab-Pro (포트 5000) 방화벽 허용 규칙을 추가합니다...
netsh advfirewall firewall add rule name="OryxLab-Pro Web" dir=in action=allow protocol=TCP localport=5000

if %errorLevel% == 0 (
    echo.
    echo [SUCCESS] 방화벽 설정이 완료되었습니다!
    echo 이제 스마트폰에서 접속을 다시 시도해보세요.
) else (
    echo [ERROR] 방화벽 설정 중 오류가 발생했습니다.
)
echo.
pause
