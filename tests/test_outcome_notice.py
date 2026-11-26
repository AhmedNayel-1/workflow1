"""توصيف اختياري لتأشيرة الرئيس وسجل إخطار فعلي، بدون تغيير الصلاحيات أو فرض مسار (متطلبات أحمد 17804617/17810123)."""
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse
from accounts.models import User
from django.core.exceptions import ValidationError
from core.models import TransactionType
from subjects.guidance import build_subject_guidance
from subjects.models import Annotation, NoticeRecord, OutgoingCorrespondence, Subject
from subjects.services import SubjectService


class OutcomeNoticeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo_data", verbosity=0)

    def setUp(self):
        base = Subject.objects.first()
        self.chair = User.objects.get(username="chairman")
        self.s = SubjectService.create_subject(
            title="اختبار توصيف التأشيرة", transaction_type=base.transaction_type, sector=base.sector,
            org_unit=base.org_unit, confidentiality=base.confidentiality, priority=base.priority,
            created_by=self.chair, current_owner=self.chair,
        )
        self.url = reverse("subjects:subject_detail", args=[self.s.id])

    def _post(self, user, **data):
        self.client.force_login(user)
        return self.client.post(self.url, data)

    def test_annotation_outcome_optional_and_validated(self):
        self._post(self.chair, action="add_annotation", annotation_text="نص حر فقط")
        self._post(self.chair, action="add_annotation", annotation_text="لجنة", outcome="PERSONNEL_COMMITTEE")
        self._post(self.chair, action="add_annotation", annotation_text="مجهول", outcome="NOT_A_CHOICE", outcome_other="مسار آخر")
        a = {x.annotation_text: x for x in Annotation.objects.filter(subject=self.s)}
        self.assertEqual(a["نص حر فقط"].outcome, "")
        self.assertEqual(a["لجنة"].outcome, "PERSONNEL_COMMITTEE")
        self.assertEqual(a["مجهول"].outcome, "")
        self.assertEqual(a["مجهول"].outcome_other, "مسار آخر")

    def test_annotation_never_records_a_notice_by_itself(self):
        self._post(self.chair, action="add_annotation", annotation_text="إخطار شفهي", outcome="VERBAL_NOTICE")
        self.assertEqual(NoticeRecord.objects.filter(subject=self.s).count(), 0)

    def test_record_notice_requires_name_and_method(self):
        self._post(self.chair, action="record_notice", recipient_name="", method="VERBAL")
        self._post(self.chair, action="record_notice", recipient_name="س", method="BAD")
        self.assertEqual(NoticeRecord.objects.count(), 0)
        self._post(self.chair, action="record_notice", recipient_name="مقدم الشكوى", method="VERBAL", notes="تم")
        n = NoticeRecord.objects.get()
        self.assertEqual((n.recipient_name, n.method, n.recorded_by_id), ("مقدم الشكوى", "VERBAL", self.chair.id))

    def test_record_notice_denied_without_subject_access(self):
        r = self._post(User.objects.get(username="transfers_emp"), action="record_notice", recipient_name="س", method="VERBAL")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(NoticeRecord.objects.count(), 0)

    def test_annotation_still_requires_existing_permission(self):
        emp = User.objects.get(username="transfers_emp")
        self._post(emp, action="add_annotation", annotation_text="x", outcome="REJECT")
        self.assertEqual(Annotation.objects.filter(subject=self.s).count(), 0)


class OutgoingAndGuidanceTests(OutcomeNoticeTests):
    def test_request_awaiting_reply_blocks_formal_close_until_reply(self):
        self._post(self.chair, action="record_outgoing", kind="REQUEST", recipient_entity="الجهاز المركزي", title="طلب بيان", sent_confirmed="1")
        r = OutgoingCorrespondence.objects.get()
        self.assertTrue(r.awaiting_reply)
        self.assertTrue(any("بانتظار رد" in e for e in SubjectService.validate_closure_requirements(self.s)))
        self._post(self.chair, action="mark_outgoing_reply", outgoing_id=r.id, reply_notes="وصل")
        r.refresh_from_db()
        self.assertFalse(r.awaiting_reply)
        self.assertFalse(any("بانتظار رد" in e for e in SubjectService.validate_closure_requirements(self.s)))

    def test_followup_requires_sent_request(self):
        self._post(self.chair, action="record_outgoing", kind="REQUEST", recipient_entity="ص", title="مسودة")
        req = OutgoingCorrespondence.objects.get()
        self._post(self.chair, action="record_outgoing", kind="FOLLOWUP", parent_id=req.id)
        self.assertEqual(OutgoingCorrespondence.objects.count(), 1)

    def test_followup_needs_original_request_and_stays_open(self):
        self._post(self.chair, action="record_outgoing", kind="FOLLOWUP", recipient_entity="س", title="استعجال")
        self.assertEqual(OutgoingCorrespondence.objects.count(), 0)
        self._post(self.chair, action="record_outgoing", kind="REQUEST", recipient_entity="الضرائب", title="طلب", sent_confirmed="1")
        req = OutgoingCorrespondence.objects.get(kind="REQUEST")
        self._post(self.chair, action="record_outgoing", kind="FOLLOWUP", parent_id=req.id)
        f = OutgoingCorrespondence.objects.get(kind="FOLLOWUP")
        self.assertEqual((f.parent_id, f.recipient_entity), (req.id, "الضرائب"))
        req.refresh_from_db()
        self.assertTrue(req.awaiting_reply)

    def test_outgoing_response_does_not_wait_for_reply(self):
        self._post(self.chair, action="record_outgoing", kind="RESPONSE", recipient_entity="قطاعات الإنتاج", title="رد بعدد المهندسين")
        self.assertFalse(any("بانتظار رد" in e for e in SubjectService.validate_closure_requirements(self.s)))

    def test_outgoing_denied_without_access(self):
        r = self._post(User.objects.get(username="transfers_emp"), action="record_outgoing", kind="REQUEST", recipient_entity="س", title="ص")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(OutgoingCorrespondence.objects.count(), 0)

    def test_decision_guidance_only_for_types_that_require_decision(self):
        perms = {"can_act": True, "can_memo": True, "can_decide": True, "can_refer": False, "can_approve": True, "can_close": True}
        def g(requires):
            tt = TransactionType.objects.get(id=self.s.transaction_type_id)
            tt.requires_decision = requires; tt.save()
            self.s.refresh_from_db()
            return build_subject_guidance(self.s, perms, has_memo=True, decisions_count=0, docs_count=1, active_step=4)
        self.assertEqual(g(True)["title"], "حان وقت القرار")
        self.assertNotEqual(g(False)["title"], "حان وقت القرار")

    def test_non_decision_type_guidance_is_reply_not_memo_and_attachment_is_optional(self):
        perms = {"can_act": True, "can_memo": True, "can_decide": True, "can_refer": True, "can_approve": True, "can_close": True}
        tt = TransactionType.objects.get(id=self.s.transaction_type_id)
        tt.requires_decision = False; tt.save(); self.s.refresh_from_db()
        ext_tt = TransactionType.objects.get(code="EXTERNAL_REQUEST"); self.s.transaction_type = ext_tt
        g = build_subject_guidance(self.s, perms, has_memo=False, decisions_count=0, docs_count=0, active_step=4)
        self.assertEqual(g["primary"]["label"], "سجّل الرد الصادر")
        labels = [a["label"] for a in g["secondary"]]
        self.assertIn("مذكرة (اختياري)", labels)
        self.s.transaction_type = TransactionType.objects.get(id=tt.id)
        g3 = build_subject_guidance(self.s, perms, has_memo=False, decisions_count=0, docs_count=1, active_step=4)
        self.assertNotEqual(g3["primary"]["label"], "سجّل الرد الصادر")  # نوع داخلي بلا جهة خارجية: لا يُفرض الرد
        g2 = build_subject_guidance(self.s, perms, has_memo=False, decisions_count=0, docs_count=0, active_step=2)
        self.assertNotIn("مستند", g2["primary"]["label"])


class OutgoingFromEntryTests(OutcomeNoticeTests):
    def _entry(self, **over):
        data = dict(title="طلب بيان من جهة", transaction_type_id=self.s.transaction_type_id, sector_id=self.s.sector_id,
                    org_unit_id=self.s.org_unit_id, confidentiality_id=self.s.confidentiality_id,
                    priority_id=self.s.priority_id, external_source="الجهاز المركزي", compose_mode="document")
        data.update(over)
        self.client.force_login(self.chair)
        return self.client.post("/subjects/create/", data)

    def test_response_rejected_on_outgoing_origin_subject(self):
        self._entry(direction="OUT")
        sub = Subject.objects.order_by("-id").first()
        self.client.force_login(self.chair)
        self.client.post(reverse("subjects:subject_detail", args=[sub.id]), {"action": "record_outgoing", "kind": "RESPONSE", "recipient_entity": "س", "title": "رد"})
        self.assertFalse(OutgoingCorrespondence.objects.filter(subject=sub, kind="RESPONSE").exists())

    def test_followup_cannot_link_to_other_subject_request(self):
        self._entry(direction="OUT")
        sub = Subject.objects.order_by("-id").first()
        oc = OutgoingCorrespondence.objects.get(subject=sub)
        oc.sent_at = timezone.now(); oc.save()
        self._post(self.chair, action="record_outgoing", kind="FOLLOWUP", parent_id=oc.id)
        self.assertFalse(OutgoingCorrespondence.objects.filter(subject=self.s, kind="FOLLOWUP").exists())

    def test_outgoing_entry_creates_open_request_and_blocks_close(self):
        r = self._entry(direction="OUT")
        self.assertEqual(r.status_code, 302)
        sub = Subject.objects.order_by("-id").first()
        oc = OutgoingCorrespondence.objects.get(subject=sub)
        self.assertEqual((oc.kind, oc.recipient_entity, oc.is_origin), ("REQUEST", "الجهاز المركزي", True))
        self.assertEqual(sub.status, Subject.Status.NEW)
        # مسودة: لم يُؤكَّد إرسالها، فلا ينتظر رداً ولا يمنع الإغلاق
        self.assertTrue(oc.is_draft and not oc.awaiting_reply)
        self.assertFalse(any("بانتظار رد" in e for e in SubjectService.validate_closure_requirements(sub)))
        # لا رد على مسودة، ولا تأكيد بدون إقرار صريح
        self.client.force_login(self.chair)
        url = reverse("subjects:subject_detail", args=[sub.id])
        self.client.post(url, {"action": "mark_outgoing_reply", "outgoing_id": oc.id})
        self.client.post(url, {"action": "mark_outgoing_sent", "outgoing_id": oc.id})
        oc.refresh_from_db(); self.assertTrue(oc.is_draft and oc.reply_received_at is None)
        self.client.post(url, {"action": "mark_outgoing_sent", "outgoing_id": oc.id, "sent_confirmed": "1"})
        oc.refresh_from_db()
        self.assertTrue(oc.awaiting_reply and oc.sent_marked_by_id == self.chair.id)
        self.assertTrue(any("بانتظار رد" in e for e in SubjectService.validate_closure_requirements(sub)))
        # الإرشاد والمرحلة الجانبية يعكسان الحالة الفعلية
        page = self.client.get(url).content.decode()
        self.assertIn("بانتظار رد/استيفاء من الجهاز المركزي", page)
        self.assertNotIn("بانتظار الإحالة والتوجيه الأول", page)

    def test_incoming_entry_unchanged_and_outgoing_needs_entity(self):
        self._entry()
        sub = Subject.objects.order_by("-id").first()
        self.assertEqual(sub.status, Subject.Status.INCOMING)
        self.assertEqual(OutgoingCorrespondence.objects.filter(subject=sub).count(), 0)
        n = Subject.objects.count()
        self._entry(direction="OUT", external_source="")
        self.assertEqual(Subject.objects.count(), n)


class OptionalAttachmentsTests(OutgoingFromEntryTests):
    def test_subject_can_be_created_and_closed_without_any_attachment(self):
        for d in ("IN", "OUT"):
            self._entry(direction=d)
            sub = Subject.objects.order_by("-id").first()
            self.assertEqual(sub.document_links.count() if hasattr(sub, "document_links") else 0, 0)
        # لا شرط إغلاق يخص المرفقات
        self.assertFalse(any("مرفق" in e or "مستند" in e for e in SubjectService.validate_closure_requirements(sub)))


class OptionalFulfillmentTests(OutcomeNoticeTests):
    def test_fulfillment_without_upload_resumes_subject(self):
        from subjects.models import SubjectSuspension
        SubjectService.suspend_subject(subject=self.s, user=self.chair, reason_ref=None, reason_details="نقص", required_item="أصل الشهادة", required_from="مقدم الطلب", expected_follow_up_date=None)
        sp = SubjectSuspension.objects.get(subject=self.s)
        self._post(self.chair, action="fulfill_suspension", suspension_id=sp.id, fulfillment_notes="تم الاستيفاء")
        sp.refresh_from_db(); self.s.refresh_from_db()
        self.assertTrue(sp.is_fulfilled)
        self.assertNotEqual(self.s.status, Subject.Status.SUSPENDED)


class ViceChairmanRolesTests(OutcomeNoticeTests):
    def test_three_vice_units_exist_without_reparenting_or_users(self):
        from organization.models import OrgUnit, PositionAssignment
        vice = OrgUnit.objects.filter(code__startswith="UNIT_VICE_")
        self.assertEqual(vice.count(), 3)
        chair = OrgUnit.objects.get(code="UNIT_CHAIR")
        self.assertTrue(all(v.parent_id == chair.id for v in vice))
        self.assertFalse(PositionAssignment.objects.filter(org_unit__in=vice).exists())
        for code in ("UNIT_HR_SECTOR", "UNIT_PROD_SECTOR", "UNIT_FIN_HR_SECTOR"):
            self.assertEqual(OrgUnit.objects.get(code=code).parent_id, chair.id)


class ClosedSubjectUploadTests(OutcomeNoticeTests):
    def test_owner_can_attach_to_closed_subject_but_viewer_cannot(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        Subject.objects.filter(id=self.s.id).update(status=Subject.Status.CLOSED)
        self.client.force_login(self.chair)
        f = lambda: SimpleUploadedFile("a.pdf", b"%PDF-1.4\n%%EOF\n", content_type="application/pdf")
        owner = self.s.current_owner
        self.client.force_login(owner)
        r = self.client.post(self.url, {"action": "upload_attachment", "doc_title": "ملحق", "attachment_file": f()})
        self.assertEqual(r.status_code, 302)
        from documents.models import SubjectDocumentLink
        self.assertTrue(SubjectDocumentLink.objects.filter(subject=self.s, document__title="ملحق").exists())
        other = User.objects.get(username="transfers_emp")
        self.client.force_login(other)
        r = self.client.post(self.url, {"action": "upload_attachment", "doc_title": "ممنوع", "attachment_file": f()})
        self.assertEqual(r.status_code, 403)


class DataRequestReplyGuardTests(OutcomeNoticeTests):
    def _as_type(self, code):
        self.s.transaction_type = TransactionType.objects.get(code=code); self.s.save()
        self.s.refresh_from_db()

    def test_data_request_blocks_formal_close_until_sent_linked_reply(self):
        self._as_type("EXTERNAL_REQUEST")
        has = lambda: any("ردّه الصادر" in e for e in SubjectService.validate_closure_requirements(self.s))
        self.assertTrue(has())
        self._post(self.chair, action="record_outgoing", kind="RESPONSE", recipient_entity="الجهة الطالبة", title="رد")  # مسودة لا تكفي
        self.assertTrue(has())
        oc = OutgoingCorrespondence.objects.get(subject=self.s, kind="RESPONSE")
        self._post(self.chair, action="mark_outgoing_sent", outgoing_id=oc.id, sent_confirmed="1")
        self.assertFalse(has())

    def test_other_types_are_not_forced_to_reply(self):
        self._as_type("COMPLAINT")
        self.assertFalse(any("ردّه الصادر" in e for e in SubjectService.validate_closure_requirements(self.s)))

    def test_outgoing_origin_data_request_not_forced(self):
        self._as_type("EXTERNAL_REQUEST")
        OutgoingCorrespondence.objects.create(subject=self.s, kind="REQUEST", is_origin=True, recipient_entity="ج", title="ط", recorded_by=self.chair)
        self.assertFalse(any("ردّه الصادر" in e for e in SubjectService.validate_closure_requirements(self.s)))


class GuidanceStateConsistencyTests(TestCase):
    def test_approved_memo_not_shown_as_pending(self):
        from django.urls import reverse  # noqa: F401
        from subjects.guidance import build_subject_guidance

        class S:
            id = 1
            status = "IN_PROGRESS"
            is_overdue = False

            class outgoing_items:
                @staticmethod
                def filter(**k):
                    class Q:
                        @staticmethod
                        def first():
                            return None
                    return Q

            class transaction_type:
                requires_decision = False
                code = "X"

        perms = {"can_act": True, "can_approve": True}
        g = build_subject_guidance(S, perms, has_memo=True, pending_memos=0, active_step=4)
        self.assertNotEqual(g["title"], "راجع المذكرة واعتمدها")
        g = build_subject_guidance(S, perms, has_memo=True, pending_memos=1, active_step=4)
        self.assertEqual(g["title"], "راجع المذكرة واعتمدها")
        g = build_subject_guidance(S, perms, has_memo=True, pending_memos=0, draft_decisions=1, active_step=4)
        self.assertEqual(g["title"], "قرار بانتظار الاعتماد")
        g = build_subject_guidance(S, perms, has_memo=True, pending_memos=0, pending_committee_items=1, active_step=4)
        self.assertEqual(g["title"], "بانتظار قرار اللجنة")
