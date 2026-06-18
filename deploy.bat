@echo off
echo.
echo ========================================
echo   SMARTBOT - Railway Deploy
echo ========================================
echo.

set /p MSG="Commit mesaji yaz (Enter = 'update'): "
if "%MSG%"=="" set MSG=update

echo.
echo Dosyalar ekleniyor...
git add .

echo Commit atiliyor: %MSG%
git commit -m "%MSG%"

echo GitHub'a push ediliyor...
git push

echo.
echo ========================================
echo   TAMAMLANDI - Railway deploy basliyor
echo ========================================
echo.
pause
