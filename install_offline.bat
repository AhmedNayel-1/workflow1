@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions DisableDelayedExpansion

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONHOME="
set "PYTHONPATH="
set "VIRTUAL_ENV="
set "PIP_REQUIRE_VIRTUALENV="
set "PIP_NO_INDEX=1"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "NON_INTERACTIVE=0"
if /i "%~1"=="--non-interactive" set "NON_INTERACTIVE=1"
if /i "%~1"=="-y" set "NON_INTERACTIVE=1"

set "PROJECT_DIR=%~dp0"
set "HELPER=%PROJECT_DIR%scripts\install_helper.py"
cd /d "%PROJECT_DIR%" || goto :err_cd

echo ============================================================================
echo   منظومة السكرتارية والمراسلات - المثبت دون إنترنت ^(Offline Installer^)
echo   Django Correspondence System - 100%% Offline Windows Installer
echo   المتطلب المعتمد: Django 5.1.x - مجلد wheelhouse محلي
echo ============================================================================
echo.
echo مسار المشروع الحالي:
echo   "%PROJECT_DIR%"
echo.

rem ----------------------------------------------------------------------------
rem 1. التحقق من ملفات المشروع ومجلد wheelhouse المحلي
rem ----------------------------------------------------------------------------
echo [فحص 1/5] التحقق من ملفات المشروع الأساسية...
if not exist "%PROJECT_DIR%manage.py" goto :err_missing_files
if not exist "%PROJECT_DIR%requirements.txt" goto :err_missing_files
if not exist "%PROJECT_DIR%config\settings.py" goto :err_missing_files
if not exist "%PROJECT_DIR%.env.example" goto :err_missing_files
if not exist "%HELPER%" goto :err_missing_files
echo     [OK] جميع ملفات المشروع الأساسية موجودة.

echo [فحص 2/5] التحقق من وجود مجلد الحزم المحلية ^(wheelhouse^)...
if not exist "%PROJECT_DIR%wheelhouse\" goto :err_no_wheelhouse
echo     [OK] تم العثور على مجلد wheelhouse.

rem ----------------------------------------------------------------------------
rem 2. التحقق من صلاحية الكتابة
rem ----------------------------------------------------------------------------
echo [فحص 3/5] التحقق من صلاحية الكتابة داخل مجلد المشروع...
set "WRITE_PROBE=%PROJECT_DIR%.offline_write_probe_%RANDOM%.tmp"
(echo ok>"%WRITE_PROBE%") 2>nul
if not exist "%WRITE_PROBE%" goto :err_write_perm
del /q "%WRITE_PROBE%" >nul 2>&1
echo     [OK] صلاحية الكتابة متوفرة.

rem ----------------------------------------------------------------------------
rem 3. اكتشاف إصدار Python المتوافق دون الحاجة إلى إنترنت
rem ----------------------------------------------------------------------------
echo [فحص 4/5] البحث عن إصدار Python متوافق ^(3.10 إلى 3.15^)...

set "BEST_PY="
set "BEST_VER="

rem محاولة Astral/CPython3.12.15 أولاً إذا كان متوفراً على الجهاز
where py >nul 2>&1
if not errorlevel 1 (
    for /f "usebackq delims=" %%E in (`py -V:Astral/CPython3.12.15 -c "import sys; print(sys.executable)" 2^>nul`) do (
        if exist "%%~E" (
            "%%~E" "%HELPER%" probe >nul 2>&1
            if not errorlevel 1 (
                set "BEST_PY=%%~E"
                for /f "usebackq delims=" %%V in (`"%%~E" -c "import sys; print('.'.join(map(str, sys.version_info[:3])))" 2^>nul`) do set "BEST_VER=%%~V"
            )
        )
    )
)

if defined BEST_PY goto :python_selected

set "RAW_CAND=%PROJECT_DIR%.offline_raw_candidates.txt"
set "DIR_CAND=%PROJECT_DIR%.offline_dir_candidates.txt"
set "SEL_OUT=%PROJECT_DIR%.offline_selected_python.txt"
if exist "%RAW_CAND%" del /q "%RAW_CAND%" >nul 2>&1
if exist "%DIR_CAND%" del /q "%DIR_CAND%" >nul 2>&1
if exist "%SEL_OUT%" del /q "%SEL_OUT%" >nul 2>&1
type nul > "%RAW_CAND%"
type nul > "%DIR_CAND%"

where py >nul 2>&1
if not errorlevel 1 (
    >>"%RAW_CAND%" py -0p 2>nul
    for %%V in (3.11 3.12 3.10 3.13 3.14 3.15 3.9 3) do (
        for /f "usebackq delims=" %%E in (`py -%%V -c "import sys; print(sys.executable)" 2^>nul`) do (
            >>"%RAW_CAND%" echo %%~E
            >>"%DIR_CAND%" echo %%~E
        )
    )
)

for /f "usebackq delims=" %%E in (`where python 2^>nul`) do (
    >>"%RAW_CAND%" echo %%~E
    >>"%DIR_CAND%" echo %%~E
)
for /f "usebackq delims=" %%E in (`where python3 2^>nul`) do (
    >>"%RAW_CAND%" echo %%~E
    >>"%DIR_CAND%" echo %%~E
)

for %%K in (
    "HKCU\Software\Python\PythonCore"
    "HKLM\Software\Python\PythonCore"
    "HKLM\SOFTWARE\WOW6432Node\Python\PythonCore"
) do (
    >>"%RAW_CAND%" reg query %%K /s 2>nul
    for /f "tokens=1,2,*" %%A in ('reg query %%K /s /v ExecutablePath 2^>nul') do (
        if /i "%%~B"=="REG_SZ" if not "%%~C"=="" >>"%DIR_CAND%" echo %%~C
    )
    for /f "tokens=1,2,*" %%A in ('reg query %%K /s /ve 2^>nul') do (
        if /i "%%~B"=="REG_SZ" if not "%%~C"=="" (
            if exist "%%~C\python.exe" >>"%DIR_CAND%" echo %%~C\python.exe
            if exist "%%~Cpython.exe" >>"%DIR_CAND%" echo %%~Cpython.exe
        )
    )
    for /f "tokens=1,2,3,*" %%A in ('reg query %%K /s /ve 2^>nul') do (
        if /i "%%~C"=="REG_SZ" if not "%%~D"=="" (
            if exist "%%~D\python.exe" >>"%DIR_CAND%" echo %%~D\python.exe
            if exist "%%~Dpython.exe" >>"%DIR_CAND%" echo %%~Dpython.exe
        )
    )
)

for %%B in (
    "%LocalAppData%\Programs\Python"
    "%ProgramFiles%"
    "%ProgramFiles(x86)%"
    "%SystemDrive%"
) do (
    if exist "%%~B\" (
        for /d %%D in ("%%~B\Python*") do (
            if exist "%%~D\python.exe" (
                >>"%RAW_CAND%" echo %%~D\python.exe
                >>"%DIR_CAND%" echo %%~D\python.exe
            )
        )
    )
)

for %%C in (
    "%UserProfile%\anaconda3\python.exe"
    "%UserProfile%\miniconda3\python.exe"
    "%LocalAppData%\anaconda3\python.exe"
    "%LocalAppData%\miniconda3\python.exe"
    "%ProgramData%\anaconda3\python.exe"
    "%ProgramData%\miniconda3\python.exe"
) do (
    if exist "%%~C" (
        >>"%RAW_CAND%" echo %%~C
        >>"%DIR_CAND%" echo %%~C
    )
)

set "BOOT_PY="
for /f "usebackq delims=" %%P in ("%DIR_CAND%") do (
    if not defined BOOT_PY (
        if /i not "%%~P"=="%PROJECT_DIR%venv\Scripts\python.exe" (
            if exist "%%~P" (
                "%%~P" "%HELPER%" probe >nul 2>&1
                if not errorlevel 1 set "BOOT_PY=%%~P"
            )
        )
    )
)

if not defined BOOT_PY goto :err_no_compatible_python

"%BOOT_PY%" "%HELPER%" select "%RAW_CAND%" "%SEL_OUT%" --exclude-dir "%PROJECT_DIR%venv"
set "SEL_RC=%errorlevel%"
del /q "%RAW_CAND%" >nul 2>&1
del /q "%DIR_CAND%" >nul 2>&1

if not "%SEL_RC%"=="0" goto :err_no_compatible_python
if not exist "%SEL_OUT%" goto :err_no_compatible_python

set "BEST_LINE="
for /f "usebackq delims=" %%L in ("%SEL_OUT%") do set "BEST_LINE=%%L"
del /q "%SEL_OUT%" >nul 2>&1
if not defined BEST_LINE goto :err_no_compatible_python

for /f "tokens=1,2 delims=|" %%A in ("%BEST_LINE%") do (
    set "BEST_PY=%%A"
    set "BEST_VER=%%B"
)
if not defined BEST_PY goto :err_no_compatible_python
if not exist "%BEST_PY%" goto :err_no_compatible_python

:python_selected
echo     [OK] تم اعتماد Python %BEST_VER%:
echo          "%BEST_PY%"

rem ----------------------------------------------------------------------------
rem 4. التحقق من صلاحية wheelhouse و venv والمساحة الحرة
rem ----------------------------------------------------------------------------
echo [فحص 5/5] التحقق من اكتمال wheelhouse وصلاحية البيئة...
"%BEST_PY%" "%HELPER%" preflight "%PROJECT_DIR%"
if errorlevel 1 goto :err_preflight_failed

"%BEST_PY%" "%HELPER%" check-wheelhouse "%PROJECT_DIR%wheelhouse"
if errorlevel 1 goto :err_invalid_wheelhouse
echo     [OK] مجلد wheelhouse يحتوي على الحزم المطلوبة وجاهز للتثبيت دون إنترنت.

set "REBUILD_VENV=0"
if exist "%PROJECT_DIR%venv\" (
    "%BEST_PY%" "%HELPER%" check-venv "%PROJECT_DIR%venv" >nul 2>&1
    if errorlevel 1 (
        echo     [تنبيه] مجلد venv الحالي غير متوافق أو منقول؛ سيتم إعادة إنشائه.
        set "REBUILD_VENV=1"
    ) else (
        echo     [OK] البيئة الافتراضية الحالية venv سليمة ومتوافقة.
    )
)
echo ============================================================================
echo.

rem ----------------------------------------------------------------------------
rem خطوة 1: إنشاء / تجهيز venv داخل المشروع
rem ----------------------------------------------------------------------------
if "%REBUILD_VENV%"=="1" (
    echo [1/7] إزالة البيئة الافتراضية القديمة غير المتوافقة...
    rmdir /s /q "%PROJECT_DIR%venv"
    if exist "%PROJECT_DIR%venv\" goto :err_venv_remove
)

if not exist "%PROJECT_DIR%venv\Scripts\python.exe" (
    echo [1/7] إنشاء البيئة الافتراضية venv باستخدام Python %BEST_VER%...
    "%BEST_PY%" -m venv "%PROJECT_DIR%venv"
    if errorlevel 1 goto :err_venv_create
) else (
    echo [1/7] استخدام البيئة الافتراضية الحالية ^(venv^).
)

set "VENV_PY=%PROJECT_DIR%venv\Scripts\python.exe"
if not exist "%VENV_PY%" goto :err_venv_create
set "VIRTUAL_ENV=%PROJECT_DIR%venv"

rem ----------------------------------------------------------------------------
rem خطوة 2: التحقق المحلي من pip دون أي اتصال بالإنترنت
rem ----------------------------------------------------------------------------
echo [2/7] التحقق من pip محلياً داخل venv...
"%VENV_PY%" -m pip --version >nul 2>&1
if errorlevel 1 (
    "%VENV_PY%" -m ensurepip --upgrade >nul 2>&1
    "%VENV_PY%" -m pip --version >nul 2>&1
    if errorlevel 1 goto :err_pip_broken
)

rem ----------------------------------------------------------------------------
rem خطوة 3: التثبيت الإلزامي دون إنترنت من wheelhouse فقط
rem ----------------------------------------------------------------------------
echo [3/7] تثبيت المكتبات محلياً دون إنترنت ^(--no-index --find-links=wheelhouse^)...
"%VENV_PY%" -m pip install --no-index --find-links="%PROJECT_DIR%wheelhouse" -r "%PROJECT_DIR%requirements.txt"
if errorlevel 1 goto :err_pip_offline_install

echo     التحقق الفعلي من استيراد جميع الحزم وإصدار Django 5.1.x...
"%VENV_PY%" -c "import sys, django, dotenv, PIL, waitress, openpyxl; v=django.VERSION[:2]; assert v==(5,1), v; print('Verified Python', sys.version.split()[0], '| Django', django.get_version())"
if errorlevel 1 goto :err_pkg_verify

rem ----------------------------------------------------------------------------
rem خطوة 4: تجهيز ملف .env ومجلد الخزينة storage_vault
rem ----------------------------------------------------------------------------
echo [4/7] تجهيز ملف .env ومجلد المرفقات المعزول storage_vault...
if not exist "%PROJECT_DIR%.env" (
    copy /y "%PROJECT_DIR%.env.example" "%PROJECT_DIR%.env" >nul
    if errorlevel 1 goto :err_env_copy
    echo     تم إنشاء .env من .env.example.
) else (
    echo     ملف .env موجود مسبقاً ولن يتم استبداله.
)
if not exist "%PROJECT_DIR%storage_vault" mkdir "%PROJECT_DIR%storage_vault"

rem ----------------------------------------------------------------------------
rem خطوة 5: إعداد وتطبيق الترحيلات
rem ----------------------------------------------------------------------------
echo [5/7] إنشاء وتطبيق ترحيلات قاعدة البيانات ^(Migrations^)...
"%VENV_PY%" "%PROJECT_DIR%manage.py" makemigrations --noinput core organization accounts subjects documents workflow committees decisions audit notifications reports
if errorlevel 1 goto :err_makemigrations
"%VENV_PY%" "%PROJECT_DIR%manage.py" migrate --noinput
if errorlevel 1 goto :err_migrate

rem ----------------------------------------------------------------------------
rem خطوة 6: تحميل البيانات التجريبية وضمان حساب الاختبار an / 123
rem ----------------------------------------------------------------------------
echo [6/7] تحميل البيانات التجريبية وتهيئة حساب Superuser ^(an / 123^)...
"%VENV_PY%" "%PROJECT_DIR%manage.py" seed_demo_data
if errorlevel 1 goto :err_seed

"%VENV_PY%" "%HELPER%" ensure-superuser "%PROJECT_DIR%"
if errorlevel 1 goto :err_superuser

rem ----------------------------------------------------------------------------
rem خطوة 7: تجميع الملفات الثابتة المحلية والفحص الشامل
rem ----------------------------------------------------------------------------
echo [7/7] تجميع الملفات الثابتة المحلية وفحص النظام...
"%VENV_PY%" "%PROJECT_DIR%manage.py" collectstatic --noinput
if errorlevel 1 goto :err_collectstatic
"%VENV_PY%" "%PROJECT_DIR%manage.py" check
if errorlevel 1 goto :err_check

echo.
echo ============================================================================
echo   اكتمل التثبيت دون إنترنت بنجاح!
echo   الإصدار المعتمد: Python %BEST_VER% + Django 5.1.x
echo   حساب الاختبار Superuser: an  ^|  كلمة المرور: 123
echo   لتشغيل الخادم في أي وقت: run_server.bat
echo   تنبيه: runserver مخصص للتطوير والاختبار فقط وليس للإنتاج.
echo ============================================================================
echo.
set "RUN_NOW="
if "%NON_INTERACTIVE%"=="0" (
    set /p RUN_NOW="هل تريد تشغيل خادم التطوير الآن؟ (Y/N): "
)
if /i "%RUN_NOW%"=="Y" (
    call "%PROJECT_DIR%run_server.bat"
)

endlocal
exit /b 0

rem ============================================================================
rem معالجة الأخطاء الواضحة
rem ============================================================================
:maybe_pause
if "%NON_INTERACTIVE%"=="0" pause
exit /b 0

:err_cd
echo [خطأ] تعذر الانتقال إلى مجلد المشروع: "%PROJECT_DIR%"
call :maybe_pause
exit /b 1

:err_missing_files
echo [فشل الفحص] ملفات المشروع غير مكتملة في: "%PROJECT_DIR%"
call :maybe_pause
exit /b 1

:err_no_wheelhouse
echo.
echo [فشل التثبيت دون إنترنت] لم يتم العثور على مجلد wheelhouse بجانب install_offline.bat!
echo المسار المتوقع:
echo   "%PROJECT_DIR%wheelhouse"
echo.
echo لتحضير التثبيت دون إنترنت، نفّذ الأمر التالي على جهاز متصل بنفس إصدار Python وبنية الويندوز ^(64-bit^):
echo   pip download -r requirements.txt -d wheelhouse
echo ثم انسخ مجلد wheelhouse بالكامل إلى مجلد المشروع وأعد تشغيل install_offline.bat.
call :maybe_pause
exit /b 1

:err_invalid_wheelhouse
echo.
echo [فشل التثبيت دون إنترنت] مجلد wheelhouse فارغ أو لا يحتوي على حزمة Django!
echo نفّذ على جهاز متصل بالإنترنت:
echo   pip download -r requirements.txt -d wheelhouse
call :maybe_pause
exit /b 1

:err_write_perm
echo [فشل الفحص] لا توجد صلاحية كتابة داخل مجلد المشروع: "%PROJECT_DIR%"
call :maybe_pause
exit /b 1

:err_preflight_failed
echo [فشل الفحص] تعذر استيفاء شروط المساحة أو الصلاحيات أعلاه.
call :maybe_pause
exit /b 1

:err_no_compatible_python
del /q "%RAW_CAND%" >nul 2>&1
del /q "%DIR_CAND%" >nul 2>&1
del /q "%SEL_OUT%" >nul 2>&1
echo.
echo [فشل الفحص] لم يتم العثور على إصدار Python متوافق ^(3.10 إلى 3.15^) على هذا الجهاز.
echo ثبّت Python 3.11.x أو 3.12.x من المثبت المحلي ^(Offline Installer^) ثم أعد تشغيل install_offline.bat.
call :maybe_pause
exit /b 1

:err_venv_remove
echo [خطأ] تعذر حذف مجلد venv القديم. أغلق أي برنامج يستخدمه ثم أعد المحاولة.
call :maybe_pause
exit /b 1

:err_venv_create
echo [خطأ] فشل إنشاء البيئة الافتراضية venv باستخدام Python %BEST_VER%.
call :maybe_pause
exit /b 1

:err_pip_broken
echo [خطأ] أداة pip غير متاحة داخل البيئة الافتراضية venv.
call :maybe_pause
exit /b 1

:err_pip_offline_install
echo.
echo [خطأ] فشل التثبيت المحلي من مجلد wheelhouse!
echo تأكد من أن حزم wheelhouse تم تنزيلها لنفس نظام Windows ^(win_amd64^) ونفس إصدار Python ^(%BEST_VER%^):
echo   pip download -r requirements.txt -d wheelhouse
call :maybe_pause
exit /b 1

:err_pkg_verify
echo [خطأ] فشل التحقق من استيراد الحزم أو توافق Django 5.1.x.
call :maybe_pause
exit /b 1

:err_env_copy
echo [خطأ] تعذر نسخ .env.example إلى .env.
call :maybe_pause
exit /b 1

:err_makemigrations
echo [خطأ] فشل أمر makemigrations.
call :maybe_pause
exit /b 1

:err_migrate
echo [خطأ] فشل تطبيق الترحيلات migrate.
call :maybe_pause
exit /b 1

:err_seed
echo [خطأ] فشل تحميل البيانات التجريبية seed_demo_data.
call :maybe_pause
exit /b 1

:err_superuser
echo [خطأ] فشل تهيئة حساب الاختبار Superuser an/123.
call :maybe_pause
exit /b 1

:err_collectstatic
echo [خطأ] فشل تجميع الملفات الثابتة المحلية collectstatic.
call :maybe_pause
exit /b 1

:err_check
echo [خطأ] فشل فحص النظام manage.py check.
call :maybe_pause
exit /b 1
