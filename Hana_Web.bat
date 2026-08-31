@echo off
cd /d "%~dp0"
start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0hana_web_app.py"
timeout /t 3 /nobreak >nul
set EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe
if not exist "%EDGE%" set EDGE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe
start "" "%EDGE%" --app=http://127.0.0.1:5001 --autoplay-policy=no-user-gesture-required
