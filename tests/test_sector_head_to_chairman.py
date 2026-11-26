"""رئيس القطاع (ورئيس القطاعات) يرفع لرئيس المجلس خارج سلسلة الموضوع؛ غيره لا (قرار أحمد 17622179)."""
from django.core.management import call_command
from django.test import TestCase
from accounts.models import User
from accounts.services import PermissionService
from core.models import ConfidentialityLevel
from subjects.models import Subject
from subjects.services import SubjectService


class SectorHeadToChairmanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo_data", verbosity=0)

    def _subject(self, creator, conf=None):
        base = Subject.objects.filter(applicant_name="محمد محمود علي").first() or Subject.objects.first()
        return SubjectService.create_subject(
            title="موضوع خارج سلسلة رئيس المجلس",
            transaction_type=base.transaction_type, sector=base.sector, org_unit=base.org_unit,
            confidentiality=conf or base.confidentiality, priority=base.priority,
            created_by=creator, current_owner=creator,
        )

    def _targets(self, username, subject):
        user = User.objects.get(username=username)
        return set(PermissionService.get_allowed_referral_targets(user, subject).values_list("username", flat=True))

    def test_sector_heads_can_target_chairman_outside_chain(self):
        s = self._subject(User.objects.get(username="transfers_emp"))
        for head in ("hr_head", "prod_head", "fin_hr_head"):
            self.assertIn("chairman", self._targets(head, s), head)

    def test_other_roles_still_cannot_target_chairman_outside_chain(self):
        s = self._subject(User.objects.get(username="hr_head"))
        for u in ("transfers_emp", "transfers_sup", "personnel_gm"):
            self.assertNotIn("chairman", self._targets(u, s), u)

    def test_top_secret_not_widened(self):
        ts = ConfidentialityLevel.objects.filter(overrides_hierarchy=True).first()
        s = self._subject(User.objects.get(username="hr_head"), conf=ts)
        self.assertNotIn("chairman", self._targets("hr_head", s))
