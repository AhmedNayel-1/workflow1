"""اختبارات إصلاحات سيناريوهات أحمد (إحالة مباشرة، إعادة العهدة، التوزيع، التعليق، الإغلاق، الاستلام، سري للغاية)."""
from django.core.management import call_command
from django.test import Client, TestCase

from accounts.models import User
from accounts.services import PermissionService
from core.models import ConfidentialityLevel
from decisions.models import Decision
from organization.models import OrgUnit
from subjects.models import Subject
from workflow.models import Referral, ReferralRecipient
from workflow.services import WorkflowEngineService


class WorkflowFixes(TestCase):
    @classmethod
    def setUpTestData(cls):
        with cls.captureOnCommitCallbacks(execute=True):
            call_command("seed_demo_data")

    def u(self, n):
        return User.objects.get(username=n)

    def subj(self):
        return Subject.objects.filter(applicant_name="محمد محمود علي").first()

    def test_sector_head_and_gm_can_refer_directly_to_employee(self):
        s = self.subj()
        self.assertIn(self.u("transfers_emp"), list(PermissionService.get_allowed_referral_targets(self.u("hr_head"), s)))
        self.assertIn(self.u("transfers_emp"), list(PermissionService.get_allowed_referral_targets(self.u("personnel_gm"), s)))
        # لا يتخطى القطاع: موظف الإسكان (قطاع آخر) خارج النطاق
        self.assertNotIn(self.u("housing_emp"), list(PermissionService.get_allowed_referral_targets(self.u("personnel_gm"), s)))

    def test_employee_can_return_custody_upward_but_not_sideways(self):
        s = self.subj()
        r = WorkflowEngineService.create_referral(
            subject=s, referred_by=self.u("chairman"), routing_mode="DIRECT", purpose="FOR_EXECUTION",
            target_users=[self.u("hr_head")], enforce_hierarchy=False)
        WorkflowEngineService.create_referral(
            subject=s, referred_by=self.u("hr_head"), routing_mode="DIRECT", purpose="FOR_EXECUTION",
            target_users=[self.u("transfers_emp")], enforce_hierarchy=False)
        t = set(PermissionService.get_allowed_referral_targets(self.u("transfers_emp"), s).values_list("username", flat=True))
        self.assertIn("chairman", t)
        self.assertNotIn("penalties_emp", t)

    def test_employee_and_supervisor_hold_suspend_close_distribute_permissions(self):
        s = self.subj()
        rank = s.confidentiality.rank
        for who, code in (("transfers_emp", "SUBJECT_SUSPEND"), ("transfers_emp", "SUBJECT_CLOSE"),
                          ("transfers_emp", "DECISION_DISTRIBUTE"), ("transfers_sup", "DECISION_DISTRIBUTE"),
                          ("transfers_sec", "DECISION_DISTRIBUTE")):
            self.assertTrue(PermissionService.user_has_permission(self.u(who), code, sector=s.sector, confidentiality_rank=rank, subject=s), (who, code))
        # لكن لا اعتماد قرار لهم
        for who in ("transfers_emp", "transfers_sup"):
            self.assertFalse(PermissionService.user_has_permission(self.u(who), "DECISION_APPROVE", sector=s.sector, confidentiality_rank=rank, subject=s))

    def test_receive_button_does_not_complete_referral(self):
        s = self.subj()
        s.current_owner = self.u("hr_head"); s.save(update_fields=["current_owner"])
        ref = WorkflowEngineService.create_referral(
            subject=s, referred_by=self.u("chairman"), routing_mode="DIRECT", purpose="FOR_EXECUTION",
            target_users=[self.u("personnel_gm")], enforce_hierarchy=False)
        rec = ref.recipients.get()
        c = Client(); c.force_login(self.u("personnel_gm"))
        c.post(f"/workflow/referrals/recipient/{rec.id}/respond/", {"action": "acknowledge"}) if False else None
        from django.urls import reverse
        c.post(reverse("workflow:referral_respond", args=[rec.id]), {"action": "complete"}.__class__({"action": "acknowledge"}))
        rec.refresh_from_db()
        self.assertEqual(rec.status, ReferralRecipient.RecipientStatus.RECEIVED)

    def test_top_secret_viewers_match_latest_matrix(self):
        base = self.subj()
        top = ConfidentialityLevel.objects.filter(overrides_hierarchy=True).first()
        s = Subject.objects.create(
            internal_number="TS-FIX-1", title="بيان سري للغاية", transaction_type=base.transaction_type,
            sector=base.sector, org_unit=base.org_unit, confidentiality=top, priority=base.priority,
            created_by=self.u("hr_head"), current_owner=self.u("hr_head"))
        WorkflowEngineService.create_referral(
            subject=s, referred_by=self.u("hr_head"), routing_mode="DIRECT", purpose="FOR_EXECUTION",
            target_users=[self.u("transfers_emp")], enforce_hierarchy=False)
        view = lambda n: PermissionService.can_view_subject(self.u(n), s)
        for n in ("hr_head", "hr_sec", "personnel_gm", "transfers_emp"):
            self.assertTrue(view(n), n)
        for n in ("transfers_sup", "transfers_sec", "gm_sec", "penalties_emp", "housing_sup"):
            self.assertFalse(view(n), n)

    def test_housing_chain_users_exist(self):
        for n in ("fin_hr_head", "admin_gm", "prod_head"):
            self.u(n)
        s = self.subj()
        h = Subject.objects.filter(applicant_name="علي علي محمود").first()
        t = set(PermissionService.get_allowed_referral_targets(self.u("prod_head"), h).values_list("username", flat=True))
        self.assertIn("fin_hr_head", t)
        t2 = set(PermissionService.get_allowed_referral_targets(self.u("fin_hr_head"), h).values_list("username", flat=True))
        self.assertIn("admin_gm", t2)
        self.assertIn("housing_emp", t2)


class CrossSectorHousingScope(TestCase):
    """موضوع إسكان من الإنتاج يصل لقطاع المالية والموارد البشرية: النطاق محصور بنوع الإسكان في قطاع الإنتاج."""

    @classmethod
    def setUpTestData(cls):
        with cls.captureOnCommitCallbacks(execute=True):
            call_command("seed_demo_data")

    def u(self, n):
        return User.objects.get(username=n)

    def _subject(self, tx_code_contains, sector_code):
        from core.models import TransactionType
        from organization.models import Sector
        tx = TransactionType.objects.get(name__contains=tx_code_contains)
        return Subject(sector=Sector.objects.get(code=sector_code), transaction_type=tx,
                       confidentiality=ConfidentialityLevel.objects.order_by("rank").first())

    def test_housing_from_production_gives_fin_hr_head_permission_and_targets(self):
        s = self._subject("إسكان", "PROD")
        self.assertTrue(PermissionService.user_has_permission(
            self.u("fin_hr_head"), "REFERRAL_CREATE", sector=s.sector, transaction_type=s.transaction_type))
        self.assertTrue(PermissionService.user_has_permission(
            self.u("admin_gm"), "REFERRAL_CREATE", sector=s.sector, transaction_type=s.transaction_type))

    def test_no_widening_for_other_types_or_sectors(self):
        prod_transfer = self._subject("نقل", "PROD")
        for name in ("fin_hr_head", "admin_gm", "housing_sup", "housing_emp"):
            self.assertFalse(PermissionService.user_has_permission(
                self.u(name), "REFERRAL_CREATE", sector=prod_transfer.sector,
                transaction_type=prod_transfer.transaction_type), name)
        hr_housing = self._subject("إسكان", "FIN_HR")
        for name in ("transfers_emp", "transfers_sup"):
            self.assertFalse(PermissionService.user_has_permission(
                self.u(name), "REFERRAL_CREATE", sector=hr_housing.sector,
                transaction_type=hr_housing.transaction_type), name)
