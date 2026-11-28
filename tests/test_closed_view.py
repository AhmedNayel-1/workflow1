"""بعد الإغلاق: كل موظفي القسم الذي تعامل مع الموضوع والسلسلة يطّلعون عليه، والسري للغاية يبقى محصوراً."""
from django.core.management import call_command
from django.test import TestCase

from accounts.models import User
from accounts.permissions_layer import CorrespondenceAccessPolicy as P
from subjects.models import Subject


class ClosedViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo_data", verbosity=0)

    def u(self, n):
        return User.objects.get(username=n)

    def test_open_then_closed_department(self):
        s = Subject.objects.get(id=1)
        s.status = "UNDER_REVIEW"; s.save(update_fields=["status"])
        self.assertFalse(P._is_closed_dept_viewer(self.u("transfers_emp"), s))
        s.status = "CLOSED"; s.save(update_fields=["status"])
        self.assertTrue(P._is_closed_dept_viewer(self.u("transfers_emp"), s))
        for n in ("transfers_emp", "transfers_sup", "transfers_sec", "personnel_gm", "hr_head"):
            self.assertTrue(P.can_view_subject(self.u(n), s), n)
            self.assertTrue(Subject.objects.filter(id=s.id).filter(P.get_visible_subjects_q(self.u(n))).exists(), n)
        self.assertFalse(P.can_view_subject(self.u("settlements_emp"), s))
        self.assertFalse(Subject.objects.filter(id=s.id).filter(P.get_visible_subjects_q(self.u("settlements_emp"))).exists())

    def test_secret_stays_restricted(self):
        s = Subject.objects.get(id=5)
        s.status = "CLOSED"; s.save(update_fields=["status"])
        self.assertFalse(P.can_view_subject(self.u("settlements_emp"), s))
        self.assertFalse(Subject.objects.filter(id=5).filter(P.get_visible_subjects_q(self.u("housing_emp"))).exists())
