# منظومة إدارة السكرتارية والمراسلات والأرشفة والدورة المستندية (Django)

نظام مؤسسي متكامل (Modular Monolith) مبني بإطار عمل **Django 5.1** و **Tailwind CSS (RTL)** لإدارة دورة حياة الموضوعات والمعاملات والمراسلات والسكرتارية والإحالات والمهام والمذكرات والتأشيرات واللجان والقرارات ومتابعة تنفيذها، مع نظام صلاحيات متعدد الأبعاد وعزل صارم للسرية.

---

## 1. المتطلبات المعتمدة

- **Python**: `3.10` إلى `3.13` (**الإصدار الأنسب والموصى به: `3.11.x` أو `3.12.x`**؛ ولا يُنصح بأقل من `3.10` أو بإصدارات `3.14+` غير المستقرة مع Django 5.1).
- **Django**: `5.1.x` (`Django>=5.1,<5.2` في `requirements.txt`).
- **قاعدة البيانات**:
  - **للتطوير والاختبار المحلي**: `SQLite` (مُعدّ افتراضياً).
  - **لبيئة الإنتاج**: `Microsoft SQL Server` عبر `mssql-django` و `pyodbc` + `ODBC Driver 17/18 for SQL Server`.
- **خادم الإنتاج الموصى به على Windows Server**: `Waitress` خلف IIS (Reverse Proxy).

---

## 2. التشغيل السريع عبر ملفات BAT (نظام Windows)

1. شغّل ملف التثبيت والتهيئة:
   - **تثبيت عبر الإنترنت (أو بوجود `wheelhouse` مع Python 3.12 من Astral):**
     ```cmd
     install.bat
     ```
   - **تثبيت دون إنترنت 100% (Offline مع مجلد `wheelhouse` واكتشاف Python المتوافق تلقائياً):**
     ```cmd
     install_offline.bat
     ```
   يقوم التثبيت بإنشاء البيئة الافتراضية `venv` داخل مجلد المشروع، وتثبيت حزم `requirements.txt`، وتجهيز `.env` ومجلد `storage_vault`، وتطبيق `makemigrations` و`migrate`، وتحميل البيانات التجريبية `seed_demo_data`، وإنشاء حساب Superuser (`an` / `123`).

2. لتشغيل السيرفر لاحقاً في أي وقت (بشكل منفصل):
   ```cmd
   run_server.bat
   ```
   > **تنبيه أمني وتشغيلي:** أمر `runserver` مخصص **للتطوير والاختبار فقط** ولا يجوز استخدامه في بيئة الإنتاج.

---

## 3. خطوات التثبيت والتشغيل يدوياً عبر سطر الأوامر (Command Prompt / PowerShell)

```cmd
:: 1. الانتقال إلى مجلد المشروع
cd django_project

:: 2. إنشاء البيئة الوهمية (venv)
python -m venv venv

:: 3. تفعيل البيئة الوهمية
:: على Windows CMD:
venv\Scripts\activate
:: على PowerShell:
:: .\venv\Scripts\Activate.ps1
:: على Linux / macOS:
:: source venv/bin/activate

:: 4. تثبيت المكتبات المطلوبة
pip install -r requirements.txt

:: 5. تجهيز ملف متغيرات البيئة
copy .env.example .env

:: 6. إنشاء وتطبيق ترحيلات قاعدة البيانات (Migrations)
python manage.py makemigrations
python manage.py migrate

:: 7. تجميع الملفات الثابتة المحلية للعمل دون إنترنت
python manage.py collectstatic --noinput

:: 8. تحميل البيانات المرجعية وحسابات الاختبار والسيناريوهات الخمسة
python manage.py seed_demo_data

:: 9. (اختياري) إنشاء حساب مدير نظام إضافي
python manage.py createsuperuser

:: 10. تشغيل خادم التطوير المحلي
python manage.py runserver
```

افتح المتصفح على العنوان: `http://127.0.0.1:8000/`

---

## 4. التثبيت دون اتصال بالإنترنت (Offline Wheelhouse)

في حال وجود قيود على الاتصال بالإنترنت داخل شبكة الشركة:

1. على جهاز متصل بالإنترنت:
   ```cmd
   mkdir wheelhouse
   pip download -r requirements.txt -d wheelhouse
   ```
3. انسخ مجلد `wheelhouse` بجانب ملفات المشروع وشغّل:
   ```cmd
   install_offline.bat
   ```
   أو ثبّت يدوياً عبر:
   ```cmd
   pip install --no-index --find-links=wheelhouse -r requirements.txt
   ```

> **تأكيد التشغيل المحلي دون إنترنت 100%:** لا تعتمد المنظومة على أي CDN خارجي؛ حيث يتم تحميل كافة الأنماط من الحزمة المحلية `static/css/app.css` وتجميعها عبر `collectstatic`.

---

## 5. إعداد SQL Server لبيئة الإنتاج

عدّل ملف `.env` بالقيم التالية:
```env
DJANGO_DEBUG=False
DB_ENGINE=mssql
DB_NAME=CorrespondenceDB
DB_USER=correspondence_app
DB_PASSWORD=StrongPasswordHere!
DB_HOST=10.0.0.15
DB_PORT=1433
DB_ODBC_DRIVER=ODBC Driver 17 for SQL Server
SECURE_STORAGE_ROOT=D:\EnterpriseStorage\CorrespondenceVault
BACKUP_ROOT=D:\Backups\CorrespondenceBackups
```

ثم شغّل الإنتاج عبر `waitress`:
```cmd
waitress-serve --host=127.0.0.1 --port=8000 config.wsgi:application
```

---

## 6. الحسابات التجريبية (بعد تشغيل `seed_demo_data`)

كلمة المرور الافتراضية لجميع الحسابات التجريبية (للاختبار المحلي فقط): `Pass@12345`

| اسم المستخدم | الدور / الصفة | القطاع / الوحدة |
| :--- | :--- | :--- |
| `admin` | مسؤول النظام | الإدارة العامة لنظم المعلومات |
| `chairman` | رئيس مجلس الإدارة | مكتب رئيس مجلس الإدارة |
| `hr_head` | رئيس قطاع الموارد البشرية | قطاع الموارد البشرية |
| `hr_sec` | سكرتارية رئيس قطاع الموارد البشرية (مفوّضة) | مكتب رئيس قطاع الموارد البشرية |
| `personnel_gm` | مدير عام شئون الأفراد | الإدارة العامة لشئون الأفراد |
| `transfers_sup` | مشرف قسم التنقلات | قسم التنقلات |
| `transfers_emp` | موظف مختص - تنقلات | قسم التنقلات |
| `penalties_emp` | موظف مختص - جزاءات | قسم الجزاءات |
| `settlements_emp` | موظف مختص - تسويات | قسم التسويات |
| `housing_emp` | موظف مختص - الشئون الإدارية | الإدارة العامة للشئون الإدارية |

---

## 7. تشغيل الاختبارات الآلية ومراجعة قاعدة البيانات

- لتشغيل كافة الاختبارات الأمنية والوظيفية والتقارير (بما فيها `tests/test_security.py` و `tests/test_p2.py`):
```cmd
python manage.py test tests
```
- المرجع الكامل لقاعدة البيانات والجداول والعلاقات: `docs/ERD.md`.

---

## 8. النسخ الاحتياطي والاستعادة (Backup & Restore)

توفر المنظومة سكريبتات جاهزة ومتزامنة في `scripts\`:
1. **إنشاء نسخة احتياطية كاملة (`scripts\backup.bat`)**: تنفذ نسخاً متزامناً لقاعدة البيانات (`sqlite3.Connection.backup()` في SQLite أو `BACKUP DATABASE` في SQL Server عبر `.env`) بالتوازي مع خزينة المرفقات `SECURE_STORAGE_ROOT` وتوليد `backup_manifest.json` ببصمات `SHA-256` خارج مجلد الكود مع الاحتفاظ بآخر **30 نسخة**.
2. **الاستعادة الآمنة (`scripts\restore.bat`)**: تتحقق من `backup_manifest.json` وكافة بصمات `SHA-256` وسلامة قاعدة البيانات قبل الاستبدال، ولا تنفذ الاستعادة إلا بتأكيد صريح (`RESTORE`). راجع `docs/BACKUP_AND_RESTORE.md`.

