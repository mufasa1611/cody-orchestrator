@echo off
setlocal enabledelayedexpansion

echo ===================================================
echo           Welcome to Codin Pro Installer           
echo ===================================================

:: 1. Check prerequisites
where git >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: Git is not installed or not in PATH.
    exit /b 1
)

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: Python is not installed or not in PATH.
    exit /b 1
)

:: 2. Ollama Auto-Installer
echo.
echo Checking for Ollama...
where ollama >nul 2>nul
if %errorlevel% neq 0 (
    echo [!] Ollama not found. I will install it for you.
    echo Downloading Ollama Setup...
    powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://ollama.com/download/OllamaSetup.exe' -OutFile 'OllamaSetup.exe'"
    echo Installing Ollama (please wait for the window to close)...
    start /wait OllamaSetup.exe
    del OllamaSetup.exe
    echo Success: Ollama installed.
) else (
    echo [v] Ollama is already installed.
)

:: 3. Get install path
set "DEFAULT_PATH=%USERPROFILE%\codin"
set /p "INSTALL_PATH=Enter installation path [%DEFAULT_PATH%]: "
if "%INSTALL_PATH%"=="" set "INSTALL_PATH=%DEFAULT_PATH%"

echo.
echo Installing Codin to %INSTALL_PATH%...
echo.

:: 4. Clone repository
if not exist "%INSTALL_PATH%" (
    git clone https://github.com/mufasa1611/cody-orchestrator.git "%INSTALL_PATH%"
    if !errorlevel! neq 0 (
        echo Error: Failed to clone repository.
        exit /b 1
    )
) else (
    echo Directory already exists. Updating...
    cd /d "%INSTALL_PATH%"
    git pull
)

cd /d "%INSTALL_PATH%"

:: 5. Create Virtual Environment & Install
echo.
echo Creating Virtual Environment...
python -m venv venv
call venv\Scripts\python.exe -m pip install --upgrade pip
call venv\Scripts\python.exe -m pip install -e .

:: 6. HARDWARE ANALYSIS & MODEL RECOMMENDATION
echo.
echo Analyzing hardware for optimal performance...
echo.

:: Use PowerShell to detect CPU, GPU, and VRAM
set "HW_SCRIPT=$gpu = Get-CimInstance Win32_VideoController | Select-Object -First 1; $vram = [math]::Round($gpu.AdapterRAM / 1GB, 0); $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1; Write-Output \"CPU: $($cpu.Name)\"; Write-Output \"GPU: $($gpu.Name)\"; Write-Output \"VRAM: $vram GB\";"
powershell -NoProfile -Command "%HW_SCRIPT%"

:: Decision logic in PowerShell for recommendation
for /f "tokens=*" %%i in ('powershell -NoProfile -Command "$gpu = Get-CimInstance Win32_VideoController | Select-Object -First 1; $vram = [math]::Round($gpu.AdapterRAM / 1GB, 0); if($vram -ge 20){'llama3:70b'}elseif($vram -ge 12){'gemma2:27b'}elseif($vram -ge 6){'gemma2:9b'}else{'phi3'}"') do set "REC_MODEL=%%i"

echo.
echo Based on your hardware, I recommend: [bold cyan]%REC_MODEL%[/bold cyan]
set /p "CHOSEN_MODEL=Enter model to use [%REC_MODEL%]: "
if "%CHOSEN_MODEL%"=="" set "CHOSEN_MODEL=%REC_MODEL%"

echo.
echo Pulling model %CHOSEN_MODEL% (this may take a while)...
ollama pull %CHOSEN_MODEL%

:: 7. Update Codin Config
echo.
echo Configuring Codin to use %CHOSEN_MODEL% as default...
set "CONFIG_PATH=%INSTALL_PATH%\.cody\config.json"
if not exist "%INSTALL_PATH%\.cody" mkdir "%INSTALL_PATH%\.cody"
powershell -NoProfile -Command "$c = @{model='%CHOSEN_MODEL%'; permission_mode='safe'}; $c | ConvertTo-Json | Out-File -FilePath '%CONFIG_PATH%' -Encoding utf8"

:: 8. Create global command alias
echo.
echo Setting up global 'codin' command...
set "LAUNCHER_DIR=%USERPROFILE%"
set "CMD_PATH=%LAUNCHER_DIR%\codin.cmd"
(
echo @echo off
echo setlocal
echo set "VENV_PYTHON=%INSTALL_PATH%\venv\Scripts\python.exe"
echo set "CODY_HOME=%INSTALL_PATH%\.cody"
echo set "PYTHONPATH=%INSTALL_PATH%\src"
echo if "%%~1"=="" ^(
echo     "%%VENV_PYTHON%%" -m crew_agent.cli shell
echo ^) else ^(
echo     "%%VENV_PYTHON%%" -m crew_agent.cli %%*
echo ^)
echo endlocal
) > "%CMD_PATH%"

echo ===================================================
echo Installation Complete!
echo You can now type 'codin' from anywhere.
echo ===================================================
pause
