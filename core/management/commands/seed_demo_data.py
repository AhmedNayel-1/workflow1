"""
أمر إدارة لتهيئة البيانات المرجعية والهيكل التنظيمي لقطاع الموارد البشرية
وحسابات الاختبار والسيناريوهات التشغيلية الخمسة المعتمدة.
"""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from accounts.models import (
    Delegation,
    PermissionCode,
    Role,
    RolePermission,
    User,
    UserRoleAssignment,
)
from committees.models import Committee
from core.models import (
    ConfidentialityLevel,
    DocumentType,
    MemoRecipientRef,
    MemoTypeRef,
    PriorityLevel,
    RetentionPolicy,
    SuspensionReason,
    TransactionType,
)
from documents.models import SubjectDocumentLink
from documents.services import DocumentService
from organization.models import Company, Employee, OrgUnit, OrgUnitType, PositionAssignment, Sector
from subjects.models import Memo
from subjects.services import SubjectService
from workflow.models import Referral, WorkflowStepDefinition, WorkflowTemplate, WorkflowTemplateVersion
from workflow.services import WorkflowEngineService


class Command(BaseCommand):
    help = "تهيئة البيانات المرجعية والتجريبية وحسابات الاختبار والسيناريوهات الخمسة"

    @transaction.atomic
    def handle(self, *args, **options):
        from organization.models import ExternalEntity
        for _c, _n in [("EXT-MOH", "وزارة الصحة"), ("EXT-MOF", "وزارة المالية"), ("EXT-CAPMAS", "الجهاز المركزي للتعبئة العامة والإحصاء"), ("EXT-ACA", "الجهاز المركزي للمحاسبات")]:
            ExternalEntity.objects.get_or_create(code=_c, defaults={"name": _n})
        self.stdout.write("جاري تهيئة البيانات المرجعية...")

        # 1. درجات السرية
        conf_normal, _ = ConfidentialityLevel.objects.get_or_create(
            code="NORMAL", defaults={"name": "عادي", "rank": 1, "overrides_hierarchy": False}
        )
        conf_secret, _ = ConfidentialityLevel.objects.get_or_create(
            code="CONFIDENTIAL", defaults={"name": "سري", "rank": 2, "overrides_hierarchy": False}
        )
        conf_top, _ = ConfidentialityLevel.objects.get_or_create(
            code="TOP_SECRET", defaults={"name": "سري للغاية", "rank": 3, "overrides_hierarchy": True}
        )

        # 2. الأولويات
        prio_normal, _ = PriorityLevel.objects.get_or_create(
            code="NORMAL", defaults={"name": "عادي", "rank": 1, "sla_days": 7}
        )
        prio_urgent, _ = PriorityLevel.objects.get_or_create(
            code="URGENT", defaults={"name": "عاجل", "rank": 2, "sla_days": 2}
        )
        prio_top_urgent, _ = PriorityLevel.objects.get_or_create(
            code="IMMEDIATE", defaults={"name": "عاجل جداً", "rank": 3, "sla_days": 1}
        )

        # 3. أسباب التعليق وسياسات الاحتفاظ وأنواع المستندات
        SuspensionReason.objects.get_or_create(
            code="MISSING_DRUG_TEST", defaults={"name": "عدم تقديم شهادة تحليل مخدرات سلبية"}
        )
        SuspensionReason.objects.get_or_create(
            code="COPY_INSTEAD_OF_ORIGINAL", defaults={"name": "تقديم صورة المؤهل بدلاً من الأصل"}
        )
        RetentionPolicy.objects.get_or_create(
            code="HR_10Y",
            defaults={"name": "سياسة حفظ ملفات الموارد البشرية (10 سنوات)", "retention_years": 10, "allow_auto_disposal": False},
        )
        doc_request, _ = DocumentType.objects.get_or_create(code="REQUEST", defaults={"name": "طلب موظف"})
        doc_invest, _ = DocumentType.objects.get_or_create(code="INVESTIGATION", defaults={"name": "ملف تحقيق"})
        doc_cert, _ = DocumentType.objects.get_or_create(code="CERTIFICATE", defaults={"name": "شهادة / مؤهل"})
        doc_official, _ = DocumentType.objects.get_or_create(code="OFFICIAL_LETTER", defaults={"name": "مكاتبة رسمية"})
        DocumentType.objects.get_or_create(code="MEMO_DOC", defaults={"name": "مذكرة عرض"})
        DocumentType.objects.get_or_create(code="DECISION_DOC", defaults={"name": "قرار إداري"})

        for m_code, m_name in [
            ("PRESENTATION", "مذكرة عرض"),
            ("COMMITTEE", "مذكرة للعرض على اللجنة"),
            ("OPINION", "مذكرة إبداء رأي"),
            ("FULFILLMENT", "مذكرة استيفاء"),
            ("EXECUTION", "مذكرة تنفيذية"),
            ("RE_PRESENTATION", "مذكرة إعادة عرض"),
        ]:
            MemoTypeRef.objects.get_or_create(code=m_code, defaults={"name": m_name, "is_active": True})

        for r_code, r_name in [
            ("CHAIRMAN", "الأستاذ الدكتور / رئيس مجلس الإدارة"),
            ("HR_HEAD", "السيد / رئيس قطاع الموارد البشرية"),
            ("PERSONNEL_GM", "السيد / مدير عام شئون الأفراد"),
            ("PERSONNEL_COM", "لجنة شئون العاملين"),
            ("TRAINING_COM", "لجنة التدريب"),
            ("LEGAL_DIR", "الإدارة العامة للشئون القانونية"),
        ]:
            MemoRecipientRef.objects.get_or_create(code=r_code, defaults={"name": r_name, "is_active": True})

        # 4. الشركة القابضة والقطاعات والهيكل التنظيمي الديناميكي
        holding_company, _ = Company.objects.get_or_create(
            code="EEHC",
            defaults={
                "name": "الشركة القابضة لكهرباء مصر",
                "short_name": "الشركة القابضة",
                "is_holding": True,
                "is_active": True,
            },
        )
        west_delta, _ = Company.objects.get_or_create(
            code="WDEPCO",
            defaults={
                "name": "شركة غرب الدلتا لإنتاج الكهرباء",
                "short_name": "غرب الدلتا",
                "is_holding": False,
                "parent_company": holding_company,
                "is_active": True,
            },
        )
        if west_delta.parent_company_id is None:
            west_delta.parent_company = holding_company
            west_delta.save(update_fields=["parent_company"])

        sec_board, _ = Sector.objects.get_or_create(code="BOARD", defaults={"name": "رئاسة مجلس الإدارة", "company": west_delta})
        sec_hr, _ = Sector.objects.get_or_create(code="HR", defaults={"name": "قطاع الموارد البشرية", "company": west_delta})
        sec_prod, _ = Sector.objects.get_or_create(code="PROD", defaults={"name": "قطاع الإنتاج", "company": west_delta})
        sec_fin_hr, _ = Sector.objects.get_or_create(code="FIN_HR", defaults={"name": "قطاع الشئون المالية والموارد البشرية", "company": west_delta})
        Sector.objects.filter(company__isnull=True).update(company=west_delta)

        t_chair, _ = OrgUnitType.objects.get_or_create(code="CHAIRMAN", defaults={"name": "رئاسة مجلس الإدارة", "level_order": 1})
        t_sector, _ = OrgUnitType.objects.get_or_create(code="SECTOR", defaults={"name": "قطاع", "level_order": 2})
        t_gd, _ = OrgUnitType.objects.get_or_create(code="GENERAL_DIR", defaults={"name": "إدارة عامة", "level_order": 3})
        t_dept, _ = OrgUnitType.objects.get_or_create(code="DEPT", defaults={"name": "إدارة", "level_order": 4})
        t_sec, _ = OrgUnitType.objects.get_or_create(code="SECTION", defaults={"name": "قسم", "level_order": 5})

        u_chair, _ = OrgUnit.objects.get_or_create(
            code="UNIT_CHAIR", defaults={"name": "مكتب رئيس مجلس الإدارة", "unit_type": t_chair, "sector": sec_board}
        )
        u_hr_sec, _ = OrgUnit.objects.get_or_create(
            code="UNIT_HR_SECTOR", defaults={"name": "رئاسة قطاع الموارد البشرية", "unit_type": t_sector, "sector": sec_hr, "parent": u_chair}
        )
        u_personnel_gd, _ = OrgUnit.objects.get_or_create(
            code="UNIT_PERSONNEL_GD", defaults={"name": "الإدارة العامة لشئون الأفراد", "unit_type": t_gd, "sector": sec_hr, "parent": u_hr_sec}
        )
        u_transfers, _ = OrgUnit.objects.get_or_create(
            code="UNIT_TRANSFERS", defaults={"name": "قسم التنقلات", "unit_type": t_sec, "sector": sec_hr, "parent": u_personnel_gd}
        )
        u_penalties, _ = OrgUnit.objects.get_or_create(
            code="UNIT_PENALTIES", defaults={"name": "قسم الجزاءات", "unit_type": t_sec, "sector": sec_hr, "parent": u_personnel_gd}
        )
        u_settlements, _ = OrgUnit.objects.get_or_create(
            code="UNIT_SETTLEMENTS", defaults={"name": "قسم التسويات", "unit_type": t_sec, "sector": sec_hr, "parent": u_personnel_gd}
        )
        u_admin_gd, _ = OrgUnit.objects.get_or_create(
            code="UNIT_ADMIN_GD", defaults={"name": "الإدارة العامة للشئون الإدارية", "unit_type": t_gd, "sector": sec_fin_hr, "parent": u_chair}
        )
        u_housing_sec, _ = OrgUnit.objects.get_or_create(
            code="UNIT_HOUSING", defaults={"name": "قسم الإسكان المصلحي", "unit_type": t_sec, "sector": sec_fin_hr, "parent": u_admin_gd}
        )

        u_fin_hr_sec, _ = OrgUnit.objects.get_or_create(
            code="UNIT_FIN_HR_SECTOR", defaults={"name": "رئاسة قطاع الشئون المالية والموارد البشرية", "unit_type": t_sector, "sector": sec_fin_hr, "parent": u_chair}
        )
        u_prod_sec, _ = OrgUnit.objects.get_or_create(
            code="UNIT_PROD_SECTOR", defaults={"name": "رئاسة قطاع الإنتاج", "unit_type": t_sector, "sector": sec_prod, "parent": u_chair}
        )

        # طبقة نواب رئيس مجلس الإدارة (أدوار هيكلية فقط): بلا مستخدمين ولا صلاحيات ولا إعادة ربط لوحدات قائمة.
        # أي ربط لقطاع بنائب أو رؤية/إحالة للنائب يحتاج قراراً صريحاً من المستخدم.
        t_vice, _ = OrgUnitType.objects.get_or_create(code="VICE_CHAIRMAN", defaults={"name": "نائب رئيس مجلس الإدارة", "level_order": 2})
        for _code, _name in (("UNIT_VICE_PROD", "نائب رئيس مجلس الإدارة لقطاعات الإنتاج"), ("UNIT_VICE_TECH", "نائب رئيس مجلس الإدارة للشئون الفنية"), ("UNIT_VICE_FIN_HR", "نائب رئيس مجلس الإدارة للشئون المالية والموارد البشرية")):
            OrgUnit.objects.get_or_create(code=_code, defaults={"name": _name, "unit_type": t_vice, "sector": sec_board, "parent": u_chair})

        # 5. أنواع المعاملات
        tx_transfer, _ = TransactionType.objects.get_or_create(
            code="TRANSFER",
            defaults={"name": "طلب نقل موظف", "sector": sec_hr, "requires_committee": True, "requires_decision": True, "requires_execution_proof": True},
        )
        tx_penalty, _ = TransactionType.objects.get_or_create(
            code="PENALTY",
            defaults={"name": "ملف جزاء موظف", "sector": sec_hr, "requires_committee": False, "requires_decision": True, "requires_execution_proof": True},
        )
        tx_allowance, _ = TransactionType.objects.get_or_create(
            code="ALLOWANCE",
            defaults={"name": "علاوة تشجيعية لمؤهل علمي", "sector": sec_hr, "requires_committee": True, "requires_decision": True, "requires_execution_proof": True},
        )
        tx_housing, _ = TransactionType.objects.get_or_create(
            code="HOUSING",
            defaults={"name": "تحسين شقة إسكان مصلحي", "sector": sec_fin_hr, "requires_committee": True, "requires_decision": False, "requires_execution_proof": False},
        )
        tx_urgent_statement, _ = TransactionType.objects.get_or_create(
            code="URGENT_STATEMENT",
            defaults={"name": "بيان عاجل وسري لجهات رقابية", "sector": sec_hr, "requires_committee": False, "requires_decision": False, "requires_execution_proof": False},
        )
        # أنواع معاملات وردت في شرح أحمد (17731215/17804617/17827052). لا لجنة ولا قرار ولا إثبات تنفيذ إلزامي؛ المسار يحدده التوجيه.
        for _code, _name in (
            ("COMPLAINT", "شكوى موظف"),
            ("GRIEVANCE", "تظلم (من جزاء أو تقرير تقييم أداء)"),
            ("RESIGNATION", "طلب استقالة"),
            ("EXTERNAL_REQUEST", "طلب بيان (من جهة خارجية أو جهة داخلية)"),
        ):
            TransactionType.objects.get_or_create(
                code=_code,
                defaults={"name": _name, "sector": sec_hr, "requires_committee": False, "requires_decision": False, "requires_execution_proof": False},
            )

        # 6. رموز الصلاحيات والأدوار
        perm_defs = [
            ("SUBJECT_CREATE", "إنشاء موضوع جديد", "الموضوعات"),
            ("SUBJECT_VIEW", "عرض الموضوعات", "الموضوعات"),
            ("SUBJECT_EDIT", "تعديل البيانات الوصفية للموضوع", "الموضوعات"),
            ("SUBJECT_SUSPEND", "تعليق الموضوع للاستيفاء", "الموضوعات"),
            ("SUBJECT_CLOSE", "إغلاق الموضوع رسمياً", "الموضوعات"),
            ("SUBJECT_EXCEPTIONAL_CLOSE", "إغلاق استثنائي للموضوع", "الموضوعات"),
            ("SUBJECT_REOPEN", "إعادة فتح موضوع مغلق", "الموضوعات"),
            ("DOCUMENT_CREATE", "تسجيل مستند وإصدار نسخ", "المستندات"),
            ("ATTACHMENT_DOWNLOAD", "تنزيل ومعاينة المرفقات", "المستندات"),
            ("REFERRAL_CREATE", "إحالة الموضوعات", "الإحالات"),
            ("TASK_CREATE", "تكليف وإنشاء مهام", "المهام"),
            ("MEMO_CREATE", "إعداد المذكرات", "المذكرات"),
            ("APPROVAL_GRANT", "اعتماد المذكرات والإجراءات", "الاعتمادات"),
            ("ANNOTATION_CREATE", "تسجيل تأشيرة إدارية", "التأشيرات"),
            ("COMMITTEE_MANAGE", "إدارة اللجان وتسجيل قراراتها", "اللجان"),
            ("DECISION_CREATE", "إعداد مشروع قرار إداري", "القرارات"),
            ("DECISION_APPROVE", "اعتماد وإصدار القرارات", "القرارات"),
            ("DECISION_DISTRIBUTE", "توزيع القرار ونشره وتكليف جهات التنفيذ", "القرارات"),
            ("ORG_VIEW", "عرض الهيكل التنظيمي", "التنظيم"),
            ("ORG_MANAGE", "إدارة الهيكل التنظيمي", "التنظيم"),
            ("USERS_MANAGE", "إدارة المستخدمين", "الإدارة"),
            ("USERS_MANAGE_SCOPED", "إدارة مستخدمي القطاع / الإدارة العامة", "الإدارة"),
            ("PERMISSIONS_MANAGE", "إدارة مصفوفة الصلاحيات", "الإدارة"),
            ("DELEGATION_MANAGE", "إدارة التفويضات والإنابة", "الإدارة"),
            ("AUDIT_VIEW", "الاطلاع على سجل التدقيق", "الأمان"),
            ("REPORTS_VIEW", "الاطلاع على التقارير والتصدير", "التقارير"),
            ("SYSTEM_SETTINGS", "إدارة البيانات المرجعية", "الإدارة"),
        ]
        perms_map = {}
        for code, name, cat in perm_defs:
            p, _ = PermissionCode.objects.get_or_create(code=code, defaults={"name": name, "category": cat})
            perms_map[code] = p

        def make_role(code, name, perm_codes, hier=False, conf=False, top=False, dl_top=False):
            r, _ = Role.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "allow_hierarchical_view": hier,
                    "can_view_confidential": conf,
                    "can_view_top_secret": top,
                    "can_download_secret_attachments": dl_top,
                },
            )
            for pc in perm_codes:
                RolePermission.objects.get_or_create(role=r, permission=perms_map[pc], defaults={"max_confidentiality_rank": 3 if top else (2 if conf else 1)})
            return r

        all_codes = list(perms_map.keys())
        r_admin = make_role("SYSTEM_ADMIN", "مسؤول النظام", all_codes, hier=False, conf=False, top=False, dl_top=False)
        r_chair = make_role("CHAIRMAN", "رئيس مجلس الإدارة", ["SUBJECT_CREATE", "SUBJECT_VIEW", "SUBJECT_EDIT", "SUBJECT_CLOSE", "SUBJECT_EXCEPTIONAL_CLOSE", "SUBJECT_REOPEN", "DOCUMENT_CREATE", "ATTACHMENT_DOWNLOAD", "REFERRAL_CREATE", "TASK_CREATE", "MEMO_CREATE", "APPROVAL_GRANT", "ANNOTATION_CREATE", "COMMITTEE_MANAGE", "DECISION_CREATE", "DECISION_APPROVE", "ORG_VIEW", "DELEGATION_MANAGE", "REPORTS_VIEW", "DECISION_DISTRIBUTE"], hier=True, conf=True, top=True, dl_top=True)
        r_sector_head = make_role("SECTOR_HEAD", "رئيس قطاع", ["SUBJECT_CREATE", "SUBJECT_VIEW", "SUBJECT_EDIT", "SUBJECT_SUSPEND", "SUBJECT_CLOSE", "SUBJECT_REOPEN", "DOCUMENT_CREATE", "ATTACHMENT_DOWNLOAD", "REFERRAL_CREATE", "TASK_CREATE", "MEMO_CREATE", "APPROVAL_GRANT", "ANNOTATION_CREATE", "COMMITTEE_MANAGE", "DECISION_CREATE", "DECISION_APPROVE", "ORG_VIEW", "DELEGATION_MANAGE", "REPORTS_VIEW", "DECISION_DISTRIBUTE"], hier=True, conf=True, top=True, dl_top=True)
        r_gm = make_role("GENERAL_MANAGER", "مدير عام", ["SUBJECT_CREATE", "SUBJECT_VIEW", "SUBJECT_EDIT", "SUBJECT_SUSPEND", "SUBJECT_CLOSE", "DOCUMENT_CREATE", "ATTACHMENT_DOWNLOAD", "REFERRAL_CREATE", "TASK_CREATE", "MEMO_CREATE", "ANNOTATION_CREATE", "DECISION_CREATE", "ORG_VIEW", "REPORTS_VIEW", "DECISION_DISTRIBUTE"], hier=True, conf=True, top=True, dl_top=False)
        r_sup = make_role("SUPERVISOR", "مشرف / رئيس قسم", ["SUBJECT_CREATE", "SUBJECT_VIEW", "SUBJECT_EDIT", "SUBJECT_SUSPEND", "DOCUMENT_CREATE", "ATTACHMENT_DOWNLOAD", "REFERRAL_CREATE", "TASK_CREATE", "MEMO_CREATE", "ORG_VIEW", "REPORTS_VIEW", "DECISION_DISTRIBUTE", "SUBJECT_CLOSE"], hier=True, conf=False, top=False, dl_top=False)
        r_sec = make_role("SECRETARIAT", "سكرتارية", ["SUBJECT_CREATE", "SUBJECT_VIEW", "DOCUMENT_CREATE", "ATTACHMENT_DOWNLOAD", "MEMO_CREATE", "ORG_VIEW", "DECISION_DISTRIBUTE"], hier=False, conf=False, top=False, dl_top=False)
        r_sector_admin = make_role(
            "SECTOR_DIR_ADMIN",
            "مسؤول قطاع / إدارة عامة (سكرتارية ومستخدمين)",
            ["SUBJECT_CREATE", "SUBJECT_VIEW", "DOCUMENT_CREATE", "ATTACHMENT_DOWNLOAD", "REFERRAL_CREATE", "MEMO_CREATE", "ORG_VIEW", "REPORTS_VIEW", "USERS_MANAGE_SCOPED"],
            hier=True,
            conf=True,
            top=False,
            dl_top=False,
        )
        r_emp = make_role("SPECIALIST", "موظف مختص تنفيذي", ["SUBJECT_VIEW", "DOCUMENT_CREATE", "ATTACHMENT_DOWNLOAD", "MEMO_CREATE", "DECISION_CREATE", "ORG_VIEW", "REPORTS_VIEW", "DECISION_DISTRIBUTE", "REFERRAL_CREATE", "SUBJECT_SUSPEND", "SUBJECT_CLOSE", "ANNOTATION_CREATE"], hier=False, conf=True, top=True, dl_top=True)

        # 7. إنشاء الموظفين والمستخدمين لكل مستوى
        def make_user(username, full_name, emp_no, job_title, unit, role, sector=None, is_admin=False, is_sec=False):
            emp, _ = Employee.objects.get_or_create(
                employee_number=emp_no,
                defaults={"full_name": full_name, "job_title": job_title, "current_unit": unit},
            )
            # لا نستخدم get_or_create هنا: سجل التنقلات التاريخي قد يحتوي صفوفاً متعددة
            # لنفس الموظف/الوحدة/المنصب (نقل ثم عودة)، وهذا سليم ولا يجب أن يكسر التهيئة.
            if not PositionAssignment.objects.filter(employee=emp).exists():
                PositionAssignment.objects.create(
                    employee=emp, org_unit=unit, position_title=job_title,
                    start_date=timezone.localdate(), is_current=True,
                )
            u, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": full_name,
                    "employee": emp,
                    "job_display_title": job_title,
                    "is_system_admin": is_admin,
                    "is_superuser": is_admin,
                    "is_staff": is_admin,
                    "is_secretariat": is_sec,
                },
            )
            if created:
                u.set_password("Pass@12345")
                u.save()
            UserRoleAssignment.objects.get_or_create(user=u, role=role, sector=sector, org_unit=unit)
            return u

        u_admin = make_user("admin", "م. أحمد مسؤول النظام", "EMP-001", "مسؤول النظام", u_chair, r_admin, is_admin=True)
        chairman = make_user("chairman", "أ.د. رئيس مجلس الإدارة", "EMP-002", "رئيس مجلس الإدارة", u_chair, r_chair)
        hr_head = make_user("hr_head", "أ. طارق رئيس قطاع الموارد البشرية", "EMP-003", "رئيس قطاع الموارد البشرية", u_hr_sec, r_sector_head, sector=sec_hr)
        hr_sec = make_user("hr_sec", "أ. سلمى سكرتارية قطاع الموارد البشرية", "EMP-004", "سكرتارية رئيس القطاع", u_hr_sec, r_sec, sector=sec_hr, is_sec=True)
        personnel_gm = make_user("personnel_gm", "أ. خالد مدير عام شئون الأفراد", "EMP-005", "مدير عام شئون الأفراد", u_personnel_gd, r_gm, sector=sec_hr)
        gm_sec = make_user("gm_sec", "أ. رانيا سكرتارية مدير عام شئون الأفراد", "EMP-011", "سكرتارية المدير العام", u_personnel_gd, r_sec, sector=sec_hr, is_sec=True)
        transfers_sup = make_user("transfers_sup", "أ. حسام مشرف قسم التنقلات", "EMP-006", "مشرف / رئيس قسم التنقلات", u_transfers, r_sup, sector=sec_hr)
        transfers_sec = make_user("transfers_sec", "أ. دعاء سكرتارية قسم التنقلات", "EMP-012", "سكرتارية قسم التنقلات", u_transfers, r_sec, sector=sec_hr, is_sec=True)
        penalties_sup = make_user("penalties_sup", "أ. مجدي مشرف قسم الجزاءات", "EMP-013", "مشرف / رئيس قسم الجزاءات", u_penalties, r_sup, sector=sec_hr)
        settlements_sup = make_user("settlements_sup", "أ. هالة مشرف قسم التسويات", "EMP-014", "مشرف / رئيس قسم التسويات", u_settlements, r_sup, sector=sec_hr)
        housing_sup = make_user("housing_sup", "أ. باسم مشرف قسم الإسكان", "EMP-015", "مشرف / رئيس قسم الإسكان المصلحي", u_housing_sec, r_sup, sector=sec_fin_hr)
        transfers_emp = make_user("transfers_emp", "أ. نادر مختص تنقلات", "EMP-007", "أخصائي شئون أفراد - تنقلات", u_transfers, r_emp, sector=sec_hr)
        penalties_emp = make_user("penalties_emp", "أ. شريف مختص جزاءات", "EMP-008", "أخصائي جزاءات", u_penalties, r_emp, sector=sec_hr)
        settlements_emp = make_user("settlements_emp", "أ. منى مختص تسويات", "EMP-009", "أخصائي تسويات", u_settlements, r_emp, sector=sec_hr)
        housing_emp = make_user("housing_emp", "أ. كريم مختص شئون إدارية", "EMP-010", "أخصائي إسكان إداري", u_housing_sec, r_emp, sector=sec_fin_hr)
        fin_hr_head = make_user("fin_hr_head", "أ. ماجد رئيس قطاع الشئون المالية والموارد البشرية", "EMP-017", "رئيس قطاع الشئون المالية والموارد البشرية", u_fin_hr_sec, r_sector_head, sector=sec_fin_hr)
        admin_gm = make_user("admin_gm", "أ. وائل مدير عام الشئون الإدارية", "EMP-018", "مدير عام الشئون الإدارية", u_admin_gd, r_gm, sector=sec_fin_hr)
        prod_head = make_user("prod_head", "أ. عادل رئيس قطاع الإنتاج", "EMP-019", "رئيس قطاعات الإنتاج", u_prod_sec, r_sector_head)
        hr_sector_admin = make_user("hr_sector_admin", "أ. منال مسؤول قطاع الموارد البشرية (سكرتارية)", "EMP-016", "مسؤول قطاع الموارد البشرية والسكرتارية", u_hr_sec, r_sector_admin, sector=sec_hr, is_sec=True)

        # سيناريو الإسكان: موضوع ينشأ في قطاع الإنتاج ويُوجَّه إلى قطاع المالية والموارد البشرية؛ يُمنح المعنيون
        # صلاحيتهم على موضوعات الإسكان فقط في قطاع الإنتاج (لا اتساع في باقي الأنواع أو القطاعات)
        for _u, _r in ((fin_hr_head, r_sector_head), (admin_gm, r_gm), (housing_sup, r_sup), (housing_emp, r_emp)):
            UserRoleAssignment.objects.get_or_create(user=_u, role=_r, sector=sec_prod, org_unit=None, transaction_type=tx_housing)

        # تفويضات السكرتارية (رئيس القطاع، المدير العام، ورئيس/مشرف القسم)
        Delegation.objects.get_or_create(
            delegator=hr_head,
            delegate=hr_sec,
            delegation_type=Delegation.DelegationType.SECRETARIAT,
            defaults={
                "scope_unit": u_hr_sec,
                "allowed_actions": ["SUBJECT_CREATE", "SUBJECT_VIEW", "REFERRAL_CREATE", "MEMO_CREATE", "DOCUMENT_CREATE"],
                "allow_confidential": True,
                "valid_from": timezone.now() - timedelta(days=1),
                "valid_to": timezone.now() + timedelta(days=90),
            },
        )
        Delegation.objects.get_or_create(
            delegator=personnel_gm,
            delegate=gm_sec,
            delegation_type=Delegation.DelegationType.SECRETARIAT,
            defaults={
                "scope_unit": u_personnel_gd,
                "allowed_actions": ["SUBJECT_CREATE", "SUBJECT_VIEW", "REFERRAL_CREATE", "DOCUMENT_CREATE"],
                "allow_confidential": True,
                "valid_from": timezone.now() - timedelta(days=1),
                "valid_to": timezone.now() + timedelta(days=90),
            },
        )
        Delegation.objects.get_or_create(
            delegator=transfers_sup,
            delegate=transfers_sec,
            delegation_type=Delegation.DelegationType.SECRETARIAT,
            defaults={
                "scope_unit": u_transfers,
                "allowed_actions": ["SUBJECT_VIEW", "REFERRAL_CREATE", "DOCUMENT_CREATE"],
                "allow_confidential": False,
                "valid_from": timezone.now() - timedelta(days=1),
                "valid_to": timezone.now() + timedelta(days=90),
            },
        )
        Delegation.objects.get_or_create(
            delegator=hr_head,
            delegate=hr_sector_admin,
            delegation_type=Delegation.DelegationType.SECRETARIAT,
            defaults={
                "scope_unit": u_hr_sec,
                "allowed_actions": ["SUBJECT_CREATE", "SUBJECT_VIEW", "REFERRAL_CREATE", "MEMO_CREATE", "DOCUMENT_CREATE"],
                "allow_confidential": True,
                "valid_from": timezone.now() - timedelta(days=1),
                "valid_to": timezone.now() + timedelta(days=90),
            },
        )

        # 8. قوالب مسارات العمل الافتراضية بإصدار v1
        tpl_transfer, _ = WorkflowTemplate.objects.get_or_create(
            code="TPL_TRANSFER", defaults={"name": "المسار الافتراضي لطلب نقل موظف", "transaction_type": tx_transfer, "sector": sec_hr}
        )
        ver_transfer, _ = WorkflowTemplateVersion.objects.get_or_create(
            template=tpl_transfer, version_number=1, defaults={"effective_from": timezone.localdate(), "is_active": True}
        )
        for idx, (st_title, unit) in enumerate([
            ("مراجعة رئيس قطاع الموارد البشرية", u_hr_sec),
            ("مدير عام شئون الأفراد", u_personnel_gd),
            ("مشرف قسم التنقلات", u_transfers),
            ("الموظف المختص بالتنقلات", u_transfers),
        ], start=1):
            WorkflowStepDefinition.objects.get_or_create(
                template_version=ver_transfer, step_order=idx, defaults={"step_title": st_title, "suggested_unit": unit, "is_optional": True}
            )

        # 9. اللجان
        Committee.objects.get_or_create(code="COM_PERSONNEL", defaults={"name": "لجنة شئون العاملين", "sector": sec_hr, "chair": hr_head})
        Committee.objects.get_or_create(code="COM_TRAINING", defaults={"name": "لجنة التدريب", "sector": sec_hr, "chair": chairman})
        Committee.objects.get_or_create(code="COM_HOUSING", defaults={"name": "لجنة الإسكان الفرعية بالمحطة", "sector": sec_fin_hr, "chair": housing_emp})

        # 10. تهيئة السيناريوهات الخمسة إذا لم تكن منشأة مسبقاً
        if not SubjectService.create_subject.__module__ or True:
            from subjects.models import Subject
            if Subject.objects.count() == 0:
                today = timezone.localdate()
                # السيناريو 1: طلب نقل محمد محمود علي (متجاوز الاستحقاق بيومين ومعلق لتحليل مخدرات)
                s1 = SubjectService.create_subject(
                    title="طلب نقل الموظف محمد محمود علي من محطة سيدي كرير إلى أبو قير",
                    description="طلب نقل موظف بين محطتي كهرباء سيدي كرير وأبو قير.",
                    transaction_type=tx_transfer,
                    sector=sec_hr,
                    org_unit=u_transfers,
                    confidentiality=conf_normal,
                    priority=prio_normal,
                    created_by=hr_sec,
                    current_owner=transfers_emp,
                    applicant_name="محمد محمود علي",
                    external_source="رئاسة قطاع الإنتاج",
                    keywords="نقل، سيدي كرير، أبو قير",
                    due_date=today - timedelta(days=2),
                )
                from django.core.files.uploadedfile import SimpleUploadedFile

                def _demo_pdf(filename: str, label: str) -> SimpleUploadedFile:
                    body_bytes = (
                        f"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                        f"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
                        f"3 0 obj<</Type/Page/MediaBox[0 0 595 842]/Parent 2 0 R/Contents 4 0 R>>endobj\n"
                        f"4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 50 750 Td ({label}) Tj ET\nendstream\nendobj\n"
                        f"trailer<</Root 1 0 R>>\n%%EOF\n"
                    ).encode("utf-8")
                    return SimpleUploadedFile(filename, body_bytes, content_type="application/pdf")

                DocumentService.register_document(
                    title="طلب النقل الأصلي - محمد محمود علي",
                    doc_type=doc_request,
                    confidentiality=conf_normal,
                    created_by=hr_sec,
                    sender_entity="قطاع الإنتاج",
                    subject=s1,
                    uploaded_file=_demo_pdf("transfer_request_mohamed.pdf", "Transfer Request - SUB-00001"),
                )
                WorkflowEngineService.create_referral(
                    subject=s1,
                    referred_by=hr_head,
                    routing_mode=Referral.RoutingMode.DIRECT,
                    purpose=Referral.Purpose.FOR_EXECUTION,
                    notes="للدراسة وإعداد مذكرة العرض بعد استيفاء التحليل الطبي",
                    target_users=[transfers_emp],
                    due_date=today - timedelta(days=1),
                    enforce_hierarchy=False,
                )
                SubjectService.suspend_subject(
                    subject=s1,
                    user=transfers_emp,
                    reason_ref=SuspensionReason.objects.filter(code="MISSING_MEDICAL").first(),
                    reason_details="يشترط استيفاء شهادة تحليل مخدرات سلبية معتمدة قبل العرض على اللجنة.",
                    required_from="الموظف محمد محمود علي / الشئون الطبية",
                    required_item="شهادة تحليل مخدرات سلبية",
                    expected_follow_up_date=today - timedelta(days=1),
                )

                # السيناريو 2: جزاء موظف (متجاوز للاستحقاق بيوم واحد)
                s2 = SubjectService.create_subject(
                    title="تنفيذ جزاء إداري وفق ملف التحقيق القانوني رقم 412",
                    description="ملف تحقيق وارد من الشئون القانونية متضمناً تأشيرة رئيس مجلس الإدارة.",
                    transaction_type=tx_penalty,
                    sector=sec_hr,
                    org_unit=u_penalties,
                    confidentiality=conf_secret,
                    priority=prio_urgent,
                    created_by=hr_head,
                    current_owner=penalties_emp,
                    external_source="الإدارة العامة للشئون القانونية",
                    keywords="جزاء، تحقيق",
                    due_date=today - timedelta(days=1),
                )
                DocumentService.register_document(
                    title="ملف التحقيق والمذكرة القانونية 412",
                    doc_type=doc_invest,
                    confidentiality=conf_secret,
                    created_by=hr_head,
                    external_in_out_number="ق/2026/412",
                    subject=s2,
                    uploaded_file=_demo_pdf("legal_investigation_412.pdf", "Investigation File 412"),
                )

                # السيناريو 3: علاوة تشجيعية - يحيى أحمد
                s3 = SubjectService.create_subject(
                    title="طلب علاوة تشجيعية لمؤهل علمي (ماجستير علوم الإدارة) - يحيى أحمد",
                    description="مقدم من الزميل يحيى أحمد للحصول على علاوة تشجيعية عن درجة الماجستير.",
                    transaction_type=tx_allowance,
                    sector=sec_hr,
                    org_unit=u_settlements,
                    confidentiality=conf_normal,
                    priority=prio_normal,
                    created_by=hr_sec,
                    current_owner=settlements_emp,
                    applicant_name="يحيى أحمد",
                    keywords="علاوة تشجيعية، ماجستير، تسويات",
                    due_date=today + timedelta(days=3),
                )
                DocumentService.register_document(
                    title="أصل شهادة الماجستير وموافقة قطاع التدريب",
                    doc_type=doc_cert,
                    confidentiality=conf_normal,
                    created_by=hr_sec,
                    subject=s3,
                    uploaded_file=_demo_pdf("masters_certificate_yahya.pdf", "Masters Certificate"),
                )

                # السيناريو 4: تحسين شقة إسكان مصلحي - علي علي محمود
                s4 = SubjectService.create_subject(
                    title="طلب تحسين شقة إسكان مصلحي - علي علي محمود",
                    description="طلب مقدم إلى لجنة الإسكان الفرعية بالمحطة ووارد عبر رئيس قطاعات الإنتاج.",
                    transaction_type=tx_housing,
                    sector=sec_fin_hr,
                    org_unit=u_housing_sec,
                    confidentiality=conf_normal,
                    priority=prio_normal,
                    created_by=chairman,
                    current_owner=housing_emp,
                    applicant_name="علي علي محمود",
                    external_source="رئيس قطاعات الإنتاج",
                    keywords="إسكان مصلحي، تحسين شقة",
                    due_date=today + timedelta(days=4),
                )

                # السيناريو 5: بيان عاجل وسري للغاية (متأخر يوماً واحداً ومحجوب تنبيهه عن المدير العام)
                s5 = SubjectService.create_subject(
                    title="بيان عاجل وسري للغاية وارد من الجهاز المركزي للتعبئة العامة والإحصاء",
                    description="طلب استيفاء بيان إحصائي سري للغاية موجه من رئيس المجلس إلى رئيس قطاع الموارد البشرية ومنه مباشرة للمختص.",
                    transaction_type=tx_urgent_statement,
                    sector=sec_hr,
                    org_unit=u_transfers,
                    confidentiality=conf_top,
                    priority=prio_top_urgent,
                    created_by=chairman,
                    current_owner=hr_head,
                    external_source="الجهاز المركزي للتعبئة العامة والإحصاء",
                    keywords="سري للغاية، الجهاز المركزي",
                    due_date=today - timedelta(days=1),
                )
                DocumentService.register_document(
                    title="خطاب الجهاز المركزي السري للغاية",
                    doc_type=doc_official,
                    confidentiality=conf_top,
                    created_by=chairman,
                    external_in_out_number="ج.م.ت/2026/9901",
                    sender_entity="الجهاز المركزي للتعبئة العامة والإحصاء",
                    subject=s5,
                    uploaded_file=_demo_pdf("capmas_top_secret_statement.pdf", "CAPMAS Top Secret"),
                )
                WorkflowEngineService.create_referral(
                    subject=s5,
                    referred_by=chairman,
                    routing_mode=Referral.RoutingMode.DIRECT,
                    purpose=Referral.Purpose.FOR_EXECUTION,
                    notes="يُعرض على رئيس قطاع الموارد البشرية للتوجيه المباشر لموظف مختص مع حجب المستويات الوسيطة.",
                    target_users=[hr_head],
                    enforce_hierarchy=False,
                )
                WorkflowEngineService.create_referral(
                    subject=s5,
                    referred_by=hr_head,
                    routing_mode=Referral.RoutingMode.DIRECT,
                    purpose=Referral.Purpose.FOR_EXECUTION,
                    notes="إحالة مباشرة وسرية للغاية لإعداد البيان دون المرور بالإدارة العامة.",
                    target_users=[transfers_emp],
                    due_date=today - timedelta(days=1),
                    enforce_hierarchy=False,
                )

                from core.models import SystemSequence
                Memo.objects.create(
                    subject=s3,
                    memo_number=SystemSequence.next_number("MEMO", "MEM"),
                    memo_type=Memo.MemoType.COMMITTEE,
                    title="مذكرة عرض للعرض على لجنة التدريب بشأن ماجستير يحيى أحمد",
                    directed_to="رئيس مجلس الإدارة / لجنة التدريب",
                    body="بالإشارة إلى الطلب المقدم من السيد/ يحيى أحمد للحصول على العلاوة التشجيعية، وبعد استيفاء أصل الشهادة وموافقة قطاع التدريب، نرفع لسيادتكم للعرض على لجنة التدريب.",
                    author=settlements_emp,
                )

        # 11. ضمان وجود حساب Superuser (an / 123)
        su, _ = User.objects.get_or_create(
            username="an",
            defaults={
                "first_name": "م. أحمد (Superuser)",
                "job_display_title": "مسؤول النظام الرئيسي (Superuser)",
                "is_system_admin": True,
                "is_superuser": True,
                "is_staff": True,
                "is_active": True,
            },
        )
        su.first_name = "م. أحمد (Superuser)"
        su.job_display_title = "مسؤول النظام الرئيسي (Superuser)"
        su.is_system_admin = True
        su.is_superuser = True
        su.is_staff = True
        su.is_active = True
        su.set_password("123")
        su.save()

        # 12. تهيئة المحادثات الفورية الافتراضية وتنبيهات ذكية نموذجية
        from chat.models import ChatConversation, ChatMessage
        from notifications.models import Notification
        from notifications.services import NotificationService

        if ChatConversation.objects.count() == 0:
            grp = ChatConversation.objects.create(
                type=ChatConversation.ConversationType.GROUP,
                name="مجموعة تنسيق الموارد البشرية والإدارية",
                created_by=su,
            )
            grp.members.add(su, chairman, hr_head, personnel_gm, transfers_sup, transfers_emp)
            gm1 = ChatMessage.objects.create(
                conversation=grp,
                sender=hr_head,
                text="مرحباً بالزملاء، يرجى متابعة المذكرات المتأخرة واستيفاء تحليل المخدرات لملف النقل قبل جلسة اللجنة.",
            )
            gm1.read_by.add(hr_head)

            dm = ChatConversation.objects.create(
                type=ChatConversation.ConversationType.DIRECT,
                created_by=su,
            )
            dm.members.add(su, hr_head)
            dm1 = ChatMessage.objects.create(
                conversation=dm,
                sender=hr_head,
                text="م. أحمد، تم تفعيل القوائم المرجعية للمذكرات وأنظمة التنبيهات الذكية بالمستويات بنجاح.",
            )
            dm1.read_by.add(hr_head)

        if Notification.objects.filter(recipient=su).count() == 0:
            from subjects.models import Subject
            first_subj = Subject.objects.order_by("id").first()
            NotificationService.notify(
                recipient=su,
                subject=first_subj,
                category=Notification.Category.INCOMING_REFERRAL,
                priority="URGENT",
                target_level="L1",
                reason_for_level="تنبيه مستوى قيادي (L1): متابعة المعاملات المتأخرة والمذكرات المرفوعة.",
                title="متابعة المعاملات الواردة والمعلقة بالنظام",
                message="توجد موضوعات جارية ومذكرة عرض جاهزة للاطلاع والمراجعة ضمن صندوق الوارد.",
                link_url=f"/subjects/{first_subj.id}/" if first_subj else "/",
            )
            NotificationService.notify(
                recipient=su,
                subject=first_subj,
                category=Notification.Category.REPLY_MEMO,
                priority="NORMAL",
                target_level="L1",
                reason_for_level="إشعار ردود ومذكرات: مرفوعة من الإدارات المختصة.",
                title="مذكرة عرض جديدة على لجنة التدريب",
                message="تم إعداد مذكرة عرض بشأن العلاوة التشجيعية لمؤهل الماجستير للمراجعة.",
                link_url=f"/subjects/{first_subj.id}/" if first_subj else "/",
            )

        from core.models import SystemSequence
        SystemSequence.sync_all()
        self.stdout.write(self.style.SUCCESS("تمت تهيئة جميع البيانات المرجعية والسيناريوهات الخمسة وحساب an بنجاح!"))
