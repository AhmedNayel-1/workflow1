@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
cd /d "%~dp0"
title تثبيت نظام المراسلات - Django

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "DJANGO_SETTINGS_MODULE=config.settings"
set "PY_CMD=py -V:Astral/CPython3.12.15"
set "VPY=%~dp0venv\Scripts\python.exe"
set "PORT=8000"
if not "%~1"=="" set "PORT=%~1"

echo ============================================================================
echo   نظام المراسلات - التثبيت التلقائي باستخدام Python 3.12
echo ============================================================================
echo.
echo [1/7] التحقق من إصدار بايثون Astral/CPython3.12.15 ...
%PY_CMD% --version >nul 2>&1
if errorlevel 1 (
    echo [خطأ] لا يمكن تشغيل Astral/CPython3.12.15
    echo        ثبّت هذا الإصدار اولًا، او عدّل المتغير PY_CMD في بداية الملف.
    pause
    exit /b 1
)
for /f "delims=" %%v in ('%PY_CMD% --version 2^>^&1') do set "PYVER=%%v"
echo       الإصدار المستخدم: !PYVER!
echo.

if not exist "%VPY%" (
    echo [2/7] إنشاء البيئة الافتراضية venv ...
    %PY_CMD% -m venv venv
    if errorlevel 1 (
        echo [خطأ] فشل إنشاء البيئة الافتراضية venv.
        pause
        exit /b 1
    )
) else (
    echo [2/7] البيئة الافتراضية venv موجودة مسبقًا.
)
if not exist "%VPY%" (
    echo [خطأ] لم يتم العثور على venv\Scripts\python.exe
    pause
    exit /b 1
)
echo.

echo [3/7] تثبيت حزم بايثون ...
if exist "%~dp0wheelhouse\" (
    echo       تم العثور على مجلد wheelhouse - تثبيت دون اتصال بالإنترنت.
    "%VPY%" -m pip install --no-index --find-links=wheelhouse -r requirements.txt
) else (
    echo       التثبيت من الإنترنت.
    "%VPY%" -m pip install --upgrade pip
    "%VPY%" -m pip install -r requirements.txt
)
if errorlevel 1 (
    echo [خطأ] فشل تثبيت الحزم. تحقق من الاتصال بالإنترنت او من مجلد wheelhouse.
    pause
    exit /b 1
)
echo.

echo [4/7] تهيئة ملف .env ومجلد التخزين storage_vault ...
if not exist "%~dp0.env" (
    if exist "%~dp0.env.example" (
        copy /y "%~dp0.env.example" "%~dp0.env" >nul
        echo       تم إنشاء .env من .env.example
    ) else (
        echo [تحذير] ملف .env.example غير موجود - تم تخطي إنشاء .env
    )
) else (
    echo       ملف .env موجود مسبقًا - لن يتم تعديله.
)
if not exist "%~dp0storage_vault" mkdir "%~dp0storage_vault"
echo.

echo [5/7] إنشاء وتطبيق هجرات قاعدة البيانات ...
"%VPY%" manage.py makemigrations core organization accounts subjects documents workflow committees decisions audit notifications reports
if errorlevel 1 (
    echo [خطأ] فشل إنشاء الهجرات makemigrations.
    pause
    exit /b 1
)
"%VPY%" manage.py migrate
if errorlevel 1 (
    echo [خطأ] فشل تطبيق الهجرات migrate.
    pause
    exit /b 1
)
echo.

echo [6/7] تعبئة البيانات المرجعية والسيناريوهات التشغيلية الخمسة ...
"%VPY%" manage.py seed_demo_data
if errorlevel 1 (
    echo [خطأ] فشل تنفيذ seed_demo_data.
    pause
    exit /b 1
)
echo.

echo [7/7] إنشاء المستخدم المدير - الاسم: an  كلمة المرور: 123 ...
"%VPY%" -c "import os, django; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); django.setup(); from django.contrib.auth import get_user_model; U = get_user_model(); u, _ = U.objects.get_or_create(username='an', defaults={'first_name': 'System Superuser', 'is_staff': True, 'is_superuser': True, 'is_system_admin': True, 'is_active': True}); u.is_staff = True; u.is_superuser = True; u.is_system_admin = True; u.is_active = True; u.set_password('123'); u.save(); print('Superuser an ready!')"
if errorlevel 1 (
    echo [خطأ] فشل إنشاء المستخدم المدير an.
    pause
    exit /b 1
)

echo.
echo ============================================================================
echo   تم التثبيت بنجاح
echo   المستخدم المدير: an    كلمة المرور: 123
echo   للتشغيل لاحقًا: run_server.bat
echo   ملاحظة: runserver للتطوير والاختبار فقط وليس للإنتاج.
echo ============================================================================
echo.
set "RUN_NOW="
set /p "RUN_NOW=هل تريد تشغيل سيرفر التطوير الآن؟ Y/N: "
if not defined RUN_NOW set "RUN_NOW=N"
set "RUN_NOW=!RUN_NOW: =!"
if /i not "!RUN_NOW!"=="Y" goto SKIP_RUN

echo.
echo ============================================================================
echo   فحص المنفذ !PORT!
echo ============================================================================
call :CHECK_PORT !PORT!
if not defined BUSY (
    echo       المنفذ متاح.
    goto PORT_OK
)

:PORT_MENU
echo.
echo ============================================================================
echo   المنفذ مشغول من تطبيق آخر: !PORT!
echo ============================================================================
echo   ملاحظة: إذا كان الاسم python.exe فقد يكون سيرفر مشروعك يعمل بالفعل.
echo.
echo   ماذا تريد ان تفعل؟
echo   [1] تحرير المنفذ - إغلاق التطبيق الآخر ثم التشغيل على نفس المنفذ
echo   [2] التشغيل على منفذ آخر - مع ترك التطبيق الآخر يعمل
echo   [3] إلغاء التشغيل الآن
echo.
set "CH="
set /p "CH=اختيارك 1 / 2 / 3: "
if not defined CH set "CH=0"
set "CH=!CH: =!"
if "!CH!"=="1" goto FREE_PORT
if "!CH!"=="2" goto OTHER_PORT
if "!CH!"=="3" goto SKIP_RUN
echo [خطأ] اختيار غير صحيح - اكتب 1 او 2 او 3.
goto PORT_MENU

:FREE_PORT
echo.
for %%p in (!BUSY_PIDS!) do (
    if "%%p"=="4" (
        echo       تخطي العملية PID 4 - عملية النظام لا يجوز إنهاؤها.
    ) else if "%%p"=="0" (
        echo       تخطي العملية PID 0.
    ) else (
        echo       إنهاء العملية PID %%p ...
        taskkill /F /PID %%p >nul 2>&1
    )
)
ping -n 3 127.0.0.1 >nul
call :CHECK_PORT !PORT!
if not defined BUSY (
    echo       تم تحرير المنفذ بنجاح.
    goto PORT_OK
)
echo [!] تعذر تحرير المنفذ - التطبيق يعيد تشغيل نفسه تلقائيًا.
echo     اوقفه من services.msc او من Docker Desktop ثم اعد المحاولة.
goto PORT_MENU

:OTHER_PORT
echo.
echo ============================================================================
echo   التشغيل على منفذ آخر
echo ============================================================================
call :FIND_FREE !PORT!
if not defined FREEPORT set "FREEPORT=8080"
echo       اول منفذ متاح: !FREEPORT!
set "NEWPORT="
set /p "NEWPORT=اكتب رقم المنفذ المطلوب او اضغط Enter لاستخدام المقترح: "
if not defined NEWPORT set "NEWPORT=!FREEPORT!"
set "NEWPORT=!NEWPORT: =!"
echo(!NEWPORT!|findstr /r "^[1-9][0-9]*$" >nul
if errorlevel 1 (
    echo [خطأ] رقم منفذ غير صالح - اكتب رقمًا بين 1024 و 65535.
    goto OTHER_PORT
)
if !NEWPORT! LSS 1024 (
    echo [خطأ] رقم منفذ غير صالح - اكتب رقمًا بين 1024 و 65535.
    goto OTHER_PORT
)
if !NEWPORT! GTR 65535 (
    echo [خطأ] رقم منفذ غير صالح - اكتب رقمًا بين 1024 و 65535.
    goto OTHER_PORT
)
set "PORT=!NEWPORT!"
call :CHECK_PORT !PORT!
if defined BUSY (
    echo [!] هذا المنفذ مشغول ايضا - اختر رقمًا آخر.
    goto PORT_MENU
)
echo       سيتم التشغيل على المنفذ !PORT!

:PORT_OK
echo.
echo ============================================================================
echo   تشغيل سيرفر التطوير: !PORT!
echo   الرابط المحلي: http://127.0.0.1:!PORT!/
echo   الشبكة المحلية: http://YOUR-PC-IP:!PORT!/   يتطلب ضبط ALLOWED_HOSTS
echo   للإيقاف: CTRL+C
echo ============================================================================
echo.
start "" "http://127.0.0.1:!PORT!/" >nul 2>&1
"%VPY%" manage.py runserver 0.0.0.0:!PORT!
if errorlevel 1 (
    echo.
    echo [تحذير] توقف السيرفر - إعادة المحاولة بدون إعادة التحميل التلقائي ...
    "%VPY%" manage.py runserver 0.0.0.0:!PORT! --noreload --traceback
)
echo.
echo تم إيقاف السيرفر.
pause
endlocal
exit /b 0

:SKIP_RUN
echo.
echo تم التثبيت. يمكنك التشغيل لاحقًا بالأمر: run_server.bat
pause
endlocal
exit /b 0

rem ---------------------------------------------------------------------------
rem  CHECK_PORT: only LISTENING sockets on the exact port, never browser sockets
rem ---------------------------------------------------------------------------
:CHECK_PORT
set "BUSY="
set "BUSY_PIDS="
for /f "tokens=2,5" %%a in ('netstat -ano -p TCP ^| findstr /I "LISTENING" ^| findstr /C:":%~1 "') do (
    set "BUSY=1"
    set "BUSY_PIDS=!BUSY_PIDS! %%b"
    echo       العنوان %%a    رقم العملية %%b
    tasklist /FI "PID eq %%b" /NH
)
exit /b 0

rem ---------------------------------------------------------------------------
rem  FIND_FREE: first free port after the requested one
rem ---------------------------------------------------------------------------
:FIND_FREE
set "FREEPORT="
set /a _base=%~1
for /l %%i in (1,1,20) do (
    if not defined FREEPORT (
        set /a _try=_base+%%i
        netstat -ano -p TCP | findstr /I "LISTENING" | findstr /C:":!_try! " >nul 2>&1
        if errorlevel 1 set "FREEPORT=!_try!"
    )
)
exit /b 0
