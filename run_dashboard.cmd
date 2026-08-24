@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src"

if not exist ".venv\Scripts\python.exe" (
  echo Project virtualenv Python was not found at .venv\Scripts\python.exe
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m streamlit run "yourscript.py" --server.port 8501 --server.address localhost --server.headless true
echo.
echo Dashboard process exited.
pause
