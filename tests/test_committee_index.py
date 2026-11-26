"""فهرس اللجان: رابط منظَّم اختياري بين قرار اللجنة الوارد (تعليق/استيفاء) واللجنة، مع احترام صلاحية رؤية الموضوع."""
from django.core.management import call_command
from django.test import Client, TestCase

from accounts.models import User
from committees.models import Committee
from subjects.models import Subject, SubjectSuspension
from subjects.services import SubjectService


class CommitteeIndex(TestCase):
    @classmethod
    def setUpTestData(cls):
        with cls.captureOnCommitCallbacks(execute=True):
            call_command("seed_demo_data")

    def u(self, n):
        return User.objects.get(username=n)

    def _open(self):
        return Subject.objects.exclude(status__in=["SUSPENDED", "CLOSED"]).filter(confidentiality__rank__lte=1).order_by("id").first()

    def _suspend(self, subject, committee):
        return SubjectService.suspend_subject(
            subject=subject, user=self.u("hr_head"), reason_details="بانتظار قرار اللجنة",
            required_from="لجنة", required_item="قرار اللجنة", committee=committee,
        )

    def test_committee_is_optional_and_old_free_text_is_not_linked(self):
        s = self._open()
        sp = self._suspend(s, None)
        self.assertIsNone(sp.committee)

    def test_linked_topic_listed_for_viewer_and_hidden_for_non_viewer(self):
        c = Committee.objects.get(name="لجنة شئون العاملين")
        s = self._open()
        self._suspend(s, c)
        self.assertEqual(c.incoming_suspensions.count(), 1)
        cl = Client(); cl.force_login(self.u("hr_head"))
        self.assertIn(s.title, cl.get("/committees/").content.decode())
        from accounts.services import PermissionService
        blocked = [u for u in User.objects.filter(is_active=True) if not PermissionService.can_view_subject(u, s)]
        self.assertTrue(blocked)
        checked = 0
        for u in blocked:
            cl2 = Client(); cl2.force_login(u)
            resp = cl2.get("/committees/")
            if resp.status_code == 200:
                checked += 1
                self.assertNotIn(s.title, resp.content.decode())
        self.assertTrue(checked)
