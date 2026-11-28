@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions DisableDelayedExpansion

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_DIR=%%~fI\"
cd /d "%PROJECT_DIR%" || goto :err_cd

echo ============================================================================
echo   منظومة السكرتارية والأرشفة — النسخ الاحتياطي الآمن (DB + Storage Vault)
echo ============================================================================
echo.

set "PY_BIN="
if exist "%PROJECT_DIR%venv\Scripts\python.exe" (
    set "PY_BIN=%PROJECT_DIR%venv\Scripts\python.exe"
) else (
    for /f "usebackq delims=" %%P in (`where python 2^>nul`) do (
        if not defined PY_BIN set "PY_BIN=%%~P"
    )
)

if not defined PY_BIN (
    echo [خطأ] لم يتم العثور على بيئة Python صالحة أو مجلد venv.
    pause
    exit /b 1
)

"%PY_BIN%" "%PROJECT_DIR%core\backup_utils.py" backup --keep 30
if errorlevel 1 (
    echo.
    echo [فشل] حدث خطأ أثناء تنفيذ النسخ الاحتياطي!
    pause
    exit /b 1
)

echo.
echo [تم] اكتمل النسخ الاحتياطي وحُفظ خارج مجلد المشروع مع الاحتفاظ بآخر 30 نسخة.
if not "%~1"=="--no-pause" pause
endlocal
exit /b 0

:err_cd
echo [خطأ] تعذر الوصول إلى مجلد المشروع.
pause
exit /b 1
