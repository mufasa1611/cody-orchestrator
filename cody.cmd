@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHON=%ROOT%venv\Scripts\python.exe"

if not exist "%PYTHON%" (
  echo Missing virtual environment Python at "%PYTHON%".
  exit /b 1
)

"%PYTHON%" -m crew_agent %*
