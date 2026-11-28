# دليل النسخ الاحتياطي والاستعادة والتشغيل دون إنترنت

## 1. مسار حفظ النسخ الاحتياطية
- تُحفظ النسخ الاحتياطية افتراضياً **خارج مجلد الكود** في المسار المجاور:
  `..\correspondence_backups\backup_YYYYMMDD_HHMMSS_microsec\`
- يمكن تخصيص مسار مختلف (مثل قرص منفصل `D:\Backups\Correspondence`) عبر المتغير `BACKUP_ROOT` في ملف `.env`.
- يحتوي كل مجلد نسخة على:
  - `database.sqlite3` (أو `database.bak` في حالة `DB_ENGINE=mssql`)
  - `storage_vault\` (نسخة متزامنة كاملة من خزينة المرفقات المعزولة)
  - `backup_manifest.json` (بصمات `SHA-256` وأحجام قاعدة البيانات وكافة المرفقات)

## 2. تنفيذ النسخ الاحتياطي
- لتنفيذ نسخة يدوية أو جدولتها عبر Windows Task Scheduler:
  ```bat
  scripts\backup.bat
  ```
  أو دون إيقاف مؤقت للجدولة الآلية:
  ```bat
  scripts\backup.bat --no-pause
  ```
- في حالة **SQLite**: يعتمد النظام على `sqlite3.Connection.backup()` للنسخ الآمن المتسق حتى أثناء عمل النظام، ويتبعها بفحص `PRAGMA integrity_check`.
- في حالة **SQL Server (`DB_ENGINE=mssql`)**: يقرأ بيانات الاتصال من `.env` (`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_ODBC_DRIVER`) دون أي كلمات مرور ثابتة، وينفذ `BACKUP DATABASE ... WITH CHECKSUM` عبر `sqlcmd` أو `pyodbc`.
- يتم تدوير النسخ تلقائياً بالاحتفاظ بآخر **30 نسخة** صالحة وحذف الأقدم.

## 3. الاستعادة الآمنة (Restore)
- للاستعادة التفاعلية مع اختيار النسخة وتأكيد كتابة `RESTORE`:
  ```bat
  scripts\restore.bat
  ```
- قبل لمس قاعدة البيانات الحية أو الخزينة الحية، يتحقق النظام من تطابق **جميع بصمات `SHA-256`** في `backup_manifest.json` ومن سلامة `PRAGMA integrity_check` للنسخة المختارة، كما ينشئ نسخة أمان مؤقتة (`.pre_restore.sqlite3`) قبل الاستبدال.
