@echo off
cd /d "%~dp0"
git add .
set /p MSG="Commit mesaji: "
git commit -m "%MSG%"
git push
pause
