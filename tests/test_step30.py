"""المرحلة 30: السكرتارية = المسؤول، المساهمة، التولّي عند الغياب، رفض الإحالة يعود للمحيل المباشر فقط."""
import json

from django.core.management import call_command
from django.test import Client, TestCase

from accounts.models import Delegation, User
from subjects.models import Subject
from workflow.models import ReferralRecipient as RR


class Step30Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo_data", verbosity=0)

    def cl(self, name):
        c = Client(HTTP_HOST="localhost")
        c.force_login(User.objects.get(username=name))
        return c

    def opt(self, name, sid):
        return json.loads(self.cl(name).get(f"/subjects/{sid}/action-options/").content)

    def test_secretariat_inherits_and_sector_admin_not(self):
        for sec in ("hr_sec", "gm_sec", "transfers_sec", "chairman_sec"):
            d = Delegation.objects.get(delegate__username=sec)
            self.assertTrue(d.allows("SUBJECT_CLOSE"), sec)
        self.assertFalse(Delegation.objects.filter(delegate__username="hr_sector_admin").exists())

    def test_reject_contribute_takeover(self):
        rr = RR.objects.filter(is_active_step=True, target_user__username="transfers_emp").first()
        sid, sender = rr.referral.subject_id, rr.referral.referred_by
        # المحيل من السلسلة: مساهمة بلا تغيير للعهدة
        owner_before = Subject.objects.get(id=sid).current_owner_id
        r = self.cl(sender.username).post(f"/subjects/{sid}/action/", {"mode": "contribute", "notes": "معلومة"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Subject.objects.get(id=sid).current_owner_id, owner_before)
        # الموظف المختص لا يتولّى
        self.cl("transfers_emp").post(f"/subjects/{sid}/action/", {"mode": "return", "notes": "ليس من اختصاصي"})
        # الرفض يعود للمحيل المباشر فقط لا لرئيس القطاع الأعلى
        self.assertEqual(Subject.objects.get(id=sid).current_owner_id, sender.id)
        self.assertEqual(self.opt("chairman", sid)["mode"], "chain")
        self.assertEqual(self.opt(sender.username, sid)["mode"], "full")
        self.assertEqual(self.cl("transfers_emp").post(f"/subjects/{sid}/action/", {"mode": "takeover", "notes": "x"}).status_code, 403)
        # الرئيس الأعلى يتولّى عند غياب صاحب العهدة
        self.assertEqual(self.cl("chairman").post(f"/subjects/{sid}/action/", {"mode": "takeover", "notes": "إجازة"}).status_code, 200)
        self.assertEqual(Subject.objects.get(id=sid).current_owner.username, "chairman")
        # سكرتارية الرئيس تأخذ نفس زر الرئيس
        self.assertEqual(self.opt("chairman_sec", sid)["mode"], "full")

    def test_parallel_branches_and_add_participant(self):
        from core.models import ActionChoice
        from workflow.models import Referral
        from workflow.services import WorkflowEngineService as W
        s = Subject.objects.filter(sector__name__contains="الموارد البشرية", org_unit__name__contains="التنقلات").exclude(status="CLOSED").order_by("id").first()
        Subject.objects.filter(id=s.id).update(current_owner=User.objects.get(username="hr_head")); s.refresh_from_db()
        W.create_referral(subject=s, referred_by=s.current_owner, routing_mode="DIRECT", purpose="FOR_EXECUTION", target_users=[User.objects.get(username="personnel_gm")])
        uid = lambda n: User.objects.get(username=n).id
        self.cl("personnel_gm").post(f"/subjects/{s.id}/action/", {"mode": "route", "target_user_ids": [uid("transfers_sup"), uid("penalties_sup")], "notes": "متوازي"})
        for n in ("hr_head", "personnel_gm", "gm_sec"):
            self.assertIn(s.internal_number, self.cl(n).get("/subjects/").content.decode())
        # مشارك إضافي دون إنهاء عمل المضيف ودون تغيير العهدة
        r = self.cl("transfers_sup").post(f"/subjects/{s.id}/action/", {"mode": "addpart", "target_user_ids": [uid("transfers_emp")], "notes": "ساعدني"})
        self.assertEqual(r.status_code, 200, r.content)
        from workflow.models import ReferralRecipient as RR
        self.assertTrue(RR.objects.filter(referral__subject=s, target_user__username="transfers_sup", is_active_step=True).exists())
        for sup, emp in (("transfers_sup", "transfers_emp"), ("penalties_sup", "penalties_emp")):
            r = self.cl(sup).post(f"/subjects/{s.id}/action/", {"mode": "route", "target_user_ids": [uid(emp)], "notes": "نفّذ"})
            self.assertEqual(r.status_code, 200, r.content)
            for n in ("personnel_gm", sup):
                self.assertIn(s.internal_number, self.cl(n).get("/subjects/").content.decode())
        done = ActionChoice.objects.get(code="DONE").id
        self.cl("transfers_emp").post(f"/subjects/{s.id}/action/", {"choice_id": done, "notes": "أ"})
        st = Subject.objects.get(id=s.id)
        self.assertNotEqual(st.status, Subject.Status.CLOSED)
        self.assertTrue(ReferralRecipientActive(s))
        self.cl("penalties_emp").post(f"/subjects/{s.id}/action/", {"choice_id": done, "notes": "ب"})


def ReferralRecipientActive(s):
    from workflow.models import ReferralRecipient as RR
    return RR.objects.filter(referral__subject=s, target_user__username="penalties_emp").exists()


class BootstrapTests(TestCase):
    def test_bootstrap_idempotent(self):
        from django.core.management import call_command
        call_command("bootstrap_demo")
        n = User.objects.count()
        call_command("bootstrap_demo")
        self.assertEqual(n, User.objects.count())
