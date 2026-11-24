"""
حزمة الاختبارات الأمنية الشاملة (Security & Isolation Test Suite):
1. إنشاء المستخدمين من داخل النظام لـ Superuser فقط.
2. تشديد صلاحيات المهام (Tasks) والقرارات (Decisions) وتنفيذها.
3. تأمين المستندات والمرفقات السرية والسرية للغاية (المرتبطة والمستقلة).
4. فرض قيود وصلاحيات الإحالة على المستخدمين والوحدات التنظيمية معاً.
5. عزل القطاعات والوحدات التنظيمية في الطبقة المنطقية المركزية (CorrespondenceAccessPolicy) واللجان.
"""
from datetime import timedelta
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import Delegation, Role, User, UserRoleAssignment
from accounts.services import PermissionService
from audit.models import AuditLog
from committees.models import Committee, CommitteeMeeting
from core.models import ConfidentialityLevel, DocumentType, PriorityLevel, TransactionType
from decisions.models import Decision
from decisions.services import DecisionService
from documents.models import Document
from documents.services import DocumentService
from organization.models import OrgUnit, OrgUnitType, Sector
from subjects.models import Subject
from subjects.services import SubjectService
from workflow.models import Referral, Task
from workflow.services import WorkflowEngineService


class SecurityAndIsolationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo_data")

    # =========================================================================
    # 1. إضافة المستخدمين وإدارة الأدوار من داخل النظام (Superuser فقط)
    # =========================================================================
    def test_superuser_only_user_creation_and_role_management(self):
        client = Client()
        hr_head = User.objects.get(username="hr_head")
        transfers_emp = User.objects.get(username="transfers_emp")
        superuser = User.objects.get(username="an")
        u_transfers = OrgUnit.objects.get(code="UNIT_TRANSFERS")
        r_emp = Role.objects.get(code="SPECIALIST")

        url = reverse("accounts:users_list")

        # منع غير الـ Superuser من الوصول أو الإنشاء
        for non_su in (hr_head, transfers_emp):
            client.force_login(non_su)
            self.assertEqual(client.get(url).status_code, 403)
            resp = client.post(
                url,
                {
                    "action": "create_user",
                    "username": "unauth_user",
                    "password": "Password@1",
                    "full_name": "محاولة غير مصرحة",
                },
            )
            self.assertEqual(resp.status_code, 403)
            self.assertFalse(User.objects.filter(username="unauth_user").exists())

        # السماح للـ Superuser (an) بإنشاء مستخدم كامل مع موظف ودور وتسجيل التدقيق
        client.force_login(superuser)
        resp = client.post(
            url,
            {
                "action": "create_user",
                "username": "new_specialist",
                "password": "NewUser@2026",
                "full_name": "أ. سامح أخصائي جديد",
                "job_display_title": "أخصائي تنقلات",
                "org_unit_id": u_transfers.id,
                "role_id": r_emp.id,
                "sector_id": u_transfers.sector_id,
                "is_active": "on",
            },
        )
        self.assertEqual(resp.status_code, 302)

        created = User.objects.get(username="new_specialist")
        self.assertFalse(created.is_superuser)
        self.assertFalse(created.is_system_admin)
        self.assertIsNotNone(created.employee)
        self.assertEqual(created.current_unit, u_transfers)
        self.assertTrue(
            UserRoleAssignment.objects.filter(user=created, role=r_emp, org_unit=u_transfers, is_active=True).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(action="USER_CREATED", model_name="User", object_id=created.id).exists()
        )

        # التأكد من قدرة المستخدم الجديد على تسجيل الدخول فعلياً
        client.logout()
        logged_in = client.login(username="new_specialist", password="NewUser@2026")
        self.assertTrue(logged_in)

        # اختبار إزالة الدور بواسطة Superuser
        client.force_login(superuser)
        assignment = UserRoleAssignment.objects.get(user=created, role=r_emp)
        resp_rm = client.post(url, {"action": "remove_role", "assignment_id": assignment.id})
        self.assertEqual(resp_rm.status_code, 302)
        self.assertFalse(UserRoleAssignment.objects.filter(id=assignment.id).exists())

    # =========================================================================
    # 2. تشديد صلاحيات المهام (Tasks) والقرارات (Decisions)
    # =========================================================================
    def test_task_creation_and_update_strict_authorization(self):
        client = Client()
        hr_head = User.objects.get(username="hr_head")
        personnel_gm = User.objects.get(username="personnel_gm")
        transfers_sup = User.objects.get(username="transfers_sup")
        transfers_emp = User.objects.get(username="transfers_emp")
        housing_emp = User.objects.get(username="housing_emp")

        # s1 مملوك حالياً لـ transfers_emp وفي قطاع الموارد البشرية
        s1 = Subject.objects.filter(applicant_name="محمد محمود علي").first()

        # منع إنشاء مهمة على موضوع ليس في عهدة المستخدم (personnel_gm لا يملك عهدة s1)
        client.force_login(personnel_gm)
        resp_gm = client.post(
            reverse("workflow:task_create", args=[s1.id]),
            {"title": "مهمة غير مصرحة", "assigned_to_id": transfers_emp.id},
        )
        self.assertEqual(resp_gm.status_code, 403)

        # منع تكليف موظف من قطاع آخر (housing_emp في FIN_HR)
        client.force_login(transfers_emp)
        resp_cross = client.post(
            reverse("workflow:task_create", args=[s1.id]),
            {"title": "مهمة عبر القطاعات", "assigned_to_id": housing_emp.id},
        )
        # transfers_emp لا يملك TASK_CREATE أصلاً -> 403
        self.assertEqual(resp_cross.status_code, 403)

        # إنشاء مهمة مشروعة: نعطي hr_head العهدة ثم يكلف transfers_emp، ثم نحاول كـ housing_emp
        s5_hr = SubjectService.create_subject(
            title="موضوع مهام تحت عهدة رئيس القطاع",
            transaction_type=TransactionType.objects.filter(sector=s1.sector).first(),
            sector=s1.sector,
            org_unit=s1.org_unit,
            confidentiality=s1.confidentiality,
            priority=s1.priority,
            created_by=hr_head,
            current_owner=hr_head,
        )
        client.force_login(hr_head)
        resp_cross_sector = client.post(
            reverse("workflow:task_create", args=[s5_hr.id]),
            {"title": "تكليف لقطاع آخر", "assigned_to_id": housing_emp.id},
        )
        self.assertEqual(resp_cross_sector.status_code, 403)

        # إنشاء مهمة صحيحة للموظف transfers_emp
        resp_ok = client.post(
            reverse("workflow:task_create", args=[s5_hr.id]),
            {"title": "دراسة ملف رسمي", "assigned_to_id": transfers_emp.id},
        )
        self.assertEqual(resp_ok.status_code, 302)
        task = Task.objects.get(subject=s5_hr, title="دراسة ملف رسمي")

        # منع أي مستخدم آخر يرى الموضوع (مثل personnel_gm أو transfers_sup) من تعديل حالة مهمة غيره
        for unauthorized_actor in (personnel_gm, transfers_sup):
            client.force_login(unauthorized_actor)
            resp_upd = client.post(
                reverse("workflow:task_update_status", args=[task.id]),
                {"status": Task.TaskStatus.COMPLETED, "outcome": "تدخل غير مصرح"},
            )
            self.assertEqual(resp_upd.status_code, 403)
            task.refresh_from_db()
            self.assertNotEqual(task.status, Task.TaskStatus.COMPLETED)

        # الموظف المكلف فقط (transfers_emp) يمكنه تحديث المهمة، ومع حالة غير صالحة لا ينهار النظام
        client.force_login(transfers_emp)
        resp_bad_status = client.post(
            reverse("workflow:task_update_status", args=[task.id]),
            {"status": "INVALID_STATE"},
        )
        self.assertEqual(resp_bad_status.status_code, 302)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.TaskStatus.NEW)

        resp_good = client.post(
            reverse("workflow:task_update_status", args=[task.id]),
            {"status": Task.TaskStatus.COMPLETED, "outcome": "أنجزت بنجاح"},
        )
        self.assertEqual(resp_good.status_code, 302)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.TaskStatus.COMPLETED)

    def test_decision_approval_distribution_and_execution_isolation(self):
        client = Client()
        hr_head = User.objects.get(username="hr_head")
        personnel_gm = User.objects.get(username="personnel_gm")
        transfers_emp = User.objects.get(username="transfers_emp")
        penalties_emp = User.objects.get(username="penalties_emp")
        u_transfers = OrgUnit.objects.get(code="UNIT_TRANSFERS")
        u_housing = OrgUnit.objects.get(code="UNIT_HOUSING")
        s1 = Subject.objects.filter(applicant_name="محمد محمود علي").first()

        # إعداد قرار مشروع بواسطة المالك الحالي للموضوع
        decision = DecisionService.create_decision_draft(
            subject=s1,
            decision_type=Decision.DecisionType.TRANSFER,
            title="قرار اختبار الأمان",
            body="نص القرار",
            issuing_authority="رئيس القطاع",
            approving_authority="رئيس القطاع",
            created_by=transfers_emp,
        )

        # الموظف المختص والمدير العام لا يملكان DECISION_APPROVE
        for non_approver in (transfers_emp, personnel_gm):
            with self.assertRaises(PermissionDenied):
                DecisionService.approve_and_issue(decision=decision, user=non_approver)

        # الاعتماد بواسطة رئيس القطاع المختص
        DecisionService.approve_and_issue(decision=decision, user=hr_head)

        # منع توزيع القرار على وحدة في قطاع آخر (UNIT_HOUSING في FIN_HR)
        with self.assertRaises(PermissionDenied):
            DecisionService.distribute_and_assign_execution(
                decision=decision,
                user=hr_head,
                distribution_units=[u_housing],
                execution_assignments=[],
            )

        # منع غير المخولين من التوزيع أو التكليف بالتنفيذ
        with self.assertRaises(PermissionDenied):
            DecisionService.distribute_and_assign_execution(
                decision=decision,
                user=transfers_emp,
                distribution_units=[u_transfers],
                execution_assignments=[],
            )

        # التوزيع والتكليف الصحيح داخل نفس القطاع
        DecisionService.distribute_and_assign_execution(
            decision=decision,
            user=hr_head,
            distribution_units=[u_transfers],
            execution_assignments=[
                {"unit": u_transfers, "user": transfers_emp, "required_action": "تنفيذ القرار"}
            ],
        )
        exec_item = decision.execution_items.first()

        # منع مستخدم غير مكلف بالتنفيذ من إغلاق بند التنفيذ (الخدمة والواجهة)
        with self.assertRaises(PermissionDenied):
            DecisionService.complete_execution_item(
                exec_item=exec_item, user=penalties_emp, execution_result="محاولة تزوير"
            )
        client.force_login(personnel_gm)
        resp_exec = client.post(
            reverse("decisions:decision_detail", args=[decision.id]),
            {
                "action": "complete_execution",
                "exec_item_id": exec_item.id,
                "execution_result": "محاولة غير مخولة",
            },
        )
        self.assertEqual(resp_exec.status_code, 403)

    # =========================================================================
    # 3. تأمين المستندات والمرفقات السرية (المرتبطة والمستقلة)
    # =========================================================================
    def test_confidential_documents_and_attachments_isolation(self):
        client = Client()
        hr_head = User.objects.get(username="hr_head")
        personnel_gm = User.objects.get(username="personnel_gm")
        transfers_sup = User.objects.get(username="transfers_sup")
        transfers_emp = User.objects.get(username="transfers_emp")
        housing_emp = User.objects.get(username="housing_emp")
        doc_type = DocumentType.objects.first()
        conf_secret = ConfidentialityLevel.objects.get(code="CONFIDENTIAL")
        conf_top = ConfidentialityLevel.objects.get(code="TOP_SECRET")

        # أ) مستند مستقل سري للغاية أنشأه رئيس القطاع
        top_pdf = SimpleUploadedFile("secret_standalone.pdf", b"%PDF-1.4 top secret", content_type="application/pdf")
        standalone_top = DocumentService.register_document(
            title="تقرير رقابي سري للغاية مستقل",
            doc_type=doc_type,
            confidentiality=conf_top,
            created_by=hr_head,
            uploaded_file=top_pdf,
        )
        top_attachment = standalone_top.versions.first().attachments.first()

        # يجب أن يُمنع المدير العام والمشرف وموظف قطاع آخر من رؤيته وتنزيله
        for user_obj in (personnel_gm, transfers_sup, housing_emp):
            self.assertFalse(PermissionService.can_view_document(user_obj, standalone_top))
            self.assertFalse(PermissionService.can_download_attachment(user_obj, top_attachment))
            client.force_login(user_obj)
            self.assertEqual(client.get(reverse("documents:document_detail", args=[standalone_top.id])).status_code, 403)
            self.assertEqual(client.get(reverse("documents:attachment_download", args=[top_attachment.id])).status_code, 403)
            self.assertNotContains(
                client.get(reverse("documents:document_list")), standalone_top.internal_number
            )

        self.assertTrue(
            AuditLog.objects.filter(
                actor_user=personnel_gm,
                action="UNAUTHORIZED_ATTACHMENT_ACCESS",
                model_name="Attachment",
                object_id=top_attachment.id,
            ).exists()
        )

        # ب) مستند مستقل بدرجة «سري»: معزول عن مشرف (بدون صلاحية السري) وعن قطاع آخر
        secret_doc = DocumentService.register_document(
            title="مكاتبة سرية مستقلة",
            doc_type=doc_type,
            confidentiality=conf_secret,
            created_by=hr_head,
        )
        self.assertFalse(PermissionService.can_view_document(transfers_sup, secret_doc))
        self.assertFalse(PermissionService.can_view_document(housing_emp, secret_doc))
        self.assertTrue(PermissionService.can_view_document(hr_head, secret_doc))

        # ج) مستند سري للغاية مرتبط بموضوع سري للغاية (s5): المدير العام ممنوع من تنزيله والمختص المباشر مسموح له
        s5 = Subject.objects.get(confidentiality__code="TOP_SECRET")
        s5_pdf = SimpleUploadedFile("s5_secret.pdf", b"%PDF-1.4 s5", content_type="application/pdf")
        s5_doc = DocumentService.register_document(
            title="مرفق البيان السري للغاية",
            doc_type=doc_type,
            confidentiality=conf_top,
            created_by=hr_head,
            subject=s5,
            uploaded_file=s5_pdf,
        )
        s5_att = s5_doc.versions.first().attachments.first()
        self.assertFalse(PermissionService.can_view_document(personnel_gm, s5_doc))
        self.assertFalse(PermissionService.can_download_attachment(personnel_gm, s5_att))
        self.assertTrue(PermissionService.can_download_attachment(transfers_emp, s5_att))

        # د) منع إصدار نسخة جديدة أو ربط مستند بموضوع لا يملك المستخدم عهدته
        client.force_login(personnel_gm)
        s1 = Subject.objects.filter(applicant_name="محمد محمود علي").first()
        s1_doc = s1.documents.first()
        resp_ver = client.post(
            reverse("documents:document_detail", args=[s1_doc.id]),
            {"action": "new_version", "change_reason": "تعديل بدون عهدة"},
        )
        self.assertEqual(resp_ver.status_code, 403)

    # =========================================================================
    # 4. فرض صلاحيات الإحالة على المستخدمين والوحدات التنظيمية معاً
    # =========================================================================
    def test_referral_enforces_user_and_org_unit_permissions(self):
        personnel_gm = User.objects.get(username="personnel_gm")
        transfers_sup = User.objects.get(username="transfers_sup")
        transfers_emp = User.objects.get(username="transfers_emp")
        u_transfers = OrgUnit.objects.get(code="UNIT_TRANSFERS")
        u_penalties = OrgUnit.objects.get(code="UNIT_PENALTIES")
        u_housing = OrgUnit.objects.get(code="UNIT_HOUSING")
        u_chair = OrgUnit.objects.get(code="UNIT_CHAIR")

        s_gm = SubjectService.create_subject(
            title="موضوع لدى المدير العام لفحص إحالة الوحدات",
            transaction_type=TransactionType.objects.filter(sector=u_transfers.sector).first(),
            sector=u_transfers.sector,
            org_unit=u_transfers,
            confidentiality=ConfidentialityLevel.objects.get(code="NORMAL"),
            priority=PriorityLevel.objects.first(),
            created_by=personnel_gm,
            current_owner=personnel_gm,
        )

        # الوحدات المسموح للمدير العام بالإحالة إليها: وحدات إدارته فقط (لا يرى قطاعاً آخر ولا مكتب رئيس المجلس)
        allowed_units_gm = set(PermissionService.get_allowed_referral_units(personnel_gm, s_gm).values_list("id", flat=True))
        self.assertIn(u_transfers.id, allowed_units_gm)
        self.assertNotIn(u_housing.id, allowed_units_gm)
        self.assertNotIn(u_chair.id, allowed_units_gm)

        # رفض الإحالة لوحدة خارج قطاع/نطاق المدير العام
        with self.assertRaises(ValidationError):
            WorkflowEngineService.create_referral(
                subject=s_gm,
                referred_by=personnel_gm,
                routing_mode=Referral.RoutingMode.DIRECT,
                purpose=Referral.Purpose.FOR_EXECUTION,
                target_units=[u_housing],
            )

        # رفض تحديد required_unit خارج النطاق المسموح
        with self.assertRaises(ValidationError):
            WorkflowEngineService.create_referral(
                subject=s_gm,
                referred_by=personnel_gm,
                routing_mode=Referral.RoutingMode.PARALLEL,
                purpose=Referral.Purpose.FOR_STUDY,
                target_units=[u_transfers],
                required_unit=u_chair,
            )

        # الإحالة لوحدة قسم التنقلات تنجح
        ref_unit = WorkflowEngineService.create_referral(
            subject=s_gm,
            referred_by=personnel_gm,
            routing_mode=Referral.RoutingMode.DIRECT,
            purpose=Referral.Purpose.FOR_EXECUTION,
            target_units=[u_transfers],
        )
        self.assertEqual(ref_unit.recipients.first().target_unit, u_transfers)

        # مشرف القسم (transfers_sup): وحدته المسموحة هي قسمه فقط، وتُرفض الإحالة لقسم شقيق
        s_sup = SubjectService.create_subject(
            title="موضوع لدى مشرف التنقلات",
            transaction_type=s_gm.transaction_type,
            sector=u_transfers.sector,
            org_unit=u_transfers,
            confidentiality=s_gm.confidentiality,
            priority=s_gm.priority,
            created_by=transfers_sup,
            current_owner=transfers_sup,
        )
        allowed_units_sup = list(PermissionService.get_allowed_referral_units(transfers_sup, s_sup))
        self.assertEqual(allowed_units_sup, [u_transfers])
        with self.assertRaises(ValidationError):
            WorkflowEngineService.create_referral(
                subject=s_sup,
                referred_by=transfers_sup,
                routing_mode=Referral.RoutingMode.DIRECT,
                purpose=Referral.Purpose.FOR_EXECUTION,
                target_units=[u_penalties],
            )

        # الموظف المختص لا يملك أي مستخدمين أو وحدات مسموح بالإحالة إليها
        s_emp = Subject.objects.filter(applicant_name="محمد محمود علي").first()
        self.assertEqual(PermissionService.get_allowed_referral_targets(transfers_emp, s_emp).count(), 0)
        self.assertEqual(PermissionService.get_allowed_referral_units(transfers_emp, s_emp).count(), 0)

    # =========================================================================
    # 5. عزل القطاعات والوحدات في الطبقة المنطقية المركزية واللجان
    # =========================================================================
    def test_central_sector_and_org_unit_isolation(self):
        client = Client()
        hr_head = User.objects.get(username="hr_head")
        hr_sec = User.objects.get(username="hr_sec")
        personnel_gm = User.objects.get(username="personnel_gm")
        transfers_sup = User.objects.get(username="transfers_sup")
        housing_emp = User.objects.get(username="housing_emp")
        sec_hr = Sector.objects.get(code="HR")
        u_hr_sec = OrgUnit.objects.get(code="UNIT_HR_SECTOR")
        t_gd = OrgUnitType.objects.get(code="GENERAL_DIR")

        # s4 موضوع في قطاع الشئون المالية والموارد البشرية (FIN_HR)
        s4 = Subject.objects.filter(applicant_name="علي علي محمود").first()
        # s1 موضوع في قطاع الموارد البشرية (HR) - قسم التنقلات
        s1 = Subject.objects.filter(applicant_name="محمد محمود علي").first()

        # رئيس قطاع HR ومدير عام الأفراد والمشرفون في HR معزولون عن قطاع FIN_HR
        self.assertFalse(PermissionService.can_view_subject(hr_head, s4))
        self.assertFalse(PermissionService.can_view_subject(personnel_gm, s4))
        self.assertFalse(PermissionService.can_view_subject(transfers_sup, s4))

        client.force_login(hr_head)
        self.assertEqual(client.get(reverse("subjects:subject_detail", args=[s4.id])).status_code, 403)
        self.assertFalse(PermissionService.filter_visible_subjects(Subject.objects.all(), hr_head).filter(id=s4.id).exists())

        # عزل الإدارة العامة عن إدارة عامة شقيقة داخل نفس القطاع
        u_sibling_gd = OrgUnit.objects.create(
            code="UNIT_TRAINING_GD",
            name="الإدارة العامة للتدريب",
            unit_type=t_gd,
            sector=sec_hr,
            parent=u_hr_sec,
        )
        s_training = SubjectService.create_subject(
            title="خطة تدريب سنوية - إدارة التدريب",
            transaction_type=TransactionType.objects.filter(sector=sec_hr).first(),
            sector=sec_hr,
            org_unit=u_sibling_gd,
            confidentiality=ConfidentialityLevel.objects.get(code="NORMAL"),
            priority=PriorityLevel.objects.first(),
            created_by=hr_head,
            current_owner=hr_head,
        )
        # رئيس قطاع HR يرى الإدارتين التابعتين لقطاعه، لكن مدير عام الأفراد معزول عن إدارة التدريب الشقيقة
        self.assertTrue(PermissionService.can_view_subject(hr_head, s_training))
        self.assertTrue(PermissionService.can_view_subject(personnel_gm, s1))
        self.assertFalse(PermissionService.can_view_subject(personnel_gm, s_training))

        # عزل نطاق التفويض (Delegation.scope_unit) عن الوحدات الشقيقة خارج النطاق
        u_penalties = OrgUnit.objects.get(code="UNIT_PENALTIES")
        s_pen = SubjectService.create_subject(
            title="موضوع قسم الجزاءات للاختبار",
            transaction_type=s_training.transaction_type,
            sector=sec_hr,
            org_unit=u_penalties,
            confidentiality=s_training.confidentiality,
            priority=s_training.priority,
            created_by=hr_head,
            current_owner=hr_head,
        )
        # تفويض محصور بنطاق وحدة التدريب فقط
        Delegation.objects.create(
            delegator=hr_head,
            delegate=housing_emp,
            delegation_type=Delegation.DelegationType.ACTING,
            scope_unit=u_sibling_gd,
            allowed_actions=["SUBJECT_VIEW"],
            allow_confidential=False,
            valid_from=timezone.now() - timedelta(days=1),
            valid_to=timezone.now() + timedelta(days=7),
        )
        self.assertTrue(PermissionService.can_view_subject(housing_emp, s_training))
        self.assertFalse(PermissionService.can_view_subject(housing_emp, s_pen))

        # عزل اللجان على مستوى القطاع
        com_housing = Committee.objects.get(code="COM_HOUSING")
        com_personnel = Committee.objects.get(code="COM_PERSONNEL")
        meeting_fin = CommitteeMeeting.objects.create(
            committee=com_housing,
            meeting_number="H-99/2026",
            meeting_date=timezone.localdate(),
            created_by=housing_emp,
        )
        client.force_login(hr_head)
        com_resp = client.get(reverse("committees:committee_list"))
        self.assertContains(com_resp, com_personnel.name)
        self.assertNotContains(com_resp, com_housing.name)
        self.assertEqual(client.get(reverse("committees:meeting_detail", args=[meeting_fin.id])).status_code, 403)
        self.assertEqual(
            client.post(
                reverse("committees:committee_list"),
                {"committee_id": com_housing.id, "meeting_number": "X-1", "meeting_date": str(timezone.localdate())},
            ).status_code,
            403,
        )

        # منع إنشاء موضوع في قطاع غير مصرح به (FIN_HR) بواسطة سكرتارية/موظفي HR
        client.force_login(hr_sec)
        resp_create_cross = client.post(
            reverse("subjects:subject_create"),
            {
                "title": "موضوع عبر قطاع آخر",
                "transaction_type_id": s4.transaction_type_id,
                "sector_id": s4.sector_id,
                "org_unit_id": s4.org_unit_id,
                "confidentiality_id": s4.confidentiality_id,
                "priority_id": s4.priority_id,
            },
        )
        self.assertEqual(resp_create_cross.status_code, 403)
