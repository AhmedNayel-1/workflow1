"""اختبارات انحدار لما كشفه الفحص الوظيفي الموسّع (نسخة معاد بناؤها)."""
from django.core.management import call_command
from django.test import Client, TestCase

from accounts.models import User
from core.models import SystemSequence
from decisions.models import Decision
from documents.models import Document


class VerificationRegressions(TestCase):
    @classmethod
    def setUpTestData(cls):
        with cls.captureOnCommitCallbacks(execute=True):
            call_command("seed_demo_data")

    def test_decision_print_without_approver_does_not_crash(self):
        from subjects.models import Subject
        subj = Subject.objects.first()
        dec = Decision.objects.create(
            subject=subj, decision_number="DEC-2026-09999", title="مسودة", body="نص",
            decision_type=Decision.DecisionType.GENERAL, created_by=User.objects.get(username="an"),
        )
        self.assertIsNone(dec.approved_by)
        c = Client()
        c.force_login(User.objects.get(username="an"))
        resp = c.get(f"/decisions/{dec.id}/print/")
        self.assertEqual(resp.status_code, 200)

    def test_sequence_sync_prevents_number_collision(self):
        SystemSequence.objects.filter(key="DOCUMENT").update(last_number=0)
        SystemSequence.sync_all()
        top = max(int(n.rsplit("-", 1)[1]) for n in Document.objects.values_list("internal_number", flat=True))
        self.assertGreaterEqual(SystemSequence.objects.get(key="DOCUMENT").last_number, top)
        nxt = SystemSequence.next_number("DOCUMENT", "DOC")
        self.assertFalse(Document.objects.filter(internal_number=nxt).exists())

    def test_403_uses_friendly_template(self):
        c = Client()
        c.force_login(User.objects.get(username="transfers_sup"))
        from subjects.models import Subject
        ts = Subject.objects.get(confidentiality__code="TOP_SECRET")
        resp = c.get(f"/subjects/{ts.id}/")
        self.assertEqual(resp.status_code, 403)
        self.assertContains(resp, "غير مصرح بهذا الإجراء", status_code=403)


class SectorIsolationAndSequenceTests(TestCase):
    """عزل القطاعات (لا توجد بيانات تشغيلية لشركة ثانية في البذر، فنختبر القطاع) وتكرار مزامنة العدادات."""

    @classmethod
    def setUpTestData(cls):
        with cls.captureOnCommitCallbacks(execute=True):
            call_command("seed_demo_data")

    def test_user_of_other_sector_cannot_see_hr_subject_document_or_list(self):
        from subjects.models import Subject
        from organization.models import Sector
        hr = Sector.objects.get(code="HR")
        subj = Subject.objects.filter(sector=hr, confidentiality__code="NORMAL").first()
        self.assertIsNotNone(subj)
        c = Client()
        c.force_login(User.objects.get(username="housing_sup"))  # قطاع FIN_HR
        self.assertEqual(c.get(f"/subjects/{subj.id}/").status_code, 403)
        listing = c.get("/subjects/")
        self.assertNotContains(listing, subj.internal_number)
        from documents.models import SubjectDocumentLink
        link = SubjectDocumentLink.objects.filter(subject=subj).select_related("document").first()
        if link:
            self.assertIn(c.get(f"/documents/{link.document_id}/").status_code, (403, 404))
        # وعكسياً: صاحب القطاع يراه
        c2 = Client()
        c2.force_login(User.objects.get(username="hr_head"))
        self.assertEqual(c2.get(f"/subjects/{subj.id}/").status_code, 200)

    def test_sync_all_is_idempotent_and_never_lowers_counters(self):
        first = SystemSequence.sync_all()
        before = dict(SystemSequence.objects.values_list("key", "last_number"))
        second = SystemSequence.sync_all()
        self.assertEqual(second, {})
        after = dict(SystemSequence.objects.values_list("key", "last_number"))
        self.assertEqual(before, after)
        SystemSequence.objects.filter(key="SUBJECT").update(last_number=10_000)
        SystemSequence.sync_all()
        self.assertEqual(SystemSequence.objects.get(key="SUBJECT").last_number, 10_000)


class NullActorRendering(TestCase):
    """صفحات لا يجوز أن تنهار عند غياب المستخدم المرتبط (معتمِد، فاعل نظام)."""

    @classmethod
    def setUpTestData(cls):
        with cls.captureOnCommitCallbacks(execute=True):
            call_command("seed_demo_data")

    def test_draft_memo_print_does_not_crash(self):
        from subjects.models import Memo, Subject
        admin = User.objects.get(username="an")
        memo = Memo.objects.create(subject=Subject.objects.first(), memo_number="MEM-2026-09999", title="مسودة",
                                   directed_to="x", body="نص", author=admin)
        self.assertIsNone(memo.approved_by)
        c = Client()
        c.force_login(admin)
        self.assertEqual(c.get(f"/subjects/memos/{memo.id}/print/").status_code, 200)
        self.assertEqual(c.get(f"/subjects/memos/{memo.id}/export-pdf/").status_code, 200)

    def test_audit_pages_render_with_system_actor(self):
        from audit.models import AuditLog
        from subjects.models import Subject
        AuditLog.objects.create(actor_user=None, action="SYSTEM_TEST", model_name="Subject", object_id="1")
        subj = Subject.objects.first()
        c = Client()
        c.force_login(User.objects.get(username="an"))
        self.assertEqual(c.get("/audit/").status_code, 200)
        self.assertEqual(c.get(f"/audit/?subject={subj.id}").status_code, 200)
        self.assertEqual(c.get(f"/subjects/{subj.id}/").status_code, 200)
