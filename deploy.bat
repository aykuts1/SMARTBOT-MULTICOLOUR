@echo off
cd /d "%~dp0"
echo.
echo ========================================
echo   SMARTBOT - Railway Deploy
echo ========================================
echo.

REM Degisiklik var mi kontrol et
git status --porcelain > "%TEMP%\git_status.txt" 2>&1
for %%A in ("%TEMP%\git_status.txt") do set STATUS_SIZE=%%~zA
del "%TEMP%\git_status.txt" 2>nul

if %STATUS_SIZE% EQU 0 (
    echo Commit edilecek degisiklik yok.
    echo Direkt push yapiliyor...
    goto :push
)

set /p MSG="Commit mesaji yaz (Enter = 'update'): "
if "%MSG%"=="" set MSG=update

echo.
echo Dosyalar ekleniyor...
git add .

echo Commit atiliyor: %MSG%
git commit -m "%MSG%"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo HATA: Commit basarisiz!
    goto :end
)

:push
echo.
echo GitHub'a push ediliyor...
git push origin main
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo HATA: Push basarisiz!
    echo GitHub kimlik bilgilerinizi kontrol edin.
    goto :end
)

echo.
echo ========================================
echo   TAMAMLANDI - Railway deploy basliyor
echo ========================================

:end
echo.
pause
