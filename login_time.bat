@echo off
setlocal

cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (
    py main.py
) else (
    where python >nul 2>&1
    if %errorlevel%==0 (
        python main.py
    ) else (
        echo Python non trovato.
        echo Installa Python o aggiungilo al PATH, poi riprova.
        pause
        exit /b 1
    )
)

if %errorlevel% neq 0 (
    echo.
    echo Errore durante l'avvio dell'app.
    pause
)

endlocal
