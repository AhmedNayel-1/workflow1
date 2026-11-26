@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions DisableDelayedExpansion

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONHOME="
set "PYTHONPATH="
set "VIRTUAL_ENV="
set "PIP_REQUIRE_VIRTUALENV="
set "PROJECT_DIR=%~dp0"
set "HELPER=%PROJECT_DIR%scripts\install_helper.py"
cd /d "%PROJECT_DIR%" || goto :err_cd

set "SERVER_PORT=%~1"
if not defined SERVER_PORT set "SERVER_PORT=8000"

echo ============================================================================
echo   منظومة السكرتارية والمراسلات - خادم التطوير المحلي
echo   Django Correspondence System - Development Server
echo   تنبيه: runserver مخصص للتطوير والاختبار فقط وليس لبيئة الإنتاج.
echo ============================================================================
echo.

set "VENV_PY=%PROJECT_DIR%venv\Scripts\python.exe"
if not exist "%VENV_PY%" goto :err_no_venv

if not exist "%PROJECT_DIR%.env" (
    if exist "%PROJECT_DIR%.env.example" (
        copy /y "%PROJECT_DIR%.env.example" "%PROJECT_DIR%.env" >nul
        echo [تنبيه] تم إنشاء ملف .env تلقائياً من .env.example.
    )
)

"%VENV_PY%" -c "import sys, django, dotenv, PIL, waitress, openpyxl; assert (3,10)<=sys.version_info[:2]<=(3,13) and django.VERSION[:2]==(5,1)" >nul 2>&1
if errorlevel 1 goto :err_bad_env

set "VIRTUAL_ENV=%PROJECT_DIR%venv"

echo [1/3] التحقق من حالة الترحيلات وتهيئة Django...
"%VENV_PY%" "%PROJECT_DIR%manage.py" migrate --check >nul 2>&1
if not errorlevel 1 goto :migrate_ok
echo تطبيق الترحيلات الناقصة فقط، بدون المساس بالبيانات الحالية...
"%VENV_PY%" "%PROJECT_DIR%manage.py" migrate --noinput
if errorlevel 1 goto :err_migrate_pending
:migrate_ok

"%VENV_PY%" "%PROJECT_DIR%manage.py" check
if errorlevel 1 goto :err_check

echo [2/3] التحقق من توفر المنفذ %SERVER_PORT%...
if exist "%HELPER%" (
    "%VENV_PY%" "%HELPER%" check-port 127.0.0.1 %SERVER_PORT% >nul 2>&1
    if errorlevel 1 goto :port_busy
)
goto :port_ok
:port_busy
echo المنفذ %SERVER_PORT% مستخدم، البحث عن منفذ آخر...
set /a SERVER_PORT=SERVER_PORT+1
if %SERVER_PORT% GTR 8100 goto :err_port_busy
"%VENV_PY%" "%HELPER%" check-port 127.0.0.1 %SERVER_PORT% >nul 2>&1
if errorlevel 1 goto :port_busy
:port_ok

echo [3/3] تشغيل الخادم الآن على: http://127.0.0.1:%SERVER_PORT%/
echo حساب الاختبار Superuser: an  ^|  كلمة المرور: 123
echo اضغط Ctrl+C لإيقاف الخادم.
echo.
start "" "http://127.0.0.1:%SERVER_PORT%/" >nul 2>&1
"%VENV_PY%" "%PROJECT_DIR%manage.py" runserver 127.0.0.1:%SERVER_PORT%
if errorlevel 1 goto :err_runtime
echo.
echo توقف الخادم.
pause
endlocal
exit /b 0

:err_cd
echo [خطأ] تعذر الانتقال إلى مجلد المشروع: "%PROJECT_DIR%"
pause
exit /b 1

:err_no_venv
echo [خطأ] لم يتم العثور على البيئة الافتراضية في:
echo   "%VENV_PY%"
echo يرجى تشغيل install.bat أولاً لإعداد المنظومة.
pause
exit /b 1

:err_bad_env
echo [خطأ] البيئة الافتراضية الحالية غير متوافقة أو ناقصة المكتبات.
echo يرجى تشغيل install.bat لإصلاح البيئة وتثبيت Django 5.1.x.
pause
exit /b 1

:err_migrate_pending
echo [خطأ] قاعدة البيانات غير مهيأة أو تحتاج لتطبيق الترحيلات ^(migrate^).
echo شغّل install.bat لإكمال التثبيت والتهيئة ثم أعد تشغيل run_server.bat.
pause
exit /b 1

:err_check
echo [خطأ] فشل فحص Django system check.
pause
exit /b 1

:err_port_busy
echo [خطأ] المنفذ %SERVER_PORT% مستخدم حالياً من برنامج آخر أو خادم يعمل مسبقاً!
echo يمكنك التشغيل على منفذ بديل مثل: run_server.bat 8080
pause
exit /b 1

:err_runtime
echo.
echo [خطأ] توقف الخادم بسبب خطأ غير متوقع.
pause
exit /b 1
