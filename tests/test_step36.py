"""المرحلة 36: الإغلاق من نافذة الإجراء، طلب الإغلاق، منع الإغلاق مع خطوة/تعليق، إشعار السلسلة."""
import json

from django.core.management import call_command
from django.test import Client, TestCase

from accounts.models import User
from notifications.models import Notification
from subjects.models import Subject
from workflow.models import ReferralRecipient as RR


class CloseFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo_data", verbosity=0)

    def cl(self, name):
        c = Client(HTTP_HOST="localhost")
        c.force_login(User.objects.get(username=name))
        return c

    def opt(self, name, sid):
        return json.loads(self.cl(name).get(f"/subjects/{sid}/action-options/").content)

    def setUp(self):
        self.rr = RR.objects.filter(is_active_step=True, target_user__username="transfers_emp").exclude(referral__purpose="FOR_INFO").first()
        self.sid = self.rr.referral.subject_id
        Subject.objects.filter(id=self.sid).update(status="UNDER_REVIEW")

    def test_employee_requests_closure_not_close(self):
        o = self.opt("transfers_emp", self.sid)
        self.assertFalse(o["can_close_now"])
        self.assertTrue(o["can_req_close"])
        self.assertEqual(self.cl("transfers_emp").post(f"/subjects/{self.sid}/action/", {"mode": "close"}).status_code, 403)
        sup = self.rr.referral.referred_by
        self.assertEqual(self.cl("transfers_emp").post(f"/subjects/{self.sid}/action/", {"mode": "request_close", "notes": "انتهيت"}).status_code, 200)
        self.assertTrue(Notification.objects.filter(recipient=sup, title__contains="طلب إغلاق").exists())
        self.assertNotEqual(Subject.objects.get(id=self.sid).status, "CLOSED")

    def test_supervisor_closes_blocked_by_other_steps_then_closes(self):
        sup = self.rr.referral.referred_by
        # الموظف ما زال عنده خطوة مفتوحة، فالمُرسِل لا يغلق (وهو لا يملك خطوة)
        r = self.cl(sup.username).post(f"/subjects/{self.sid}/action/", {"mode": "close", "notes": "x"})
        self.assertIn(r.status_code, (400, 403))
        self.assertNotEqual(Subject.objects.get(id=self.sid).status, "CLOSED")
        RR.objects.filter(referral__subject_id=self.sid, is_active_step=True).update(is_active_step=False)
        from subjects.services import SubjectService
        s = Subject.objects.get(id=self.sid)
        SubjectService.close_subject(subject=s, user=User.objects.get(username="chairman"), closure_notes="تم", outcome="نُفّذ", exceptional=True)
        s.refresh_from_db()
        self.assertEqual(s.status, "CLOSED")
        self.assertEqual(s.closure_outcome, "نُفّذ")
        self.assertTrue(Notification.objects.filter(recipient__username="transfers_emp", title__contains="أُغلق").exists())

    def test_open_suspension_blocks(self):
        from subjects import suspension as SU
        from subjects.models import StepSuspension
        emp = User.objects.get(username="transfers_emp")
        SU.suspend_step(emp, Subject.objects.get(id=self.sid), self.rr, "مستند", user_id=User.objects.get(username="penalties_emp").id)
        from django.core.exceptions import ValidationError
        from subjects.services import SubjectService
        s = Subject.objects.get(id=self.sid)
        with self.assertRaises(Exception):
            SubjectService.close_subject(subject=s, user=self.rr.referral.referred_by)
        self.assertTrue(StepSuspension.objects.filter(subject_id=self.sid, lifted_at__isnull=True).exists())
