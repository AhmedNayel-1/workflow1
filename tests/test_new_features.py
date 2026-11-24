"""
حزمة اختبارات الميزات الجديدة والتكامل المؤسسي (test_new_features.py):
1. صلاحيات مسؤول القطاع / الإدارة العامة (SECTOR_DIR_ADMIN): إدارة المستخدمين ضمن النطاق فقط وحجب صلاحيات Superuser (403).
2. مظلة الشركة القابضة لكهرباء مصر (EEHC) وإضافة شركات موازية دون المساس بهيكل شركة غرب الدلتا لإنتاج الكهرباء.
3. البحث المتقدم في الأرشيف (بالتاريخ، جهة الصدور، نوع المستند، والسرية) مع عزل السري للغاية.
4. التصدير المباشر لملفات PDF المؤسسية للموضوعات والمذكرات والمستندات والتقارير مع التحقق من البايتات والصلاحيات.
5. المعاينة الشاملة للمرفقات بما في ذلك استخراج جداول وفقرات ملفات Office (.docx / .xlsx) مع التعقيم.
6. شاشة السجلات الموحدة (التعديلات، المشكلات والأخطاء، الأحداث) ومستكشف مسار موضوع لمستخدم محدد.
7. المسار التنفيذي ذو الـ 5 خطوات الأفقية ومبدّل المستخدمين للاختبار المحلي (L1–L6).
"""
import io
import json
import zipfile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook
from accounts.models import Role, User
from accounts.services import PermissionService
from audit.models import AuditLog
from core.models import ConfidentialityLevel, DocumentType, SystemErrorLog
from documents.models import Attachment, Document
from documents.office_preview import extract_office_preview_html
from documents.services import DocumentService
from organization.models import Company, OrgUnit, Sector
from subjects.models import Memo, Subject


def _build_minimal_docx_bytes(text_line: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        zf.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p><w:r><w:t>{text_line}</w:t></w:r></w:p></w:body>"
            "</w:document>",
        )
    return buf.getvalue()


def _build_minimal_xlsx_bytes(header: str, value: str) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "البيانات"
    ws.append([header, "القيمة"])
    ws.append([value, 1250])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class NewFeaturesTestSuite(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo_data")

    def test_sector_dir_admin_scoped_management_and_restrictions(self):
        client = Client()
        sector_admin = User.objects.get(username="hr_sector_admin")
        self.assertFalse(sector_admin.is_superuser)
        self.assertFalse(sector_admin.is_system_admin)
        self.assertTrue(sector_admin.is_secretariat)
        self.assertTrue(PermissionService.can_manage_users(sector_admin))

        client.force_login(sector_admin)

        # 1) يُمنع من الشاشات الحصرية لـ Superuser (مصفوفة الصلاحيات / إدارة قاعدة البيانات)
        self.assertEqual(client.get(reverse("accounts:permissions_matrix")).status_code, 403)

        # 2) يمكنه فتح شاشة المستخدمين وإضافة مستخدم داخل قطاعه (قطاع الشئون الإدارية والموارد البشرية)
        users_url = reverse("accounts:users_list")
        self.assertEqual(client.get(users_url).status_code, 200)

        hr_unit = OrgUnit.objects.filter(sector=sector_admin.current_sector).first()
        specialist_role = Role.objects.get(code="SPECIALIST")
        self.assertIsNotNone(hr_unit)

        resp_create = client.post(
            users_url,
            {
                "action": "create_user",
                "username": "scoped_hr_emp",
                "password": "Pass@12345",
                "full_name": "أ. موظف قطاع جديد",
                "job_display_title": "أخصائي موارد بشرية",
                "org_unit_id": hr_unit.id,
                "role_id": specialist_role.id,
                "sector_id": hr_unit.sector_id,
            },
        )
        self.assertEqual(resp_create.status_code, 302)
        created_u = User.objects.get(username="scoped_hr_emp")

        # 3) يُمنع (403) من إضافة مستخدم خارج قطاعه (مثل قطاع محطة سيدي كرير)
        other_sector = Sector.objects.exclude(id=hr_unit.sector_id).filter(org_units__isnull=False).first()
        if other_sector:
            other_unit = other_sector.org_units.first()
            resp_cross = client.post(
                users_url,
                {
                    "action": "create_user",
                    "username": "cross_sector_emp",
                    "password": "Pass@12345",
                    "full_name": "محاولة خارج النطاق",
                    "org_unit_id": other_unit.id,
                    "role_id": specialist_role.id,
                    "sector_id": other_sector.id,
                },
            )
            self.assertEqual(resp_cross.status_code, 403)
            self.assertFalse(User.objects.filter(username="cross_sector_emp").exists())

        # 4) يُمنع (403) من إسناد أدوار قيادية عليا أو مسؤول نظام
        sysadmin_role = Role.objects.filter(code="SYSTEM_ADMIN").first()
        if sysadmin_role:
            resp_elevate = client.post(
                users_url,
                {
                    "action": "create_user",
                    "username": "elevated_try",
                    "password": "Pass@12345",
                    "full_name": "محاولة تصعيد",
                    "org_unit_id": hr_unit.id,
                    "role_id": sysadmin_role.id,
                    "sector_id": hr_unit.sector_id,
                },
            )
            self.assertEqual(resp_elevate.status_code, 403)

        # 5) يُمنع (403) من حذف Superuser أو مستخدم من قطاع آخر
        superuser = User.objects.get(username="an")
        self.assertEqual(
            client.post(users_url, {"action": "delete_user", "user_id": superuser.id}).status_code,
            403,
        )
        sidi_user = User.objects.filter(username="sidi_veh_emp").first()
        if sidi_user:
            self.assertEqual(
                client.post(users_url, {"action": "delete_user", "user_id": sidi_user.id}).status_code,
                403,
            )

        # 6) يمكنه حذف المستخدم الذي أنشأه داخل قطاعه
        resp_del = client.post(users_url, {"action": "delete_user", "user_id": created_u.id})
        self.assertEqual(resp_del.status_code, 302)
        self.assertFalse(User.objects.filter(username="scoped_hr_emp").exists())

    def test_holding_company_umbrella_and_parallel_company_creation(self):
        client = Client()
        superuser = User.objects.get(username="an")
        client.force_login(superuser)

        org_url = reverse("organization:org_tree")
        resp = client.get(org_url)
        self.assertEqual(resp.status_code, 200)

        # التحقق من وجود الشركة القابضة وشركة غرب الدلتا وبقاء قطاعاتها ووحداتها كاملة
        holding = Company.objects.get(code="EEHC")
        wdepco = Company.objects.get(code="WDEPCO")
        self.assertTrue(holding.is_holding)
        self.assertEqual(wdepco.parent_company_id, holding.id)
        wdepco_sectors_before = Sector.objects.filter(company=wdepco).count()
        self.assertGreater(wdepco_sectors_before, 0)

        # إضافة شركة موازية جديدة تحت مظلة الشركة القابضة
        resp_add = client.post(
            org_url,
            {
                "action": "create_company",
                "code": "EDEPCO",
                "name": "شركة شرق الدلتا لإنتاج الكهرباء",
                "short_name": "شرق الدلتا",
            },
        )
        self.assertEqual(resp_add.status_code, 302)
        edepco = Company.objects.get(code="EDEPCO")
        self.assertEqual(edepco.parent_company_id, holding.id)
        self.assertFalse(edepco.is_holding)
        self.assertTrue(Sector.objects.filter(company=edepco).exists())

        # التأكد من عدم تأثر هيكل شركة غرب الدلتا لإنتاج الكهرباء
        self.assertEqual(Sector.objects.filter(company=wdepco).count(), wdepco_sectors_before)

        # تصفية العرض حسب الشركة الموازية
        resp_filter = client.get(f"{org_url}?company=EDEPCO")
        self.assertEqual(resp_filter.status_code, 200)
        self.assertContains(resp_filter, "شرق الدلتا")

    def test_advanced_archive_search_filters_and_confidentiality_isolation(self):
        client = Client()
        superuser = User.objects.get(username="an")
        regular_user = User.objects.get(username="housing_emp")
        top_secret = ConfidentialityLevel.objects.get(code="TOP_SECRET")
        normal_doc_type = DocumentType.objects.first()

        # إنشاء مستند سري للغاية مرتبط بمصدر مميز
        ts_doc = DocumentService.register_document(
            title="مذكرة فحص سري للغاية لمحطة التحويل",
            doc_type=normal_doc_type,
            confidentiality=top_secret,
            created_by=superuser,
            sender_entity="مكتب الرقابة المركزية",
            summary="معلومات سرية للغاية يجب حجبها عن البحث العام.",
        )

        search_url = reverse("core:archive_search")

        # 1) البحث بالمرشحات المتقدمة من حساب Superuser يجد المستند السري للغاية
        client.force_login(superuser)
        resp_admin = client.get(
            search_url,
            {
                "q": "فحص",
                "source": "الرقابة المركزية",
                "doc_type": str(normal_doc_type.id),
                "confidentiality": str(top_secret.id),
                "date_from": "2020-01-01",
                "date_to": "2035-12-31",
            },
        )
        self.assertEqual(resp_admin.status_code, 200)
        self.assertContains(resp_admin, ts_doc.internal_number)

        # 2) الموظف غير المصرح له لا يرى المستند السري للغاية في نتائج البحث المتقدم
        client.force_login(regular_user)
        resp_emp = client.get(
            search_url,
            {
                "q": "فحص",
                "source": "الرقابة المركزية",
                "confidentiality": str(top_secret.id),
            },
        )
        self.assertEqual(resp_emp.status_code, 200)
        self.assertNotContains(resp_emp, ts_doc.internal_number)

    def test_institutional_pdf_exports_and_permissions(self):
        client = Client()
        superuser = User.objects.get(username="an")
        client.force_login(superuser)

        subj = Subject.objects.first()
        doc = Document.objects.first()
        memo = Memo.objects.first()

        # Subject PDF
        if subj:
            r_sub = client.get(reverse("subjects:subject_export_pdf", args=[subj.id]))
            self.assertEqual(r_sub.status_code, 200)
            self.assertEqual(r_sub["Content-Type"], "application/pdf")
            self.assertTrue(r_sub.content.startswith(b"%PDF-1."))

        # Document PDF
        if doc:
            r_doc = client.get(reverse("documents:document_export_pdf", args=[doc.id]))
            self.assertEqual(r_doc.status_code, 200)
            self.assertEqual(r_doc["Content-Type"], "application/pdf")
            self.assertTrue(r_doc.content.startswith(b"%PDF-1."))

        # Memo PDF
        if memo:
            r_mem = client.get(reverse("subjects:memo_export_pdf", args=[memo.id]))
            self.assertEqual(r_mem.status_code, 200)
            self.assertEqual(r_mem["Content-Type"], "application/pdf")
            self.assertTrue(r_mem.content.startswith(b"%PDF-1."))

        # Report PDF
        r_rep = client.get(reverse("reports:report_detail", args=["overdue-tasks"]) + "?export=pdf")
        self.assertEqual(r_rep.status_code, 200)
        self.assertEqual(r_rep["Content-Type"], "application/pdf")
        self.assertTrue(r_rep.content.startswith(b"%PDF-1."))

    def test_universal_office_preview_docx_xlsx_sanitized(self):
        client = Client()
        superuser = User.objects.get(username="an")
        client.force_login(superuser)

        normal_conf = ConfidentialityLevel.objects.order_by("rank").first()
        doc_type = DocumentType.objects.first()

        docx_bytes = _build_minimal_docx_bytes("تقرير فحص <script>alert(1)</script> معتمد")
        docx_file = SimpleUploadedFile("report.docx", docx_bytes, content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        doc_w = DocumentService.register_document(
            title="ملف وورد تجريبي",
            doc_type=doc_type,
            confidentiality=normal_conf,
            created_by=superuser,
            uploaded_file=docx_file,
        )
        att_w = Attachment.objects.filter(document_version__document=doc_w).first()
        self.assertIsNotNone(att_w)
        self.assertEqual(att_w.preview_kind, "office")
        resp_w = client.get(reverse("documents:attachment_preview", args=[att_w.id]))
        self.assertEqual(resp_w.status_code, 200)
        self.assertContains(resp_w, "تقرير فحص")
        self.assertNotContains(resp_w, "<script>alert(1)</script>")

        xlsx_bytes = _build_minimal_xlsx_bytes("البند", "محطة سيدي كرير")
        xlsx_file = SimpleUploadedFile("sheet.xlsx", xlsx_bytes, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        doc_x = DocumentService.register_document(
            title="جدول إكسل تجريبي",
            doc_type=doc_type,
            confidentiality=normal_conf,
            created_by=superuser,
            uploaded_file=xlsx_file,
        )
        att_x = Attachment.objects.filter(document_version__document=doc_x).first()
        self.assertIsNotNone(att_x)
        resp_x = client.get(reverse("documents:attachment_preview", args=[att_x.id]))
        self.assertEqual(resp_x.status_code, 200)
        self.assertContains(resp_x, "محطة سيدي كرير")

    def test_unified_audit_log_tabs_and_subject_user_tracer(self):
        client = Client()
        superuser = User.objects.get(username="an")
        client.force_login(superuser)

        SystemErrorLog.objects.create(
            component="tests.test_new_features",
            operation="TestException",
            error_message="اختبار تسجيل خطأ فني في شاشة السجلات",
        )
        AuditLog.objects.create(
            actor_user=superuser,
            action="TEST_DENIED_OP",
            model_name="Subject",
            object_id=1,
            outcome="DENIED",
            reason="رفض تجريبي للتدقيق",
        )

        audit_url = reverse("audit:audit_log")
        for tab_name in ["all", "edits", "errors", "events"]:
            resp = client.get(f"{audit_url}?tab={tab_name}")
            self.assertEqual(resp.status_code, 200)

        resp_err = client.get(f"{audit_url}?tab=errors")
        self.assertContains(resp_err, "TestException")
        self.assertContains(resp_err, "TEST_DENIED_OP")

        subj = Subject.objects.first()
        trace_user = User.objects.get(username="hr_sec")
        resp_trace = client.get(
            audit_url,
            {"tab": "tracer", "trace_subject_id": str(subj.id), "trace_user_id": str(trace_user.id)},
        )
        self.assertEqual(resp_trace.status_code, 200)
        self.assertContains(resp_trace, subj.internal_number)

    def test_horizontal_5_step_bar_and_dev_account_switcher(self):
        client = Client()
        superuser = User.objects.get(username="an")
        hr_sec = User.objects.get(username="hr_sec")
        subj = Subject.objects.first()

        # التحقق من المسار التنفيذي الأفقي ذي الـ 5 خطوات في كل الأحوال
        client.force_login(superuser)
        resp_detail = client.get(reverse("subjects:subject_detail", args=[subj.id]))
        self.assertEqual(resp_detail.status_code, 200)
        self.assertContains(resp_detail, 'class="steps"')
        self.assertContains(resp_detail, "التسجيل والمرفقات")
        self.assertContains(resp_detail, "الاعتماد والإغلاق والأرشفة")

        # التحقق من مبدّل الحسابات في وضع الاختبار المحلي وحجبه عند إيقافه
        switch_url = reverse("accounts:switch_user")
        with override_settings(ENABLE_DEV_ACCOUNT_SWITCHER=True):
            resp_sw = client.post(switch_url, {"user_id": hr_sec.id})
            self.assertEqual(resp_sw.status_code, 302)
            self.assertEqual(int(client.session.get("_auth_user_id")), hr_sec.id)

            # التحقق من دعم target_user_id وعدم حدوث 404 عند تمرير معرّف غير موجود
            resp_fallback = client.post(switch_url, {"target_user_id": superuser.id})
            self.assertEqual(resp_fallback.status_code, 302)
            self.assertEqual(int(client.session.get("_auth_user_id")), superuser.id)

            resp_invalid = client.post(switch_url, {"user_id": 9999999})
            self.assertEqual(resp_invalid.status_code, 302)

        with override_settings(ENABLE_DEV_ACCOUNT_SWITCHER=False):
            resp_blocked = client.post(switch_url, {"user_id": superuser.id})
            self.assertEqual(resp_blocked.status_code, 403)

    def test_org_tree_drag_drop_unit_and_user_endpoints(self):
        client = Client()
        superuser = User.objects.get(username="an")
        client.force_login(superuser)

        units = list(OrgUnit.objects.filter(sector__company__code="WDEPCO").order_by("id")[:2])
        if len(units) >= 2:
            src_unit, dst_unit = units[0], units[1]
            # نقل وحدة فرعية عبر السحب والإفلات
            resp_unit = client.post(
                reverse("organization:move_unit"),
                data=json.dumps({"unit_id": src_unit.id, "new_parent_id": dst_unit.id}),
                content_type="application/json",
            )
            self.assertEqual(resp_unit.status_code, 200)
            self.assertTrue(resp_unit.json().get("ok"))
            src_unit.refresh_from_db()
            self.assertEqual(src_unit.parent_id, dst_unit.id)

            # نقل مستخدم إلى وحدة أخرى عبر السحب والإفلات
            target_user = User.objects.filter(is_superuser=False).first()
            if target_user:
                resp_user = client.post(
                    reverse("organization:move_user"),
                    data=json.dumps({"user_id": target_user.id, "target_unit_id": dst_unit.id}),
                    content_type="application/json",
                )
                self.assertEqual(resp_user.status_code, 200)
                self.assertTrue(resp_user.json().get("ok"))
                target_user.refresh_from_db()
                self.assertEqual(target_user.primary_org_unit_id, dst_unit.id)

    def test_subject_detail_open_side_timeline_and_from_to_flow(self):
        client = Client()
        superuser = User.objects.get(username="an")
        subj = Subject.objects.first()
        client.force_login(superuser)

        resp = client.get(reverse("subjects:subject_detail", args=[subj.id]))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode("utf-8")
        # سجل الحركة مفتوح تلقائياً جانباً (غير مخفي بـ hidden على #timeline-box)
        self.assertIn('id="timeline-box"', html)
        self.assertNotIn('id="timeline-box" class="hidden', html)
        self.assertContains(resp, "مراحل السير")
        self.assertContains(resp, "من")
        self.assertContains(resp, "إلى")
