"""رؤية التسلسل الإداري لما يُوجَّه للموظفين (نسخة معاد بناؤها)."""
from django.core.management import call_command
from django.test import TestCase

from accounts.models import User
from accounts.permissions_layer import CorrespondenceAccessPolicy as P
from core.models import ConfidentialityLevel
from organization.models import OrgUnit
from subjects.models import Subject
from workflow.models import Referral, ReferralRecipient, Task


class ChainVisibility(TestCase):
    @classmethod
    def setUpTestData(cls):
        with cls.captureOnCommitCallbacks(execute=True):
            call_command("seed_demo_data")

    def u(self, name):
        return User.objects.get(username=name)

    def can(self, name, subj):
        s = Subject.objects.get(pk=subj.pk)
        in_list = Subject.objects.filter(P.get_visible_subjects_q(self.u(name))).filter(pk=s.pk).exists()
        single = P.can_view_subject(self.u(name), s)
        self.assertEqual(single, in_list, f"list/detail mismatch for {name}")
        return single

    def make(self, target="transfers_emp", conf=None, status="PENDING", via="referral"):
        base = Subject.objects.select_related("confidentiality", "priority", "transaction_type").first()
        unit = OrgUnit.objects.get(code="UNIT_HR_SECTOR")  # خارج وحدات المشرف والمدير العام
        conf = conf or ConfidentialityLevel.objects.filter(overrides_hierarchy=False).first()
        n = Subject.objects.count() + 1
        s = Subject.objects.create(
            internal_number=f"CHAIN-{n:05d}", title="اختبار التسلسل", transaction_type=base.transaction_type,
            sector=unit.sector, org_unit=unit, confidentiality=conf, priority=base.priority,
            created_by=self.u("hr_sec"), current_owner=self.u("hr_sec"),
        )
        if via == "referral":
            r = Referral.objects.create(subject=s, referred_by=self.u("hr_sec"), confidentiality=conf, priority=base.priority)
            ReferralRecipient.objects.create(referral=r, target_user=self.u(target), status=status)
        elif via == "task":
            Task.objects.create(subject=s, assigned_to=self.u(target), assigned_by=self.u("hr_sec"), title="t", priority=base.priority)
        return s

    def test_chain_sees_subject_directed_to_employee(self):
        s = self.make()
        for name in ("transfers_sup", "personnel_gm", "hr_head"):
            self.assertTrue(self.can(name, s), name)

    def test_gm_secretariat_sees_via_delegation_within_scope(self):
        s = self.make()  # transfers_emp داخل نطاق تفويض gm_sec (الإدارة العامة للأفراد)
        self.assertTrue(self.can("gm_sec", s))
        s2 = self.make(target="housing_emp")  # خارج نطاق الإدارة العامة
        self.assertFalse(self.can("gm_sec", s2))

    def test_supervisor_secretariat_sees_own_department_only(self):
        s = self.make()
        self.assertTrue(self.can("transfers_sec", s))

    def test_task_assignment_also_counts(self):
        s = self.make(via="task")
        for name in ("transfers_sup", "personnel_gm"):
            self.assertTrue(self.can(name, s), name)

    def test_other_departments_and_employees_do_not_see(self):
        s = self.make()
        for name in ("penalties_sup", "settlements_sup", "housing_sup", "penalties_emp", "settlements_emp", "housing_emp"):
            self.assertFalse(self.can(name, s), name)

    def test_withdrawn_referral_does_not_grant_chain_view(self):
        s = self.make(status="WITHDRAWN")
        for name in ("transfers_sup", "personnel_gm"):
            self.assertFalse(self.can(name, s), name)

    def test_top_secret_not_widened(self):
        top = ConfidentialityLevel.objects.filter(overrides_hierarchy=True).first()
        s = self.make(conf=top)
        # مشرف القسم لا يرى «سري للغاية»؛ المدير العام الأعلى من الموظف المنفذ يراه (تعليمات أحمد الأحدث)
        self.assertFalse(self.can("transfers_sup", s))
        self.assertTrue(self.can("personnel_gm", s))
        self.assertFalse(self.can("gm_sec", s))
        self.assertFalse(self.can("transfers_sec", s))
        self.assertFalse(self.can("penalties_sup", s))

    def test_directed_to_supervisor_not_covered_by_employee_rule(self):
        s = self.make(target="penalties_sup")
        self.assertFalse(self.can("transfers_sup", s))
        self.assertFalse(self.can("settlements_sup", s))

    def test_documents_and_attachments_follow_subject_visibility(self):
        from documents.models import Document
        s = self.make()
        # الصلاحية على المستندات تعتمد can_view_subject: ثابتة "من لا يرى الموضوع لا يرى مستنده" تبقى سارية
        for name in ("transfers_sup", "penalties_sup"):
            self.assertEqual(self.can(name, s), P.can_view_subject(self.u(name), s))
