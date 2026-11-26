"""عزل حقيقي بين شركتين: شركة ثانية بمستخدمين بأدوار عليا (رئيس قطاع / مدير عام / مشرف) لا يرون شيئاً من شركة WDEPCO.
الاختبار يبني الشركة الثانية في الاختبار نفسه ولا يعتمد على بيانات البذر."""
import re

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase

from accounts.models import Role, User, UserRoleAssignment
from documents.models import Attachment
from organization.models import Company, Employee, OrgUnit, Sector
from core.models import ConfidentialityLevel
from subjects.models import Subject

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


class CrossCompanyIsolation(TestCase):
    @classmethod
    def setUpTestData(cls):
        with cls.captureOnCommitCallbacks(execute=True):
            call_command("seed_demo_data")
        other = Company.objects.create(code="OTHERCO", name="شركة أخرى للاختبار")
        cls.sector = Sector.objects.create(code="OTH_S", name="قطاع الشركة الأخرى", company=other)
        base_unit = OrgUnit.objects.get(code="UNIT_TRANSFERS")
        cls.unit = OrgUnit.objects.create(code="OTH_U", name="وحدة أخرى", unit_type=base_unit.unit_type, sector=cls.sector)
        cls.outsiders = []
        for i, role_code in enumerate(["SECTOR_HEAD", "GENERAL_MANAGER", "SUPERVISOR", "SPECIALIST", "SECTOR_DIR_ADMIN"]):
            emp = Employee.objects.create(employee_number=f"OTH{i}", full_name=f"مستخدم {role_code}", job_title="اختبار", current_unit=cls.unit)
            u = User.objects.create_user(username=f"oth_{role_code.lower()}", password="x12345678", employee=emp)
            UserRoleAssignment.objects.create(user=u, role=Role.objects.get(code=role_code), sector=cls.sector, org_unit=cls.unit)
            cls.outsiders.append(u)

        # بيانات WDEPCO بكل درجات السرية، بمرفق حقيقي، يصنعها الأدمن عبر الواجهة
        admin = User.objects.get(username="an")
        c = Client()
        c.force_login(admin)
        from core.models import TransactionType, PriorityLevel, DocumentType
        hr_unit = OrgUnit.objects.get(code="UNIT_HR_SECTOR")
        cls.subjects = {}
        for code in ("NORMAL", "CONFIDENTIAL", "TOP_SECRET"):
            conf = ConfidentialityLevel.objects.get(code=code)
            title = f"ISOTITLE-{code}-XYZ"
            resp = c.post("/subjects/create/", {
                "compose_mode": "document", "title": title,
                "transaction_type_id": TransactionType.objects.filter(is_active=True).first().id,
                "sector_id": hr_unit.sector_id, "org_unit_id": hr_unit.id, "confidentiality_id": conf.id,
                "priority_id": PriorityLevel.objects.first().id, "description": "d", "applicant_name": "a",
                "external_source": "e", "status": "INCOMING", "due_date": "2026-12-30",
                "initial_doc_type_id": DocumentType.objects.first().id, "initial_doc_title": f"DOCTITLE-{code}",
                "initial_attachment": SimpleUploadedFile("t.pdf", PDF, content_type="application/pdf"),
            })
            cls.subjects[code] = Subject.objects.get(title=title)

    def _urls(self, subj):
        att = Attachment.objects.filter(document_version__document__subjectdocumentlink__subject=subj).first()
        doc = att.document_version.document if att else None
        urls = [f"/subjects/{subj.id}/", f"/subjects/{subj.id}/preview-json/", f"/subjects/{subj.id}/export-pdf/"]
        if att:
            urls += [f"/documents/{doc.id}/", f"/documents/{doc.id}/export-pdf/",
                     f"/documents/attachments/{att.id}/download/", f"/documents/attachments/{att.id}/preview/"]
        return urls

    def test_attachments_exist_for_the_fixture(self):
        for code, subj in self.subjects.items():
            self.assertTrue(len(self._urls(subj)) > 3, f"لا مرفق للموضوع {code}")

    def test_outsiders_get_no_access_to_any_wdepco_object(self):
        for user in self.outsiders:
            c = Client()
            c.force_login(user)
            for code, subj in self.subjects.items():
                for url in self._urls(subj):
                    resp = c.get(url)
                    self.assertIn(resp.status_code, (403, 404), f"{user.username} {code} {url} -> {resp.status_code}")
                    self.assertNotIn(b"%PDF-1.4\n1 0 obj", resp.content[:200] if resp.status_code == 200 else b"")

    def test_outsiders_cannot_discover_wdepco_through_lists_search_reports_audit(self):
        needles = [f"ISOTITLE-{c}-XYZ" for c in self.subjects] + [s.internal_number for s in self.subjects.values()]
        pages = ["/", "/subjects/", "/documents/", "/decisions/", "/notifications/", "/workflow/referrals/", "/workflow/tasks/",
                 "/search/?q=ISOTITLE", "/archive-search/?q=ISOTITLE", "/reports/", "/committees/", "/audit/",
                 "/subjects/?q=ISOTITLE", "/notifications/drawer-state/", "/chat/state/"]
        from reports.services import REPORT_MAP
        pages += [f"/reports/{slug}/" for slug in REPORT_MAP]
        for user in self.outsiders:
            c = Client()
            c.force_login(user)
            for url in pages:
                resp = c.get(url)
                self.assertNotEqual(resp.status_code, 500, f"{user.username} {url}")
                body = resp.content.decode("utf-8", "ignore")
                # نتجاهل صدى استعلام البحث نفسه
                body = re.sub(r"ISOTITLE(?=[^-])", "", body)
                for n in needles:
                    self.assertNotIn(n, body, f"{user.username} رأى {n} في {url}")

    def test_outsider_cannot_act_on_wdepco_subject(self):
        subj = self.subjects["NORMAL"]
        u = User.objects.get(username="oth_sector_head")
        c = Client()
        c.force_login(u)
        before = subj.status
        for action, extra in [("add_annotation", {"annotation_text": "x"}), ("close_subject", {"closure_notes": "x"}),
                              ("update_meta", {"title": "HACK", "version_lock": subj.version_lock}),
                              ("suspend", {"reason_details": "x"})]:
            resp = c.post(f"/subjects/{subj.id}/", {"action": action, **extra})
            self.assertIn(resp.status_code, (302, 403, 404))
        subj.refresh_from_db()
        self.assertEqual(subj.title, "ISOTITLE-NORMAL-XYZ")
        self.assertEqual(subj.status, before)
        resp = c.post(f"/workflow/referrals/create/{subj.id}/", {"routing_mode": "DIRECT", "purpose": "FOR_EXECUTION",
                      "target_user_ids": [u.id], "notes": "x"})
        self.assertIn(resp.status_code, (302, 403, 404))
        from workflow.models import Referral
        self.assertFalse(Referral.objects.filter(subject=subj, referred_by=u).exists())

    def test_wdepco_hr_head_still_sees_own_data(self):
        c = Client()
        c.force_login(User.objects.get(username="hr_head"))
        self.assertEqual(c.get(f"/subjects/{self.subjects['NORMAL'].id}/").status_code, 200)

    def test_control_insiders_do_see_the_needles(self):
        """ضابط الاختبار: لو لم يرَ الداخليون النصوص المفتاحية لكان اختبار الغرباء بلا معنى."""
        c = Client()
        c.force_login(User.objects.get(username="an"))
        body = c.get("/subjects/").content.decode()
        self.assertIn("ISOTITLE-NORMAL-XYZ", body)
        c.force_login(User.objects.get(username="hr_head"))
        self.assertIn("ISOTITLE-NORMAL-XYZ", c.get("/subjects/").content.decode())
        subj = self.subjects["NORMAL"]
        att = Attachment.objects.filter(document_version__document__subjectdocumentlink__subject=subj).first()
        self.assertEqual(c.get(f"/documents/attachments/{att.id}/download/").status_code, 200)

    def test_invariant_attachment_or_document_access_implies_subject_access(self):
        """لا مستند ولا مرفق يُفتح لمن لا يرى موضوعه (لكل المستخدمين ولكل درجات السرية)."""
        for user in User.objects.filter(is_superuser=False, is_active=True):
            c = Client()
            c.force_login(user)
            for code, subj in self.subjects.items():
                if c.get(f"/subjects/{subj.id}/").status_code == 200:
                    continue
                att = Attachment.objects.filter(document_version__document__subjectdocumentlink__subject=subj).first()
                doc_id = att.document_version.document_id
                for url in (f"/documents/attachments/{att.id}/download/", f"/documents/attachments/{att.id}/preview/",
                            f"/documents/{doc_id}/", f"/documents/{doc_id}/export-pdf/"):
                    self.assertIn(c.get(url).status_code, (403, 404), f"تسريب: {user.username} {code} {url}")

    def test_memo_and_decision_print_pdf_respect_subject_access(self):
        from subjects.models import Memo
        from decisions.models import Decision
        subj = self.subjects["TOP_SECRET"]
        admin_c = Client()
        admin_c.force_login(User.objects.get(username="an"))
        admin_c.post(f"/subjects/{subj.id}/", {"action": "add_memo", "memo_type": "PRESENTATION", "directed_to_select": "رئيس مجلس الإدارة",
                                               "memo_title": "ISOMEMO", "memo_body": "نص"})
        memo = Memo.objects.get(subject=subj)
        admin_c.post(f"/decisions/create/{subj.id}/", {"decision_type": "GENERAL", "title": "ISODEC", "body": "b",
                                                       "issuing_authority": "a", "approving_authority": "b"})
        dec = Decision.objects.get(subject=subj)
        # الأدمن يفتحها (ضابط)
        self.assertEqual(admin_c.get(f"/subjects/memos/{memo.id}/print/").status_code, 200)
        self.assertEqual(admin_c.get(f"/decisions/{dec.id}/print/").status_code, 200)
        urls = [f"/subjects/memos/{memo.id}/print/", f"/subjects/memos/{memo.id}/export-pdf/",
                f"/decisions/{dec.id}/", f"/decisions/{dec.id}/print/"]
        for user in list(self.outsiders) + [User.objects.get(username=n) for n in ("personnel_gm", "transfers_sup", "hr_sec", "chairman")]:
            c = Client()
            c.force_login(user)
            for url in urls:
                self.assertIn(c.get(url).status_code, (403, 404), f"{user.username} {url}")
