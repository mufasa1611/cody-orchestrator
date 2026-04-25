@echo off
setlocal enabledelayedexpansion

echo ===================================================
echo Welcome to Codex Installer
echo ===================================================

:: 1. Check prerequisites
where git >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: Git is not installed or not in PATH. Please install Git and try again.
    exit /b 1
)

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: Python is not installed or not in PATH. Please install Python and try again.
    exit /b 1
)

:: 2. Get install path
set "DEFAULT_PATH=%USERPROFILE%\codex"
set /p "INSTALL_PATH=Enter installation path [%DEFAULT_PATH%]: "
if "%INSTALL_PATH%"=="" set "INSTALL_PATH=%DEFAULT_PATH%"

echo.
echo Installing Codex to %INSTALL_PATH%...
echo.

:: 3. Clone repository
if not exist "%INSTALL_PATH%" (
    git clone https://github.com/mufasa1611/cody-orchestrator.git "%INSTALL_PATH%"
    if !errorlevel! neq 0 (
        echo Error: Failed to clone repository.
        exit /b 1
    )
) else (
    echo Directory already exists. Attempting to update...
    cd /d "%INSTALL_PATH%"
    git pull
)

cd /d "%INSTALL_PATH%"

:: 4. Create Virtual Environment
echo.
echo Creating Virtual Environment...
python -m venv venv
if !errorlevel! neq 0 (
    echo Error: Failed to create virtual environment.
    exit /b 1
)

:: 5. Install Dependencies
echo.
echo Installing dependencies...
call venv\Scripts\python.exe -m pip install --upgrade pip
call venv\Scripts\python.exe -m pip install -e .
if !errorlevel! neq 0 (
    echo Error: Failed to install dependencies.
    exit /b 1
)

:: 6. Create global command alias
echo.
echo Setting up global 'codex' command...
set "CMD_PATH=%USERPROFILE%\codex.cmd"
(
echo @echo off
echo setlocal
echo set "VENV_PYTHON=%INSTALL_PATH%\venv\Scripts\python.exe"
echo set "CODY_HOME=%INSTALL_PATH%\.cody"
echo if "%%~1"=="" ^(
echo     "%%VENV_PYTHON%%" -m crew_agent.cli shell
echo ^) else ^(
echo     "%%VENV_PYTHON%%" -m crew_agent.cli %%*
echo ^)
echo endlocal
) > "%CMD_PATH%"

echo ===================================================
echo Installation Complete!
echo You can now type 'codex' from anywhere to start.
echo On your first run, Codex will help you set up Ollama and pick an AI model.
echo ===================================================
pause
