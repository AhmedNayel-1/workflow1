"""
اختبارات P2 الشاملة — الأرشفة والتقارير الاثنا عشر والمعاينة الداخلية
والعزل بين القطاعات والعمل دون إنترنت والنسخ الاحتياطي والاستعادة ودورة حياة السيناريوهات الخمسة.
"""
import io
import sqlite3
import tempfile
from datetime import timedelta
from pathlib import Path

from django.apps import apps
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from accounts.models import PermissionCode, Role, RolePermission, User, UserRoleAssignment
from audit.models import ActivityLog, AuditLog
from committees.models import Committee, CommitteeAgendaItem, CommitteeMeeting
from core.backup_utils import create_backup, list_backups, restore_backup, sha256_file
from core.models import (
    ConfidentialityLevel,
    DocumentType,
    PriorityLevel,
    SuspensionReason,
    SystemSequence,
    TransactionType,
)
from decisions.models import Decision, DecisionExecutionItem
from decisions.services import DecisionService
from documents.models import Attachment, Document, DocumentVersion
from documents.services import DocumentService, verify_attachment_integrity
from organization.models import Employee, OrgUnit, OrgUnitType, Sector
from reports.services import REPORT_DEFINITIONS, build_report
from subjects.models import Subject
from subjects.services import SubjectService
from workflow.models import Referral, Task
from workflow.services import WorkflowEngineService


class P2OperationalArchiveTests(TestCase):
    def setUp(self):
        self.tmp_vault = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_vault.cleanup)

        self.conf_normal = ConfidentialityLevel.objects.create(code="NORMAL", name="عادي", rank=1, overrides_hierarchy=False)
        self.conf_secret = ConfidentialityLevel.objects.create(code="CONFIDENTIAL", name="سري", rank=2, overrides_hierarchy=False)
        self.conf_top = ConfidentialityLevel.objects.create(code="TOP_SECRET", name="سري للغاية", rank=3, overrides_hierarchy=True)

        self.prio_normal = PriorityLevel.objects.create(code="NORMAL", name="عادي", rank=1, sla_days=7)

        self.sec_hr = Sector.objects.create(code="HR", name="قطاع الموارد البشرية")
        self.sec_prod = Sector.objects.create(code="PROD", name="قطاع الإنتاج")

        self.ut_sec = OrgUnitType.objects.create(code="SECTOR", name="قطاع", level_order=2)
        self.ut_gd = OrgUnitType.objects.create(code="GENERAL_DIR", name="إدارة عامة", level_order=3)
        self.ut_div = OrgUnitType.objects.create(code="SECTION", name="قسم", level_order=5)

        self.u_hr_sec = OrgUnit.objects.create(code="HR_S", name="رئاسة الموارد البشرية", unit_type=self.ut_sec, sector=self.sec_hr)
        self.u_hr_gd = OrgUnit.objects.create(code="HR_GD", name="شئون الأفراد", unit_type=self.ut_gd, sector=self.sec_hr, parent=self.u_hr_sec)
        self.u_hr_tr = OrgUnit.objects.create(code="HR_TR", name="قسم التنقلات", unit_type=self.ut_div, sector=self.sec_hr, parent=self.u_hr_gd)
        self.u_prod_ops = OrgUnit.objects.create(code="PROD_OP", name="إدارة التشغيل", unit_type=self.ut_div, sector=self.sec_prod)

        self.tx_transfer = TransactionType.objects.create(
            code="TRANSFER", name="نقل موظف", sector=self.sec_hr, requires_committee=True, requires_decision=True, requires_execution_proof=True
        )
        self.tx_ops = TransactionType.objects.create(code="OPS", name="أمر تشغيل", sector=self.sec_prod)
        self.doc_type = DocumentType.objects.create(code="REQUEST", name="طلب موظف")
        self.susp_reason = SuspensionReason.objects.create(code="MISSING_DRUG_TEST", name="نقص تحليل طبي")

        perm_codes = [
            "SUBJECT_CREATE", "SUBJECT_VIEW", "SUBJECT_EDIT", "SUBJECT_SUSPEND",
            "SUBJECT_CLOSE", "DOCUMENT_CREATE", "ATTACHMENT_DOWNLOAD", "REFERRAL_CREATE",
            "TASK_CREATE", "MEMO_CREATE", "APPROVAL_GRANT", "COMMITTEE_MANAGE",
            "DECISION_CREATE", "DECISION_APPROVE", "REPORTS_VIEW", "AUDIT_VIEW",
        ]
        perms = {c: PermissionCode.objects.create(code=c, name=c, category="اختبار") for c in perm_codes}

        self.role_head = Role.objects.create(
            code="SECTOR_HEAD", name="رئيس قطاع",
            allow_hierarchical_view=True, can_view_confidential=True, can_view_top_secret=True, can_download_secret_attachments=True,
        )
        self.role_emp = Role.objects.create(
            code="SPECIALIST", name="موظف مختص",
            allow_hierarchical_view=False, can_view_confidential=False, can_view_top_secret=False, can_download_secret_attachments=False,
        )
        self.role_sup = Role.objects.create(
            code="SUPERVISOR", name="رئيس قسم",
            allow_hierarchical_view=True, can_view_confidential=False, can_view_top_secret=False,
        )
        for p in perms.values():
            RolePermission.objects.create(role=self.role_head, permission=p, max_confidentiality_rank=3)
        for code in ["SUBJECT_VIEW", "DOCUMENT_CREATE", "ATTACHMENT_DOWNLOAD", "REPORTS_VIEW", "MEMO_CREATE"]:
            RolePermission.objects.create(role=self.role_emp, permission=perms[code], max_confidentiality_rank=1)
        for code in ["SUBJECT_CREATE", "SUBJECT_VIEW", "REFERRAL_CREATE", "TASK_CREATE", "REPORTS_VIEW"]:
            RolePermission.objects.create(role=self.role_sup, permission=perms[code], max_confidentiality_rank=1)

        def mk_user(uname, name, emp_no, unit, role, sector, is_super=False):
            emp = Employee.objects.create(employee_number=emp_no, full_name=name, job_title=name, current_unit=unit)
            u = User.objects.create_user(username=uname, password="Pass@12345", first_name=name, employee=emp, is_superuser=is_super, is_system_admin=is_super)
            UserRoleAssignment.objects.create(user=u, role=role, sector=sector, org_unit=unit)
            return u

        self.admin = mk_user("admin", "مدير النظام", "E1", self.u_hr_sec, self.role_head, None, is_super=True)
        self.hr_head = mk_user("hr_head", "رئيس قطاع الموارد البشرية", "E2", self.u_hr_sec, self.role_head, self.sec_hr)
        self.hr_emp = mk_user("hr_emp", "مختص تنقلات", "E3", self.u_hr_tr, self.role_emp, self.sec_hr)
        self.prod_head = mk_user("prod_head", "رئيس قطاع الإنتاج", "E4", self.u_prod_ops, self.role_head, self.sec_prod)

        # موضوعات ومستندات عبر قطاعي HR و PROD
        self.hr_sub = SubjectService.create_subject(
            title="موضوع نقل بالوارد البشرية", description="تفاصيل", transaction_type=self.tx_transfer,
            sector=self.sec_hr, org_unit=self.u_hr_tr, confidentiality=self.conf_normal, priority=self.prio_normal,
            created_by=self.hr_head, current_owner=self.hr_emp,
        )
        self.hr_suspended_sub = SubjectService.create_subject(
            title="موضوع معلق للاستيفاء", description="نقص", transaction_type=self.tx_transfer,
            sector=self.sec_hr, org_unit=self.u_hr_tr, confidentiality=self.conf_normal, priority=self.prio_normal,
            created_by=self.hr_head, current_owner=self.hr_emp,
        )
        SubjectService.suspend_subject(
            subject=self.hr_suspended_sub, user=self.hr_head, reason_ref=self.susp_reason,
            reason_details="تحليل سلبي مطلوب", required_from="الشئون الطبية", required_item="شهادة التحليل",
        )
        self.prod_sub = SubjectService.create_subject(
            title="موضوع صيانة قطاع الإنتاج", description="بيانات إنتاج", transaction_type=self.tx_ops,
            sector=self.sec_prod, org_unit=self.u_prod_ops, confidentiality=self.conf_normal, priority=self.prio_normal,
            created_by=self.prod_head, current_owner=self.prod_head,
        )

    def test_all_12_reports_build_and_excel_and_print(self):
        today = timezone.localdate()
        # مهمة متأخرة ومهمة مكتملة
        Task.objects.create(
            subject=self.hr_sub, title="مهمة متأخرة", assigned_to=self.hr_emp,
            assigned_unit=self.u_hr_tr, assigned_by=self.hr_head, priority=self.prio_normal,
            due_date=today - timedelta(days=3), status=Task.TaskStatus.IN_PROGRESS,
        )
        Task.objects.create(
            subject=self.hr_sub, title="مهمة مكتملة", assigned_to=self.hr_emp,
            assigned_unit=self.u_hr_tr, assigned_by=self.hr_head, priority=self.prio_normal,
            due_date=today - timedelta(days=1), status=Task.TaskStatus.COMPLETED, completed_at=timezone.now(),
        )

        # لجنة وبند وقرار وبند تنفيذ غير مكتمل
        committee = Committee.objects.create(code="C1", name="لجنة شئون العاملين", sector=self.sec_hr, chair=self.hr_head)
        meeting = CommitteeMeeting.objects.create(
            committee=committee, meeting_number="1", meeting_date=today, created_by=self.hr_head
        )
        CommitteeAgendaItem.objects.create(
            meeting=meeting, subject=self.hr_sub, recommendation="الموافقة",
            resolution_type=CommitteeAgendaItem.ResolutionType.APPROVED, resolution_text="ووفق عليه", recorded_by=self.hr_head,
        )
        dec = Decision.objects.create(
            decision_number=SystemSequence.next_number("DECISION", "DEC"),
            subject=self.hr_sub, title="قرار نقل", body="يُنقل...",
            issuing_authority="رئيس القطاع", approving_authority="رئيس القطاع",
            status=Decision.Status.EXECUTING, created_by=self.hr_head, approved_by=self.hr_head, issued_date=today,
        )
        DecisionExecutionItem.objects.create(
            decision=dec, assigned_unit=self.u_hr_tr, assigned_user=self.hr_emp,
            required_action="إخلاء الطرف", due_date=today - timedelta(days=1),
            execution_status=DecisionExecutionItem.ExecutionStatus.PENDING,
        )

        self.client.force_login(self.hr_head)
        for rep in REPORT_DEFINITIONS:
            url = reverse("reports:report_detail", args=[rep.slug])
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, f"Report {rep.slug} failed")

            # فحص Excel (.xlsx)
            xl_resp = self.client.get(f"{url}?export=xlsx")
            self.assertEqual(xl_resp.status_code, 200)
            self.assertIn("spreadsheetml", xl_resp["Content-Type"])
            wb = load_workbook(io.BytesIO(xl_resp.content))
            ws = wb.active
            self.assertTrue(ws.views.sheetView[0].rightToLeft)

            # فحص الطباعة A4
            pr_resp = self.client.get(f"{url}?print=1")
            self.assertEqual(pr_resp.status_code, 200)
            self.assertNotIn("cdn.tailwindcss.com", pr_resp.content.decode("utf-8"))

    def test_cross_sector_report_isolation_and_tampering(self):
        # مستخدم HR يرى فقط HR ولا يرى PROD عند محاولة التلاعب بـ ?sector=
        self.client.force_login(self.hr_head)
        payload = build_report("subjects-status", self.hr_head, {})
        hr_nums = {r["internal_number"] for r in payload["rows"]}
        self.assertIn(self.hr_sub.internal_number, hr_nums)
        self.assertNotIn(self.prod_sub.internal_number, hr_nums)

        tamper_resp = self.client.get(reverse("reports:report_detail", args=["subjects-status"]) + f"?sector={self.sec_prod.id}")
        self.assertEqual(tamper_resp.status_code, 403)

        # الموظف العادي محروم من تقرير حركة المستندات السرية من AuditLog
        self.client.force_login(self.hr_emp)
        audit_resp = self.client.get(reverse("reports:report_detail", args=["confidential-audit"]))
        self.assertEqual(audit_resp.status_code, 403)

    def test_avg_completion_time_uses_reliable_events_only(self):
        # إغلاق hr_sub وتسجيل فارق زمني موثوق عبر ActivityLog + استبعاد غير المغلقين (hr_suspended_sub)
        closed_sub = SubjectService.create_subject(
            title="موضوع مغلق بدقة", description="اختبار", transaction_type=self.tx_transfer,
            sector=self.sec_hr, org_unit=self.u_hr_tr, confidentiality=self.conf_normal, priority=self.prio_normal,
            created_by=self.hr_head, current_owner=self.hr_head,
        )
        # حذف requiring execution proof عبر نوع معاملة لا يشترط قرار لإغلاقه
        tx_simple = TransactionType.objects.create(code="SIMPLE", name="بسيط", sector=self.sec_hr)
        closed_sub.transaction_type = tx_simple
        closed_sub.save()
        SubjectService.close_subject(subject=closed_sub, user=self.hr_head, closure_notes="تم الإنجاز")

        # ضبط حدث الإنشاء ليكون قبل 48 ساعة للتحقق العددي
        create_log = ActivityLog.objects.filter(subject=closed_sub, action_type="SUBJECT_CREATED").first()
        ActivityLog.objects.filter(id=create_log.id).update(created_at=timezone.now() - timedelta(hours=48))

        report = build_report("avg-completion-time", self.hr_head, {})
        self.assertEqual(report["meta"]["evaluated_count"], 1)
        self.assertGreaterEqual(report["meta"]["avg_hours"], 47.0)
        # تأكد من عدم إدراج الموضوع المفتوح/المعلق
        nums = [r["internal_number"] for r in report["rows"]]
        self.assertEqual(nums, [closed_sub.internal_number])

    def test_attachment_validation_integrity_preview_and_version_immutability(self):
        with override_settings(SECURE_STORAGE_ROOT=Path(self.tmp_vault.name)):
            # 1. رفض ملف منتحل (امتداد pdf بمحتوى تنفيذي MZ)
            fake_exe = SimpleUploadedFile("virus.pdf", b"MZ\x90\x00FAKE_EXE", content_type="application/pdf")
            with self.assertRaises(ValidationError):
                DocumentService.register_document(
                    title="ملف مشبوه", doc_type=self.doc_type, confidentiality=self.conf_normal,
                    created_by=self.hr_head, uploaded_file=fake_exe,
                )

            # 2. حفظ PDF سليم سري وتأكيد المعاينة الداخلية وتسجيل AuditLog وعدم تسريب المسار الحقيقي
            valid_pdf = SimpleUploadedFile("secret_memo.pdf", b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n", content_type="application/pdf")
            doc = DocumentService.register_document(
                title="مستند سري سليم", doc_type=self.doc_type, confidentiality=self.conf_secret,
                created_by=self.hr_head, subject=self.hr_sub, uploaded_file=valid_pdf, is_approved=True,
            )
            att = doc.versions.first().attachments.first()
            ver = att.document_version

            # منع تعديل أو حذف النسخة المعتمدة
            ver.status_label = "تعديل غير مشروع"
            with self.assertRaises(PermissionDenied):
                ver.save()
            with self.assertRaises(PermissionDenied):
                ver.delete()
            with self.assertRaises(PermissionDenied):
                att.delete()

            # إصدار نسخة v2 جديدة مع سبب تعديل إلزامي والاحتفاظ بالنسخة v1
            v2_img = SimpleUploadedFile(
                "page2.png",
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde",
                content_type="image/png",
            )
            v2 = DocumentService.create_new_version(
                document=doc, user=self.hr_head, change_reason="إضافة ملحق توضيحي", uploaded_files=[v2_img], is_approved=True
            )
            self.assertEqual(doc.versions.count(), 2)
            self.assertEqual(v2.version_number, 2)

            # الموظف العادي ممنوع من معاينة السري، ورئيس القطاع مسموح وتُسجل الحركة في AuditLog
            self.client.force_login(self.hr_emp)
            denied_prev = self.client.get(reverse("documents:attachment_preview", args=[att.id]))
            self.assertEqual(denied_prev.status_code, 403)

            self.client.force_login(self.hr_head)
            ok_prev = self.client.get(reverse("documents:attachment_preview", args=[att.id]))
            self.assertEqual(ok_prev.status_code, 200)
            html = ok_prev.content.decode("utf-8")
            self.assertIn("<iframe", html)
            self.assertNotIn(att.stored_relative_path, html)
            self.assertTrue(
                AuditLog.objects.filter(action="DOCUMENT_PREVIEW", model_name="Attachment", object_id=str(att.id), outcome="SUCCESS").exists()
            )

            # العبث بالملف على القرص يؤدي لاكتشاف تلف SHA-256 ومنع التحميل/المعاينة
            full_path = Path(self.tmp_vault.name) / att.stored_relative_path
            full_path.write_bytes(b"TAMPERED_CONTENT")
            integrity = verify_attachment_integrity(att)
            self.assertFalse(integrity["ok"])
            self.assertEqual(integrity["status"], "TAMPERED")
            tampered_dl = self.client.get(reverse("documents:attachment_download", args=[att.id]))
            self.assertEqual(tampered_dl.status_code, 403)
            self.assertTrue(
                AuditLog.objects.filter(action="ATTACHMENT_INTEGRITY_FAILED", object_id=str(att.id)).exists()
            )

    def test_offline_no_cdn_and_erd_completeness(self):
        project_root = Path(__file__).resolve().parent.parent
        # التحقق من خلو جميع القوالب من أي CDN أو روابط إنترنت
        for html_file in (project_root / "templates").rglob("*.html"):
            txt = html_file.read_text(encoding="utf-8")
            self.assertNotIn("cdn.tailwindcss.com", txt, str(html_file))
            self.assertNotIn("fonts.googleapis.com", txt, str(html_file))

        self.assertTrue((project_root / "static" / "css" / "app.css").is_file())

        # التحقق من شمول docs/ERD.md لجميع النماذج الفعلية
        erd_text = (project_root / "docs" / "ERD.md").read_text(encoding="utf-8")
        for app_label in ["core", "organization", "accounts", "subjects", "documents", "workflow", "committees", "decisions", "audit", "notifications"]:
            cfg = apps.get_app_config(app_label)
            for model in cfg.get_models():
                self.assertIn(model.__name__, erd_text, f"Model {model.__name__} missing in ERD.md")

    def test_sqlite_backup_and_restore_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            live_db = root / "live.sqlite3"
            live_vault = root / "live_vault"
            backups_dir = root / "external_backups"
            live_vault.mkdir(parents=True)

            # إنشاء قاعدة بيانات حية وملف مرفق في الخزينة
            conn = sqlite3.connect(str(live_db))
            conn.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, val TEXT)")
            conn.execute("INSERT INTO records (val) VALUES ('قرار معتمد 2026')")
            conn.commit()
            conn.close()
            sample_file = live_vault / "2026" / "doc.pdf"
            sample_file.parent.mkdir(parents=True)
            sample_file.write_bytes(b"%PDF-1.4 OK")
            orig_hash = sha256_file(sample_file)

            snap = create_backup(
                base_dir=root / "code_dir",
                backup_root=backups_dir,
                vault_root=live_vault,
                sqlite_path=live_db,
                keep_last=30,
            )

            # إتلاف البيانات الحية عمداً بعد النسخة الاحتياطية
            conn = sqlite3.connect(str(live_db))
            conn.execute("DELETE FROM records")
            conn.commit()
            conn.close()
            sample_file.write_bytes(b"CORRUPTED")

            # رفض الاستعادة بدون تأكيد RESTORE
            with self.assertRaises(PermissionError):
                restore_backup(snap["snapshot_dir"], confirm_token="NO", base_dir=root / "code_dir", backup_root=backups_dir, vault_root=live_vault, sqlite_path=live_db)

            # استعادة كاملة ومتطابقة
            restore_backup(
                snap["snapshot_dir"], confirm_token="RESTORE",
                base_dir=root / "code_dir", backup_root=backups_dir, vault_root=live_vault, sqlite_path=live_db,
            )
            conn = sqlite3.connect(str(live_db))
            restored_rows = conn.execute("SELECT val FROM records").fetchall()
            conn.close()
            self.assertEqual(restored_rows, [("قرار معتمد 2026",)])
            self.assertEqual(sha256_file(sample_file), orig_hash)
            self.assertEqual(len(list_backups(backups_dir)), 1)
