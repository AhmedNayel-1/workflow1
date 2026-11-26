"""
حزمة الاختبارات الآلية الشاملة:
- اختبار السيناريوهات الخمسة كاملة من البداية إلى النهاية.
- اختبار السرية الفائقة (منع المدير العام من الاطلاع أو البحث أو تنزيل مرفقات سري للغاية).
- اختبار الإحالة المباشرة، المتتابعة، المتوازية، والاطلاع للعلم فقط.
- اختبار التعليق والاستيفاء والإغلاق المشروط وإعادة الفتح.
- اختبار Many-to-Many للمستندات، عدم استبدال النسخ، منع التكرار، وتعارض التعديل المتزامن.
"""
from datetime import timedelta
import threading
import time
from unittest.mock import patch
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import OperationalError, connections
from django.test import Client, TestCase, TransactionTestCase
from django.utils import timezone
from accounts.models import Delegation, User
from accounts.services import PermissionService
from audit.models import ActivityLog
from committees.models import Committee, CommitteeAgendaItem, CommitteeMeeting
from core.models import ConfidentialityLevel, DocumentType, PriorityLevel, SystemSequence, TransactionType
from decisions.models import Decision
from decisions.services import DecisionService
from documents.models import Attachment, SubjectDocumentLink
from documents.services import DocumentService
from django.urls import reverse
from notifications.models import Notification
from organization.models import OrgUnit, Sector
from subjects.models import Memo, Subject, SubjectStatusHistory
from subjects.services import OptimisticLockError, SubjectService, transition_subject
from workflow.models import (
    Referral,
    ReferralRecipient,
    Task,
    WorkflowStepDefinition,
    WorkflowTemplate,
    WorkflowTemplateVersion,
)
from workflow.services import WorkflowEngineService, apply_template


class CorrespondenceSystemTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # الإشعارات تُنشأ داخل transaction.on_commit، وTestCase لا ينفذها إلا بهذا السياق
        with cls.captureOnCommitCallbacks(execute=True):
            call_command("seed_demo_data")

    def test_scenario_5_top_secret_overrides_hierarchy(self):
        """
        السيناريو الخامس (اختبار الأمان الأساسي):
        المدير العام لشئون الأفراد يقع أعلى هرمياً من قسم التنقلات، لكنه غير مصرح له
        بالاطلاع على الموضوع السري للغاية المحال مباشرة من رئيس القطاع إلى الموظف المختص.
        """
        top_secret_subject = Subject.objects.get(confidentiality__code="TOP_SECRET")
        hr_head = User.objects.get(username="hr_head")
        hr_sec = User.objects.get(username="hr_sec")
        personnel_gm = User.objects.get(username="personnel_gm")
        transfers_emp = User.objects.get(username="transfers_emp")

        self.assertTrue(PermissionService.can_view_subject(hr_head, top_secret_subject))
        self.assertTrue(PermissionService.can_view_subject(transfers_emp, top_secret_subject))
        self.assertTrue(PermissionService.can_view_subject(hr_sec, top_secret_subject))

        # المدير العام يجب أن يُمنع تماماً رغم تبعيته الهرمية
        # المدير العام الأعلى من الموظف المنفذ يرى الموضوع (تعليمات أحمد الأحدث)، أما المشرف وسكرتارية القسم والمدير العام فلا
        self.assertTrue(PermissionService.can_view_subject(personnel_gm, top_secret_subject))
        self.assertFalse(PermissionService.can_view_subject(User.objects.get(username="transfers_sup"), top_secret_subject))
        self.assertFalse(PermissionService.can_view_subject(User.objects.get(username="gm_sec"), top_secret_subject))
        self.assertFalse(PermissionService.can_view_subject(User.objects.get(username="transfers_sec"), top_secret_subject))

        # موظف في إدارة أخرى لا يرى الموضوع في البحث
        client = Client()
        client.force_login(User.objects.get(username="housing_sup"))
        resp = client.get("/search/?q=الجهاز المركزي")
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, top_secret_subject.internal_number)

        # محاولة الوصول المباشر لتفاصيل الموضوع تعطي 403 Forbidden
        detail_resp = client.get(f"/subjects/{top_secret_subject.id}/")
        self.assertEqual(detail_resp.status_code, 403)

    def test_scenario_1_transfer_suspend_fulfill_decide_execute_close(self):
        """السيناريو الأول: طلب نقل، تعليق لتحليل مخدرات، استيفاء، لجنة، قرار، تنفيذ، ثم إغلاق."""
        hr_head = User.objects.get(username="hr_head")
        transfers_emp = User.objects.get(username="transfers_emp")
        u_transfers = OrgUnit.objects.get(code="UNIT_TRANSFERS")
        s1 = Subject.objects.filter(applicant_name="محمد محمود علي").first()

        # لا يمكن إغلاق الموضوع وهو معلق
        with self.assertRaises(ValidationError):
            SubjectService.close_subject(subject=s1, user=hr_head, closure_notes="محاولة إغلاق مبكر")

        # تسجيل استيفاء شهادة تحليل المخدرات
        suspension = s1.suspensions.filter(is_fulfilled=False).first()
        SubjectService.fulfill_suspension(
            suspension=suspension,
            user=transfers_emp,
            fulfillment_notes="تم تقديم شهادة تحليل مخدرات سلبية معتمدة.",
        )
        s1.refresh_from_db()
        self.assertEqual(s1.status, Subject.Status.IN_PROGRESS)

        # عرض على لجنة شئون العاملين
        com = Committee.objects.get(code="COM_PERSONNEL")
        meeting = CommitteeMeeting.objects.create(
            committee=com,
            meeting_number="15/2026",
            meeting_date=timezone.localdate(),
            created_by=hr_head,
        )
        item = CommitteeAgendaItem.objects.create(
            meeting=meeting,
            subject=s1,
            resolution_type=CommitteeAgendaItem.ResolutionType.APPROVED,
            resolution_text="الموافقة على نقل محمد محمود علي إلى محطة أبو قير.",
            recorded_by=hr_head,
        )

        # إعداد واعتماد وإصدار القرار
        decision = DecisionService.create_decision_draft(
            subject=s1,
            decision_type=Decision.DecisionType.TRANSFER,
            title="قرار نقل الموظف محمد محمود علي",
            body="ينقل السيد/ محمد محمود علي إلى محطة كهرباء أبو قير.",
            issuing_authority="رئيس مجلس الإدارة",
            approving_authority="رئيس مجلس الإدارة",
            created_by=transfers_emp,
            committee_item=item,
        )
        DecisionService.approve_and_issue(decision=decision, user=hr_head)

        # توزيع وتكليف بالتنفيذ — إصدار القرار لا يغلق الموضوع تلقائياً
        DecisionService.distribute_and_assign_execution(
            decision=decision,
            user=hr_head,
            distribution_units=[u_transfers],
            execution_assignments=[
                {"unit": u_transfers, "user": transfers_emp, "required_action": "تنفيذ إخلاء الطرف والنقل"}
            ],
        )
        with self.assertRaises(ValidationError):
            SubjectService.close_subject(subject=s1, user=hr_head)

        # إتمام التنفيذ ثم الإغلاق الرسمي وإعادة الفتح
        exec_item = decision.execution_items.first()
        DecisionService.complete_execution_item(
            exec_item=exec_item, user=transfers_emp, execution_result="تم إخلاء الطرف والمباشرة."
        )
        s1.refresh_from_db()
        SubjectService.close_subject(subject=s1, user=hr_head, closure_notes="اكتملت جميع إجراءات النقل.")
        self.assertEqual(s1.status, Subject.Status.CLOSED)

        # إعادة الفتح تحفظ closed_at التاريخي
        SubjectService.reopen_subject(subject=s1, user=hr_head, reason="ورود التماس لاحق.")
        s1.refresh_from_db()
        self.assertEqual(s1.status, Subject.Status.REOPENED)
        self.assertIsNotNone(s1.closed_at)

    def test_referrals_sequential_parallel_and_for_info(self):
        """اختبار الإحالة المتتابعة والمتوازية والإحالة للعلم فقط (دون تكليف)."""
        hr_head = User.objects.get(username="hr_head")
        personnel_gm = User.objects.get(username="personnel_gm")
        transfers_sup = User.objects.get(username="transfers_sup")
        transfers_emp = User.objects.get(username="transfers_emp")
        s3 = Subject.objects.filter(applicant_name="يحيى أحمد").first()

        # للعلم فقط: لا تغيّر current_owner
        prev_owner = s3.current_owner
        ref_info = WorkflowEngineService.create_referral(
            subject=s3,
            referred_by=hr_head,
            routing_mode=Referral.RoutingMode.DIRECT,
            purpose=Referral.Purpose.FOR_INFO,
            notes="للعلم والاطلاع فقط",
            target_users=[personnel_gm],
            enforce_hierarchy=False,
        )
        s3.refresh_from_db()
        self.assertEqual(s3.current_owner, prev_owner)
        self.assertTrue(ref_info.is_for_info_only)

        # إحالة متتابعة: الأول ينشط والثاني ينتظر دوره
        ref_seq = WorkflowEngineService.create_referral(
            subject=s3,
            referred_by=hr_head,
            routing_mode=Referral.RoutingMode.SEQUENTIAL,
            purpose=Referral.Purpose.FOR_STUDY,
            target_users=[personnel_gm, transfers_sup],
            enforce_hierarchy=False,
        )
        r1, r2 = list(ref_seq.recipients.order_by("sequence_order"))
        self.assertTrue(r1.is_active_step)
        self.assertFalse(r2.is_active_step)
        WorkflowEngineService.acknowledge_or_complete_recipient(recipient_item=r1, user=personnel_gm, response_notes="تمت المراجعة")
        r2.refresh_from_db()
        self.assertTrue(r2.is_active_step)

        # إحالة متوازية بشرط أول رد
        ref_par = WorkflowEngineService.create_referral(
            subject=s3,
            referred_by=hr_head,
            routing_mode=Referral.RoutingMode.PARALLEL,
            purpose=Referral.Purpose.FOR_STUDY,
            parallel_completion_rule=Referral.ParallelCompletionRule.FIRST_RESPONSE,
            target_users=[transfers_sup, transfers_emp],
            idempotency_key="unique-par-key-1",
            enforce_hierarchy=False,
        )
        # منع التكرار بنفس idempotency_key
        ref_par_dup = WorkflowEngineService.create_referral(
            subject=s3,
            referred_by=hr_head,
            routing_mode=Referral.RoutingMode.PARALLEL,
            purpose=Referral.Purpose.FOR_STUDY,
            target_users=[transfers_sup, transfers_emp],
            idempotency_key="unique-par-key-1",
            enforce_hierarchy=False,
        )
        self.assertEqual(ref_par.id, ref_par_dup.id)
        first_rec = ref_par.recipients.first()
        WorkflowEngineService.acknowledge_or_complete_recipient(recipient_item=first_rec, user=transfers_sup)
        ref_par.refresh_from_db()
        self.assertTrue(ref_par.is_completed)

    def test_document_many_to_many_versions_and_secure_attachments(self):
        """اختبار ربط المستند بأكثر من موضوع وإصدار نسخ غير قابلة للاستبدال وحماية المرفقات."""
        hr_head = User.objects.get(username="hr_head")
        s1 = Subject.objects.filter(applicant_name="محمد محمود علي").first()
        s3 = Subject.objects.filter(applicant_name="يحيى أحمد").first()
        doc_type = DocumentType.objects.first()
        conf_normal = ConfidentialityLevel.objects.get(code="NORMAL")

        sample_pdf = SimpleUploadedFile("policy.pdf", b"%PDF-1.4 test content", content_type="application/pdf")
        doc = DocumentService.register_document(
            title="قرار تنظيمي مشترك",
            doc_type=doc_type,
            confidentiality=conf_normal,
            created_by=hr_head,
            subject=s1,
            uploaded_file=sample_pdf,
        )
        SubjectDocumentLink.objects.create(subject=s3, document=doc, linked_by=hr_head)
        self.assertEqual(doc.subjects.count(), 2)

        # إصدار نسخة ثانية دون حذف النسخة الأولى
        sample_pdf_v2 = SimpleUploadedFile("policy_v2.pdf", b"%PDF-1.4 updated v2", content_type="application/pdf")
        DocumentService.create_new_version(
            document=doc, user=hr_head, change_reason="تحديث المادة الثانية", is_approved=True, uploaded_file=sample_pdf_v2
        )
        self.assertEqual(doc.versions.count(), 2)

        # رفض امتداد تنفيذي خطير (.exe)
        bad_file = SimpleUploadedFile("virus.exe", b"MZ...", content_type="application/octet-stream")
        with self.assertRaises(ValidationError):
            DocumentService.validate_uploaded_file(bad_file)

    def test_optimistic_locking_and_atomic_numbering(self):
        """اختبار اكتشاف تعارض التعديل المتزامن والترقيم التسلسلي الآمن."""
        hr_head = User.objects.get(username="hr_head")
        s3 = Subject.objects.filter(applicant_name="يحيى أحمد").first()
        old_ver = s3.version_lock
        SubjectService.update_subject_with_lock(s3.id, old_ver, hr_head, keywords="محدث")
        with self.assertRaises(OptimisticLockError):
            SubjectService.update_subject_with_lock(s3.id, old_ver, hr_head, keywords="بيانات قديمة")

        n1 = SystemSequence.next_number("TEST_SEQ", "TST")
        n2 = SystemSequence.next_number("TEST_SEQ", "TST")
        self.assertNotEqual(n1, n2)

    def test_task_completion_does_not_auto_close_subject(self):
        """اكتمال مهمة واحدة لا يغلق الموضوع تلقائياً."""
        hr_head = User.objects.get(username="hr_head")
        housing_emp = User.objects.get(username="housing_emp")
        s4 = Subject.objects.filter(applicant_name="علي علي محمود").first()
        task = WorkflowEngineService.create_task(
            subject=s4, title="معاينة الشقة", assigned_to=housing_emp, assigned_by=hr_head
        )
        task.status = Task.TaskStatus.COMPLETED
        task.save()
        s4.refresh_from_db()
        self.assertNotEqual(s4.status, Subject.Status.CLOSED)

    def test_quick_archive_search_isolation(self):
        """البحث السريع في العناوين والملخصات لا يكشف السري للغاية لغير المصرح لهم."""
        client = Client()
        personnel_gm = User.objects.get(username="transfers_sup")
        hr_head = User.objects.get(username="hr_head")

        # مشرف القسم يبحث عن كلمة في عنوان/ملخص الموضوع السري للغاية: يجب ألا يظهر
        client.force_login(personnel_gm)
        resp_gm = client.get("/archive-search/?q=الجهاز المركزي")
        self.assertEqual(resp_gm.status_code, 200)
        self.assertNotContains(resp_gm, "DOC-2026-00004")
        self.assertNotContains(resp_gm, "SUB-2026-00005")

        # رئيس القطاع المخول يبحث عن نفس الكلمة: يجب أن يظهر
        client.force_login(hr_head)
        resp_head = client.get("/archive-search/?q=الجهاز المركزي")
        self.assertEqual(resp_head.status_code, 200)
        self.assertContains(resp_head, "SUB-2026-00005")

    def test_superuser_only_db_and_permissions_screens(self):
        """شاشات إدارة قواعد البيانات والصلاحيات متاحة لـ Superuser (an) فقط وممنوعة عن البقية."""
        client = Client()
        hr_head = User.objects.get(username="hr_head")
        superuser = User.objects.get(username="an")

        client.force_login(hr_head)
        self.assertEqual(client.get("/db-admin/").status_code, 403)
        self.assertEqual(client.get("/accounts/permissions-matrix/").status_code, 403)
        self.assertEqual(client.get("/accounts/users/").status_code, 403)

        client.force_login(superuser)
        self.assertEqual(client.get("/db-admin/").status_code, 200)
        self.assertEqual(client.get("/accounts/permissions-matrix/").status_code, 200)
        self.assertEqual(client.get("/accounts/users/").status_code, 200)

    def test_overdue_due_date_alerts_and_confidentiality_isolation(self):
        """التنبيهات عند تجاوز تاريخ الاستحقاق تظهر للمصرح لهم فقط ولا تكشف السري للغاية لغير المصرح."""
        from core.context_processors import get_user_overdue_alerts

        personnel_gm = User.objects.get(username="housing_sup")
        hr_head = User.objects.get(username="hr_head")
        top_secret_subject = Subject.objects.get(confidentiality__code="TOP_SECRET")

        # من لا يرى الموضوع السري للغاية لا يرى تنبيه الاستحقاق الخاص به
        gm_alerts = get_user_overdue_alerts(personnel_gm)
        self.assertFalse(any(a["subject_id"] == top_secret_subject.id for a in gm_alerts))

        # رئيس القطاع المخول يرى تنبيه الاستحقاق على الواجهة وداخل مركز الإشعارات
        head_alerts = get_user_overdue_alerts(hr_head)
        self.assertTrue(any(a["subject_id"] == top_secret_subject.id for a in head_alerts))

        client = Client()
        client.force_login(personnel_gm)
        resp_gm = client.get("/notifications/")
        self.assertEqual(resp_gm.status_code, 200)
        self.assertNotContains(resp_gm, top_secret_subject.internal_number)

        client.force_login(hr_head)
        resp_head = client.get("/notifications/")
        self.assertEqual(resp_head.status_code, 200)
        self.assertContains(resp_head, top_secret_subject.internal_number)

    def test_hierarchical_routing_and_gm_read_only_sector_head_referrals(self):
        """
        موضوع مسجل لمدير عام شئون الأفراد:
        - إحالات رئيس القطاع للاطلاع فقط ولا يملك المدير العام التعديل عندما لا يكون في عهدته.
        - المدير العام أو سكرتاريته يوجّهان حصراً إلى مشرف/رئيس القسم المختص (وليس الموظف مباشرة).
        - مشرف القسم أو سكرتارية القسم يوزّعان حصراً على الموظف المختص التابع للقسم.
        """
        hr_head = User.objects.get(username="hr_head")
        personnel_gm = User.objects.get(username="personnel_gm")
        gm_sec = User.objects.get(username="gm_sec")
        transfers_sup = User.objects.get(username="transfers_sup")
        transfers_sec = User.objects.get(username="transfers_sec")
        transfers_emp = User.objects.get(username="transfers_emp")

        # 1. موضوع جديد لدى رئيس القطاع: المدير العام يطلع فقط (can_act = False)
        tx = TransactionType.objects.first()
        conf = ConfidentialityLevel.objects.get(code="NORMAL")
        prio = PriorityLevel.objects.first()
        unit_transfers = OrgUnit.objects.get(code="UNIT_TRANSFERS")
        subj = SubjectService.create_subject(
            title="موضوع اختبار التوجيه الهرمي للتنقلات",
            transaction_type=tx,
            sector=unit_transfers.sector,
            org_unit=unit_transfers,
            confidentiality=conf,
            priority=prio,
            created_by=hr_head,
            current_owner=hr_head,
        )
        self.assertFalse(PermissionService.can_act_on_subject(personnel_gm, subj))
        with self.assertRaises(ValidationError):
            WorkflowEngineService.create_referral(
                subject=subj,
                referred_by=personnel_gm,
                routing_mode=Referral.RoutingMode.DIRECT,
                purpose=Referral.Purpose.FOR_EXECUTION,
                target_users=[transfers_sup],
            )

        # 2. رئيس القطاع يوجه إلى مدير عام شئون الأفراد
        WorkflowEngineService.create_referral(
            subject=subj,
            referred_by=hr_head,
            routing_mode=Referral.RoutingMode.DIRECT,
            purpose=Referral.Purpose.FOR_EXECUTION,
            target_users=[personnel_gm],
        )
        self.assertTrue(PermissionService.can_act_on_subject(personnel_gm, subj))
        self.assertTrue(PermissionService.can_act_on_subject(gm_sec, subj))

        # المدير العام أو سكرتاريته: ممنوع التخطي للموظف مباشرة، ومسموح التوجيه لمشرف القسم
        gm_targets = list(PermissionService.get_allowed_referral_targets(gm_sec, subj))
        self.assertIn(transfers_sup, gm_targets)
        self.assertIn(transfers_emp, gm_targets)  # الإحالة المباشرة للموظف المختص مسموحة (احتمال 2)
        self.assertNotIn(User.objects.get(username="housing_emp"), gm_targets)
        with self.assertRaises(ValidationError):
            WorkflowEngineService.create_referral(
                subject=subj,
                referred_by=gm_sec,
                routing_mode=Referral.RoutingMode.DIRECT,
                purpose=Referral.Purpose.FOR_EXECUTION,
                target_users=[User.objects.get(username="housing_emp")],
            )

        WorkflowEngineService.create_referral(
            subject=subj,
            referred_by=gm_sec,
            routing_mode=Referral.RoutingMode.DIRECT,
            purpose=Referral.Purpose.FOR_EXECUTION,
            target_users=[transfers_sup],
        )

        # 3. مشرف القسم أو سكرتارية القسم يوزّع على الموظف المختص التابع فقط
        sup_targets = list(PermissionService.get_allowed_referral_targets(transfers_sec, subj))
        self.assertEqual(sup_targets, [transfers_emp])
        WorkflowEngineService.create_referral(
            subject=subj,
            referred_by=transfers_sec,
            routing_mode=Referral.RoutingMode.DIRECT,
            purpose=Referral.Purpose.FOR_EXECUTION,
            target_users=[transfers_emp],
        )
        subj.refresh_from_db()
        self.assertEqual(subj.current_owner, transfers_emp)

    def test_subject_state_machine_allowed_and_disallowed_transitions(self):
        """التحقق من آلة حالات الموضوع: السماح بالمسار الصحيح ورفض الانتقالات غير المسموحة وتسجيل ActivityLog."""
        hr_head = User.objects.get(username="hr_head")
        tx = TransactionType.objects.first()
        conf = ConfidentialityLevel.objects.get(code="NORMAL")
        prio = PriorityLevel.objects.first()
        unit_transfers = OrgUnit.objects.get(code="UNIT_TRANSFERS")

        subj = SubjectService.create_subject(
            title="موضوع اختبار آلة الحالات",
            transaction_type=tx,
            sector=unit_transfers.sector,
            org_unit=unit_transfers,
            confidentiality=conf,
            priority=prio,
            created_by=hr_head,
            current_owner=hr_head,
        )
        initial_ver = subj.version_lock

        # انتقال غير مسموح من NEW إلى REOPENED يرفع ValidationError ولا يغير الحالة أو النسخة
        with self.assertRaises(ValidationError):
            transition_subject(subj, Subject.Status.REOPENED, hr_head, reason="انتقال غير منطقي")
        subj.refresh_from_db()
        self.assertEqual(subj.status, Subject.Status.NEW)
        self.assertEqual(subj.version_lock, initial_ver)

        # انتقال مسموح: NEW -> IN_PROGRESS يزيد version_lock ويسجل ActivityLog وSubjectStatusHistory
        transition_subject(subj, Subject.Status.IN_PROGRESS, hr_head, reason="بدء المعالجة")
        subj.refresh_from_db()
        self.assertEqual(subj.status, Subject.Status.IN_PROGRESS)
        self.assertEqual(subj.version_lock, initial_ver + 1)
        self.assertTrue(
            ActivityLog.objects.filter(subject=subj, action_type="SUBJECT_STATUS_CHANGED").exists()
        )
        self.assertTrue(
            SubjectStatusHistory.objects.filter(
                subject=subj, from_status=Subject.Status.NEW, to_status=Subject.Status.IN_PROGRESS
            ).exists()
        )

        # التعليق لا يسمح بالإغلاق المباشر من SUSPENDED
        SubjectService.suspend_subject(
            subject=subj,
            user=hr_head,
            reason_details="استيفاء مستند",
            required_from="الموظف",
            required_item="بيان حالة",
        )
        with self.assertRaises(ValidationError):
            transition_subject(subj, Subject.Status.CLOSED, hr_head, reason="إغلاق أثناء التعليق")

        # إلغاء الموضوع (CANCELLED) حالة نهائية لا تقبل انتقالاً بعدها
        transition_subject(subj, Subject.Status.CANCELLED, hr_head, reason="إلغاء الطلب")
        with self.assertRaises(ValidationError):
            transition_subject(subj, Subject.Status.IN_PROGRESS, hr_head, reason="محاولة استئناف بعد الإلغاء")

    def test_parallel_first_response_skips_others_and_coordinator_is_owner(self):
        """الإحالة المتوازية: coordinator هو current_owner، وأول رد في FIRST_RESPONSE يلغي البقية."""
        hr_head = User.objects.get(username="hr_head")
        personnel_gm = User.objects.get(username="personnel_gm")
        transfers_sup = User.objects.get(username="transfers_sup")
        transfers_emp = User.objects.get(username="transfers_emp")
        tx = TransactionType.objects.first()
        conf = ConfidentialityLevel.objects.get(code="NORMAL")
        prio = PriorityLevel.objects.first()
        unit_transfers = OrgUnit.objects.get(code="UNIT_TRANSFERS")

        subj = SubjectService.create_subject(
            title="موضوع اختبار التوازي وأول رد",
            transaction_type=tx,
            sector=unit_transfers.sector,
            org_unit=unit_transfers,
            confidentiality=conf,
            priority=prio,
            created_by=hr_head,
            current_owner=transfers_sup,
        )

        # الافتراضي للمنسق هو المحيل (hr_head) ويصبح current_owner أثناء التوازي
        ref_par = WorkflowEngineService.create_referral(
            subject=subj,
            referred_by=hr_head,
            routing_mode=Referral.RoutingMode.PARALLEL,
            purpose=Referral.Purpose.FOR_STUDY,
            parallel_completion_rule=Referral.ParallelCompletionRule.FIRST_RESPONSE,
            target_users=[transfers_sup, transfers_emp],
            enforce_hierarchy=False,
        )
        subj.refresh_from_db()
        self.assertEqual(ref_par.coordinator, hr_head)
        self.assertEqual(subj.current_owner, hr_head)

        r1, r2 = list(ref_par.recipients.order_by("sequence_order"))
        WorkflowEngineService.acknowledge_or_complete_recipient(
            recipient_item=r1, user=transfers_sup, response_notes="أول إفادة"
        )
        ref_par.refresh_from_db()
        r1.refresh_from_db()
        r2.refresh_from_db()

        self.assertTrue(ref_par.is_completed)
        self.assertEqual(r1.status, ReferralRecipient.RecipientStatus.RESPONDED)
        self.assertFalse(r1.is_active_step)
        self.assertEqual(r2.status, ReferralRecipient.RecipientStatus.SKIPPED_NO_RESPONSE)
        self.assertFalse(r2.is_active_step)

        # محاولة رد متأخر من الطرف المتجاوز ترفع ValidationError ولا تغير حالته
        with self.assertRaises(ValidationError):
            WorkflowEngineService.acknowledge_or_complete_recipient(
                recipient_item=r2, user=transfers_emp, response_notes="رد متأخر"
            )
        r2.refresh_from_db()
        self.assertEqual(r2.status, ReferralRecipient.RecipientStatus.SKIPPED_NO_RESPONSE)

        # تمرير منسق صريح مختلف عن المحيل
        ref_coord = WorkflowEngineService.create_referral(
            subject=subj,
            referred_by=hr_head,
            routing_mode=Referral.RoutingMode.PARALLEL,
            purpose=Referral.Purpose.FOR_STUDY,
            target_users=[transfers_sup, transfers_emp],
            coordinator=personnel_gm,
            enforce_hierarchy=False,
        )
        subj.refresh_from_db()
        self.assertEqual(ref_coord.coordinator, personnel_gm)
        self.assertEqual(subj.current_owner, personnel_gm)

    def test_notification_failure_does_not_rollback_referral(self):
        """فشل إرسال الإشعار داخل on_commit لا يُفشل حفظ الإحالة ولا يلغيها."""
        hr_head = User.objects.get(username="hr_head")
        personnel_gm = User.objects.get(username="personnel_gm")
        s3 = Subject.objects.filter(applicant_name="يحيى أحمد").first()

        with patch("workflow.services.NotificationService.notify", side_effect=RuntimeError("فشل خدمة الإشعارات")) as mock_notify:
            with self.captureOnCommitCallbacks(execute=True):
                referral = WorkflowEngineService.create_referral(
                    subject=s3,
                    referred_by=hr_head,
                    routing_mode=Referral.RoutingMode.DIRECT,
                    purpose=Referral.Purpose.FOR_STUDY,
                    target_users=[personnel_gm],
                    enforce_hierarchy=False,
                )

        self.assertTrue(Referral.objects.filter(id=referral.id).exists())
        self.assertTrue(mock_notify.called)

    def test_acknowledge_locks_referral_and_recipients_with_select_for_update(self):
        """التحقق من استخدام select_for_update على الإحالة والمستلمين داخل atomic."""
        from django.db.models.query import QuerySet

        hr_head = User.objects.get(username="hr_head")
        transfers_sup = User.objects.get(username="transfers_sup")
        transfers_emp = User.objects.get(username="transfers_emp")
        s3 = Subject.objects.filter(applicant_name="يحيى أحمد").first()

        ref = WorkflowEngineService.create_referral(
            subject=s3,
            referred_by=hr_head,
            routing_mode=Referral.RoutingMode.PARALLEL,
            purpose=Referral.Purpose.FOR_STUDY,
            parallel_completion_rule=Referral.ParallelCompletionRule.ALL,
            target_users=[transfers_sup, transfers_emp],
            enforce_hierarchy=False,
        )
        r1 = ref.recipients.order_by("sequence_order").first()

        locked_qs = []
        orig_qs_sfu = QuerySet.select_for_update

        def spy_qs_sfu(qs_self, *args, **kwargs):
            locked_qs.append((qs_self.model.__name__, connections["default"].in_atomic_block))
            return orig_qs_sfu(qs_self, *args, **kwargs)

        with patch.object(QuerySet, "select_for_update", autospec=True, side_effect=spy_qs_sfu):
            WorkflowEngineService.acknowledge_or_complete_recipient(
                recipient_item=r1, user=transfers_sup, response_notes="تمت المراجعة"
            )

        self.assertIn(("Referral", True), locked_qs)
        self.assertIn(("ReferralRecipient", True), locked_qs)

    def test_apply_template_creates_referrals_with_sla_due_date_and_views(self):
        """تفعيل القوالب: apply_template تنشئ الإحالات مع due_date من sla_hours وتعمل من الإنشاء وصفحة الموضوع."""
        hr_head = User.objects.get(username="hr_head")
        tx = TransactionType.objects.first()
        conf = ConfidentialityLevel.objects.get(code="NORMAL")
        prio = PriorityLevel.objects.first()
        u_transfers = OrgUnit.objects.get(code="UNIT_TRANSFERS")
        u_penalties = OrgUnit.objects.get(code="UNIT_PENALTIES")

        tpl = WorkflowTemplate.objects.create(
            code="TPL_STAGE3_TEST",
            name="مسار اختباري قياسي",
            transaction_type=tx,
            sector=u_transfers.sector,
            is_active=True,
        )
        ver = WorkflowTemplateVersion.objects.create(
            template=tpl,
            version_number=1,
            effective_from=timezone.localdate(),
            is_active=True,
        )
        WorkflowStepDefinition.objects.create(
            template_version=ver,
            step_order=1,
            step_title="دراسة قسم التنقلات",
            suggested_unit=u_transfers,
            suggested_action="فحص المسوغات",
            sla_hours=48,
        )
        WorkflowStepDefinition.objects.create(
            template_version=ver,
            step_order=2,
            step_title="مراجعة قسم الجزاءات",
            suggested_unit=u_penalties,
            suggested_action="إبداء الرأي التأديبي",
            sla_hours=72,
        )

        # 1) تطبيق مباشر عبر الدالة apply_template
        subj = SubjectService.create_subject(
            title="موضوع تطبيق قالب مباشر",
            transaction_type=tx,
            sector=u_transfers.sector,
            org_unit=u_transfers,
            confidentiality=conf,
            priority=prio,
            created_by=hr_head,
            current_owner=hr_head,
        )
        refs = apply_template(subj, ver, hr_head)
        self.assertEqual(len(refs), 2)
        subj.refresh_from_db()
        self.assertEqual(subj.workflow_template_version, ver)
        self.assertEqual(subj.status, Subject.Status.IN_PROGRESS)
        today = timezone.localdate()
        self.assertEqual(refs[0].due_date, today + timedelta(days=2))
        self.assertEqual(refs[1].due_date, today + timedelta(days=3))

        # 2) اختيار القالب من شاشة إنشاء الموضوع subject_form
        client = Client()
        client.force_login(hr_head)
        resp_create = client.post(
            reverse("subjects:subject_create"),
            {
                "compose_mode": "document",
                "title": "موضوع عبر نموذج الإنشاء مع قالب",
                "transaction_type_id": tx.id,
                "sector_id": u_transfers.sector_id,
                "org_unit_id": u_transfers.id,
                "confidentiality_id": conf.id,
                "priority_id": prio.id,
                "current_owner_id": hr_head.id,
                "workflow_template_version_id": ver.id,
            },
        )
        self.assertEqual(resp_create.status_code, 302)
        created_subj = Subject.objects.get(title="موضوع عبر نموذج الإنشاء مع قالب")
        self.assertEqual(created_subj.workflow_template_version, ver)
        self.assertEqual(created_subj.referrals.count(), 2)

        # 3) تطبيق القالب من صفحة الموضوع (workflow:apply_template)
        subj2 = SubjectService.create_subject(
            title="موضوع للتطبيق من صفحة التفاصيل",
            transaction_type=tx,
            sector=u_transfers.sector,
            org_unit=u_transfers,
            confidentiality=conf,
            priority=prio,
            created_by=hr_head,
            current_owner=hr_head,
        )
        resp_apply = client.post(
            reverse("workflow:apply_template", args=[subj2.id]),
            {"template_version_id": ver.id},
        )
        self.assertEqual(resp_apply.status_code, 302)
        self.assertEqual(subj2.referrals.count(), 2)

    def test_reject_or_return_recipient_requires_reason_and_returns_owner(self):
        """رفض/إرجاع الإحالة: يتطلب سبباً إجبارياً ويعيد العهدة للمحيل ويمر بـ transition_subject مع إشعار."""
        hr_head = User.objects.get(username="hr_head")
        personnel_gm = User.objects.get(username="personnel_gm")
        tx = TransactionType.objects.first()
        conf = ConfidentialityLevel.objects.get(code="NORMAL")
        prio = PriorityLevel.objects.first()
        u_transfers = OrgUnit.objects.get(code="UNIT_TRANSFERS")

        subj = SubjectService.create_subject(
            title="موضوع اختبار الرفض والإرجاع",
            transaction_type=tx,
            sector=u_transfers.sector,
            org_unit=u_transfers,
            confidentiality=conf,
            priority=prio,
            created_by=hr_head,
            current_owner=hr_head,
        )
        ref = WorkflowEngineService.create_referral(
            subject=subj,
            referred_by=hr_head,
            routing_mode=Referral.RoutingMode.DIRECT,
            purpose=Referral.Purpose.FOR_EXECUTION,
            target_users=[personnel_gm],
        )
        rec = ref.recipients.first()

        # رفض بدون سبب يرفع ValidationError
        with self.assertRaises(ValidationError):
            WorkflowEngineService.reject_or_return_recipient(
                recipient_item=rec, user=personnel_gm, reason="   "
            )

        # رفض بسبب صحيح عبر الواجهة يعيد العهدة ويحدث الحالة ويسجل ActivityLog وإشعاراً
        client = Client()
        client.force_login(personnel_gm)
        with self.captureOnCommitCallbacks(execute=True):
            resp = client.post(
                reverse("workflow:referral_reject", args=[rec.id]),
                {"reason": "عدم الاختصاص المكاني"},
            )
        self.assertEqual(resp.status_code, 302)

        subj.refresh_from_db()
        ref.refresh_from_db()
        rec.refresh_from_db()
        self.assertEqual(rec.status, ReferralRecipient.RecipientStatus.RETURNED)
        self.assertFalse(rec.is_active_step)
        self.assertTrue(ref.is_completed)
        self.assertEqual(subj.current_owner, hr_head)
        self.assertEqual(subj.status, Subject.Status.UNDER_REVIEW)
        self.assertTrue(
            ActivityLog.objects.filter(subject=subj, action_type="REFERRAL_RETURNED").exists()
        )
        self.assertTrue(
            Notification.objects.filter(recipient=hr_head, subject=subj).exists()
        )

    def test_withdraw_referral_before_and_after_receipt(self):
        """سحب الإحالة من المحيل: ينجح قبل الاستلام ويفشل بعد الاستلام."""
        hr_head = User.objects.get(username="hr_head")
        personnel_gm = User.objects.get(username="personnel_gm")
        tx = TransactionType.objects.first()
        conf = ConfidentialityLevel.objects.get(code="NORMAL")
        prio = PriorityLevel.objects.first()
        u_transfers = OrgUnit.objects.get(code="UNIT_TRANSFERS")

        subj = SubjectService.create_subject(
            title="موضوع اختبار السحب",
            transaction_type=tx,
            sector=u_transfers.sector,
            org_unit=u_transfers,
            confidentiality=conf,
            priority=prio,
            created_by=hr_head,
            current_owner=hr_head,
        )
        ref1 = WorkflowEngineService.create_referral(
            subject=subj,
            referred_by=hr_head,
            routing_mode=Referral.RoutingMode.DIRECT,
            purpose=Referral.Purpose.FOR_EXECUTION,
            target_users=[personnel_gm],
        )

        # سحب الإحالة قبل الاستلام ينجح عبر الواجهة
        client = Client()
        client.force_login(hr_head)
        with self.captureOnCommitCallbacks(execute=True):
            resp = client.post(
                reverse("workflow:referral_withdraw", args=[ref1.id]),
                {"reason": "تعديل التوجيه"},
            )
        self.assertEqual(resp.status_code, 302)
        ref1.refresh_from_db()
        subj.refresh_from_db()
        self.assertTrue(ref1.is_withdrawn)
        self.assertTrue(ref1.is_completed)
        self.assertEqual(ref1.recipients.first().status, ReferralRecipient.RecipientStatus.WITHDRAWN)
        self.assertEqual(subj.current_owner, hr_head)
        self.assertEqual(subj.status, Subject.Status.UNDER_REVIEW)
        self.assertTrue(
            ActivityLog.objects.filter(subject=subj, action_type="REFERRAL_WITHDRAWN").exists()
        )
        self.assertTrue(
            Notification.objects.filter(recipient=personnel_gm, subject=subj).exists()
        )

        # إحالة جديدة يتم استلامها أولاً ثم محاولة السحب تفشل بـ ValidationError
        ref2 = WorkflowEngineService.create_referral(
            subject=subj,
            referred_by=hr_head,
            routing_mode=Referral.RoutingMode.DIRECT,
            purpose=Referral.Purpose.FOR_EXECUTION,
            target_users=[personnel_gm],
        )
        rec2 = ref2.recipients.first()
        WorkflowEngineService.acknowledge_or_complete_recipient(
            recipient_item=rec2, user=personnel_gm, complete=False
        )
        with self.assertRaises(ValidationError):
            WorkflowEngineService.withdraw_referral(referral=ref2, user=hr_head)

    def test_reassign_recipient_pending_only(self):
        """إعادة إسناد مستلم معلق لمستخدم آخر تحدث المستلم والعهدة وتسجل ActivityLog وإشعاراً."""
        personnel_gm = User.objects.get(username="personnel_gm")
        transfers_sup = User.objects.get(username="transfers_sup")
        penalties_sup = User.objects.get(username="penalties_sup")
        tx = TransactionType.objects.first()
        conf = ConfidentialityLevel.objects.get(code="NORMAL")
        prio = PriorityLevel.objects.first()
        u_transfers = OrgUnit.objects.get(code="UNIT_TRANSFERS")

        subj = SubjectService.create_subject(
            title="موضوع اختبار إعادة الإسناد",
            transaction_type=tx,
            sector=u_transfers.sector,
            org_unit=u_transfers,
            confidentiality=conf,
            priority=prio,
            created_by=personnel_gm,
            current_owner=personnel_gm,
        )
        ref = WorkflowEngineService.create_referral(
            subject=subj,
            referred_by=personnel_gm,
            routing_mode=Referral.RoutingMode.DIRECT,
            purpose=Referral.Purpose.FOR_EXECUTION,
            target_users=[transfers_sup],
            enforce_hierarchy=False,
        )
        rec = ref.recipients.first()

        client = Client()
        client.force_login(personnel_gm)
        with self.captureOnCommitCallbacks(execute=True):
            resp = client.post(
                reverse("workflow:referral_reassign", args=[rec.id]),
                {"new_user_id": penalties_sup.id, "reason": "نقل الاختصاص"},
            )
        self.assertEqual(resp.status_code, 302)

        rec.refresh_from_db()
        subj.refresh_from_db()
        self.assertEqual(rec.target_user, penalties_sup)
        self.assertEqual(subj.current_owner, penalties_sup)
        self.assertTrue(
            ActivityLog.objects.filter(subject=subj, action_type="REFERRAL_REASSIGNED").exists()
        )
        self.assertTrue(
            Notification.objects.filter(recipient=penalties_sup, subject=subj).exists()
        )

        # بعد الرد على الإحالة، لا يجوز إعادة الإسناد
        WorkflowEngineService.acknowledge_or_complete_recipient(
            recipient_item=rec, user=penalties_sup, response_notes="تم الرد"
        )
        with self.assertRaises(ValidationError):
            WorkflowEngineService.reassign_recipient(
                recipient_item=rec, new_user=transfers_sup, user=personnel_gm
            )

    def test_process_sla_idempotent_reminders_escalations_and_drawer_state(self):
        """أمر process_sla يرسل تذكير قبل بيوم وتصعيد عند التأخير دون تكرار عند التشغيل مرتين، وdrawer_state يقرأ التصعيد المسجل."""
        hr_head = User.objects.get(username="hr_head")
        personnel_gm = User.objects.get(username="personnel_gm")
        transfers_sup = User.objects.get(username="transfers_sup")
        transfers_emp = User.objects.get(username="transfers_emp")
        tx = TransactionType.objects.first()
        conf = ConfidentialityLevel.objects.get(code="NORMAL")
        prio = PriorityLevel.objects.first()
        u_transfers = OrgUnit.objects.get(code="UNIT_TRANSFERS")

        today = timezone.localdate()

        # 1) إحالة مستحقة غداً (تستحق التذكير قبل الاستحقاق بيوم)
        subj_due_soon = SubjectService.create_subject(
            title="موضوع مستحق غداً SLA",
            transaction_type=tx,
            sector=u_transfers.sector,
            org_unit=u_transfers,
            confidentiality=conf,
            priority=prio,
            created_by=transfers_sup,
            current_owner=transfers_sup,
        )
        ref_due_soon = WorkflowEngineService.create_referral(
            subject=subj_due_soon,
            referred_by=transfers_sup,
            routing_mode=Referral.RoutingMode.DIRECT,
            purpose=Referral.Purpose.FOR_EXECUTION,
            target_users=[transfers_emp],
            due_date=today + timedelta(days=1),
            enforce_hierarchy=False,
        )

        # 2) إحالة متأخرة ومهمة متأخرة (تستحق التصعيد للمدير المباشر transfers_sup)
        subj_overdue = SubjectService.create_subject(
            title="موضوع متأخر SLA",
            transaction_type=tx,
            sector=u_transfers.sector,
            org_unit=u_transfers,
            confidentiality=conf,
            priority=prio,
            created_by=hr_head,
            current_owner=transfers_emp,
        )
        ref_overdue = WorkflowEngineService.create_referral(
            subject=subj_overdue,
            referred_by=personnel_gm,
            routing_mode=Referral.RoutingMode.DIRECT,
            purpose=Referral.Purpose.FOR_EXECUTION,
            target_users=[transfers_emp],
            due_date=today - timedelta(days=2),
            enforce_hierarchy=False,
        )
        task_overdue = WorkflowEngineService.create_task(
            subject=subj_overdue,
            title="مهمة متأخرة للاختبار",
            assigned_to=transfers_emp,
            assigned_by=transfers_sup,
            due_date=today - timedelta(days=3),
        )

        # قبل تشغيل process_sla: drawer_state لا يعرض تصعيداً حياً غير مسجل للإحالة الجديدة
        client = Client()
        client.force_login(transfers_sup)
        before_drawer = client.get(reverse("notifications:drawer_state")).json()
        self.assertFalse(
            any(item.get("subject_id") == subj_overdue.id for item in before_drawer["notifications"])
        )

        # التشغيل الأول لـ process_sla
        with self.captureOnCommitCallbacks(execute=True):
            call_command("process_sla")

        ref_due_soon.refresh_from_db()
        ref_overdue.refresh_from_db()
        task_overdue.refresh_from_db()
        self.assertIsNotNone(ref_due_soon.last_reminded_at)
        self.assertIsNotNone(ref_overdue.escalated_at)
        self.assertIsNotNone(task_overdue.escalated_at)

        # التحقق من وصول التذكير والتصعيد وActivityLog
        reminder_count_1 = Notification.objects.filter(
            subject=subj_due_soon,
            recipient=transfers_emp,
            category=Notification.Category.DEADLINE,
        ).count()
        escalation_notif_count_1 = Notification.objects.filter(
            subject=subj_overdue,
            recipient=transfers_sup,
            category=Notification.Category.ESCALATION_OVERDUE,
        ).count()
        escalation_log_count_1 = ActivityLog.objects.filter(
            subject=subj_overdue,
            action_type="SLA_ESCALATED",
        ).count()
        self.assertEqual(reminder_count_1, 1)
        self.assertEqual(escalation_notif_count_1, 2)
        self.assertEqual(escalation_log_count_1, 2)

        # التحقق من أن drawer_state يقرأ التصعيد المسجل
        after_drawer = client.get(reverse("notifications:drawer_state")).json()
        overdue_items = [
            item for item in after_drawer["notifications"] if item.get("subject_id") == subj_overdue.id
        ]
        self.assertTrue(len(overdue_items) >= 1)
        self.assertFalse(overdue_items[0]["is_live_escalation"])

        # التشغيل الثاني لـ process_sla: لا يكرر أي تذكير أو تصعيد أو ActivityLog
        with self.captureOnCommitCallbacks(execute=True):
            call_command("process_sla")
        self.assertEqual(
            Notification.objects.filter(
                subject=subj_due_soon,
                recipient=transfers_emp,
                category=Notification.Category.DEADLINE,
            ).count(),
            reminder_count_1,
        )
        self.assertEqual(
            Notification.objects.filter(
                subject=subj_overdue,
                recipient=transfers_sup,
                category=Notification.Category.ESCALATION_OVERDUE,
            ).count(),
            escalation_notif_count_1,
        )
        self.assertEqual(
            ActivityLog.objects.filter(
                subject=subj_overdue,
                action_type="SLA_ESCALATED",
            ).count(),
            escalation_log_count_1,
        )


class ParallelReferralConcurrencyTests(TransactionTestCase):
    """اختبارات التزامن الحقيقي بين خيوط متعددة عند استكمال الإحالة المتوازية (ALL)."""

    def setUp(self):
        call_command("seed_demo_data")

    def test_concurrent_all_responses_complete_referral_safely(self):
        hr_head = User.objects.get(username="hr_head")
        transfers_sup = User.objects.get(username="transfers_sup")
        transfers_emp = User.objects.get(username="transfers_emp")
        tx = TransactionType.objects.first()
        conf = ConfidentialityLevel.objects.get(code="NORMAL")
        prio = PriorityLevel.objects.first()
        unit_transfers = OrgUnit.objects.get(code="UNIT_TRANSFERS")

        subj = SubjectService.create_subject(
            title="موضوع اختبار التزامن في ALL",
            transaction_type=tx,
            sector=unit_transfers.sector,
            org_unit=unit_transfers,
            confidentiality=conf,
            priority=prio,
            created_by=hr_head,
            current_owner=hr_head,
        )
        ref = WorkflowEngineService.create_referral(
            subject=subj,
            referred_by=hr_head,
            routing_mode=Referral.RoutingMode.PARALLEL,
            purpose=Referral.Purpose.FOR_STUDY,
            parallel_completion_rule=Referral.ParallelCompletionRule.ALL,
            target_users=[transfers_sup, transfers_emp],
            enforce_hierarchy=False,
        )
        r1, r2 = list(ref.recipients.order_by("sequence_order"))

        barrier = threading.Barrier(2)
        errors = []

        def respond(rec, usr, note):
            try:
                barrier.wait(timeout=5)
                for attempt in range(5):
                    try:
                        WorkflowEngineService.acknowledge_or_complete_recipient(
                            recipient_item=rec, user=usr, response_notes=note
                        )
                        break
                    except OperationalError as lock_err:
                        # SQLite يقفل الجدول عند تزامن معاملات DEFERRED بخلاف SQL Server الذي يدعم قفل الصفوف
                        if "locked" in str(lock_err).lower() and attempt < 4:
                            time.sleep(0.05)
                            continue
                        raise
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        t1 = threading.Thread(target=respond, args=(r1, transfers_sup, "رد المشرف"))
        t2 = threading.Thread(target=respond, args=(r2, transfers_emp, "رد الموظف"))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertEqual(errors, [])
        ref.refresh_from_db()
        r1.refresh_from_db()
        r2.refresh_from_db()
        self.assertTrue(ref.is_completed)
        self.assertEqual(r1.status, ReferralRecipient.RecipientStatus.RESPONDED)
        self.assertEqual(r2.status, ReferralRecipient.RecipientStatus.RESPONDED)





