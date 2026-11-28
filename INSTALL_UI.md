# تركيب الواجهة الجديدة (Frontend v2)

## قبل البدء
1. خذ نسخة احتياطية كاملة من المشروع (خصوصاً مجلدات `templates` و`static`).
2. هذه الحزمة **تستبدل الواجهة بالكامل**. لا تركّبها فوق الحزمة السابقة `ui_redesign_patch.zip`.

## الخطوات
1. احذف من مشروعك:
   - مجلد `templates/` بالكامل.
   - `static/css/ui.css` و`static/css/theme.css` و`static/css/app.css` القديم.
   - `static/js/ui.js` و`static/js/guide.js`.
   - (اترك `static/fonts/` كما هو.)
2. انسخ محتويات هذه الحزمة فوق المشروع (نفس المسارات):
   - `templates/` (جديد بالكامل) — `static/css/app.css` — `static/js/app.js`
   - `core/templatetags/` — `core/guidance.py` — `subjects/guidance.py`
   - `core/views.py` و`subjects/views.py` (يضيفان بيانات بطاقة «الخطوة التالية»)
   - `tests/test_new_features.py` (تحديث تأكيدات مرتبطة بأصناف الواجهة القديمة)
3. شغّل: `python manage.py collectstatic --noinput` (إن كان DEBUG=False).
4. شغّل الاختبارات: `python manage.py test tests` ثم افتح الصفحات يدوياً.

## ما لا يتغير
لا تعديل على النماذج أو قاعدة البيانات أو الروابط أو الصلاحيات. التغيير في القوالب وCSS وJS ومرشّحين صغيرين في الـ views.
