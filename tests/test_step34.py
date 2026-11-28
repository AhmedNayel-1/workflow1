"""المرحلة 34: تعليق خطوة لاستيفاء مستند."""
import json
from datetime import timedelta

from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from notifications.models import Notification
from subjects.models import StepSuspension, Subject
from workflow.models import ReferralRecipient as RR


class SuspendStepTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo_data", verbosity=0)

    def cl(self, name):
        c = Client(HTTP_HOST="localhost")
        c.force_login(User.objects.get(username=name))
        return c

    def setUp(self):
        self.rr = RR.objects.filter(is_active_step=True, target_user__username="transfers_emp").exclude(referral__purpose="FOR_INFO").first()
        self.sid = self.rr.referral.subject_id
        self.sender = self.rr.referral.referred_by
        self.req = User.objects.get(username="penalties_emp")
        Subject.objects.filter(id=self.sid).update(status="UNDER_REVIEW")

    def suspend(self, fu=None):
        d = {"mode": "suspend", "item": "صورة الهوية", "from": f"p:{self.req.id}"}
        if fu:
            d["follow_up"] = fu
        return self.cl("transfers_emp").post(f"/subjects/{self.sid}/action/", d)

    def test_suspend_notify_cancel_by_each(self):
        prior = Subject.objects.get(id=self.sid).status
        self.assertEqual(self.suspend().status_code, 200)
        sus = StepSuspension.objects.get(subject_id=self.sid)
        self.assertEqual(Subject.objects.get(id=self.sid).status, "SUSPENDED")
        self.assertTrue(Notification.objects.filter(recipient=self.req).exists())
        from subjects.models import SubjectAccessGrant
        self.assertFalse(SubjectAccessGrant.objects.filter(subject_id=self.sid, user=self.req).exists())
        r = self.cl("transfers_emp").post(f"/subjects/{self.sid}/action/", {"mode": "return", "notes": "x"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.cl("transfers_emp").post(f"/subjects/{self.sid}/action/", {"mode": "unsuspend"}).status_code, 200)
        s2 = Subject.objects.get(id=self.sid)
        self.assertEqual(s2.status, prior)
        self.assertEqual(StepSuspension.objects.get(id=sus.id).lift_kind, "CANCEL")
        self.assertTrue(Notification.objects.filter(recipient__username="transfers_emp", subject_id=self.sid, title__contains="عاد").exists())

    def test_due_date_paused_and_not_overdue(self):
        self.suspend()
        s = Subject.objects.get(id=self.sid)
        s.due_date = timezone.localdate() - timedelta(days=3)
        s.save(update_fields=["due_date"])
        self.assertFalse(s.is_overdue)
        StepSuspension.objects.filter(subject_id=self.sid).update(suspended_at=timezone.now() - timedelta(days=4))
        self.cl(self.sender.username)  # لا يغيّر شيئاً
        from subjects import suspension as SU
        SU.cancel(User.objects.get(username="transfers_emp"), Subject.objects.get(id=self.sid))
        s = Subject.objects.get(id=self.sid)
        self.assertEqual(s.due_date, timezone.localdate() + timedelta(days=1))

    def test_supervisor_can_cancel(self):
        self.suspend()
        ok = False
        for name in ("transfers_sup", self.sender.username, "chairman"):
            o = json.loads(self.cl(name).get(f"/subjects/{self.sid}/action-options/").content)
            if o.get("can_cancel") and name != "transfers_emp":
                r = self.cl(name).post(f"/subjects/{self.sid}/action/", {"mode": "unsuspend"})
                self.assertEqual(r.status_code, 200)
                ok = True
                break
        self.assertTrue(ok)
        self.assertNotEqual(Subject.objects.get(id=self.sid).status, "SUSPENDED")
        self.assertEqual(self.cl("housing_emp").post(f"/subjects/{self.sid}/action/", {"mode": "unsuspend"}).status_code, 403)

    def test_reminder_after_follow_up(self):
        self.suspend((timezone.localdate() - timedelta(days=1)).isoformat())
        from subjects import suspension as SU
        self.assertEqual(SU.send_due_reminders(), 1)
        self.assertEqual(SU.send_due_reminders(), 0)

    def test_list_tag(self):
        self.suspend()
        html = self.cl("transfers_emp").get("/subjects/").content.decode()
        self.assertIn("معلّق: صورة الهوية", html)

    def test_requested_cannot_cancel_but_can_request(self):
        self.suspend()
        c = self.cl("penalties_emp")
        n = Notification.objects.get(recipient=self.req)
        self.assertEqual(n.link_url, f"/subjects/{self.sid}/suspension-request/")
        self.assertEqual(c.get(n.link_url).status_code, 200)
        self.assertIn(c.post(f"/subjects/{self.sid}/action/", {"mode": "unsuspend"}).status_code, (400, 403))
        self.assertEqual(Subject.objects.get(id=self.sid).status, "SUSPENDED")
        self.assertEqual(c.post(n.link_url).status_code, 200)
        self.assertTrue(Notification.objects.filter(recipient__username="transfers_emp", title__contains="طلب إلغاء").exists())
        self.assertEqual(self.cl("housing_emp").get(n.link_url).status_code, 403)
