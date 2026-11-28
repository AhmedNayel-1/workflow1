@echo off
cd /d "%~dp0"
setlocal enabledelayedexpansion

echo ============================================================================
echo   Django Correspondence System - Automated Installer (Using Python 3.12)
echo ============================================================================
echo.

:: تحديد بايثون بناءً على إعدادات الجهاز الحالي
set "PY_CMD=python"

:: التحقق من أن الإصدار يعمل
%PY_CMD% --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Could not run Python using command: %PY_CMD%
    pause
    exit /b 1
)

echo Using Python command: %PY_CMD%
%PY_CMD% --version
echo.

if not exist "venv\Scripts\python.exe" (
    echo [1/7] Creating virtual environment venv...
    %PY_CMD% -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment venv.
        pause
        exit /b 1
    )
) else (
    echo [1/7] Virtual environment venv already exists.
)

echo [2/7] Activating virtual environment...
call "%~dp0venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment.
    pause
    exit /b 1
)

echo [3/7] Installing Python packages...
if exist "wheelhouse\" (
    echo     Found wheelhouse folder - installing offline...
    python -m pip install --no-index --find-links=wheelhouse -r requirements.txt
) else (
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
)
if errorlevel 1 (
    echo [ERROR] pip install failed. Check internet connection or wheelhouse folder.
    pause
    exit /b 1
)

echo [4/7] Preparing .env and isolated storage_vault...
if not exist ".env" (
    copy /y ".env.example" ".env" >nul
    echo     Created .env from .env.example.
)
if not exist "storage_vault" mkdir "storage_vault"

echo [5/7] Creating and applying database migrations...
python manage.py makemigrations core organization accounts subjects documents workflow committees decisions audit notifications reports
if errorlevel 1 (
    echo [ERROR] makemigrations failed.
    pause
    exit /b 1
)
python manage.py migrate
if errorlevel 1 (
    echo [ERROR] migrate failed.
    pause
    exit /b 1
)

echo [6/7] Seeding reference data and 5 operational scenarios...
python manage.py seed_demo_data
if errorlevel 1 (
    echo [ERROR] seed_demo_data failed.
    pause
    exit /b 1
)

echo [7/7] Creating Superuser ^(username: an / password: 123^)...
python -c "import os, django; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); django.setup(); from django.contrib.auth import get_user_model; U = get_user_model(); u, _ = U.objects.get_or_create(username='an', defaults={'first_name': 'System Superuser', 'is_staff': True, 'is_superuser': True, 'is_system_admin': True, 'is_active': True}); u.is_staff = True; u.is_superuser = True; u.is_system_admin = True; u.is_active = True; u.set_password('123'); u.save(); print('Superuser an ready!')"
if errorlevel 1 (
    echo [ERROR] Failed to create superuser an.
    pause
    exit /b 1
)

echo.
echo ============================================================================
echo   Installation completed successfully!
echo   Superuser: an / Password: 123
echo   Run run_server.bat anytime to start the server.
echo   Note: runserver is for development/testing only, not production.
echo ============================================================================
echo.
set /p RUN_NOW="Start development server now? (Y/N): "
if /i "%RUN_NOW%"=="Y" (
    call "%~dp0run_server.bat"
)

endlocal