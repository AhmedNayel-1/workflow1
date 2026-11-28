"""
الطبقة المنطقية الموحدة لبرمجة صلاحيات رؤية المراسلات والموضوعات والمستندات
(CorrespondenceAccessPolicy) مع تطبيق عزل القطاعات والوحدات التنظيمية.

القواعد الحاكمة:
1. مدير النظام الأعلى (Superuser / SYSTEM_ADMIN) ورئيس مجلس الإدارة (CHAIRMAN):
   نطاقهما على مستوى المنشأة بالكامل (مع بقاء «سري للغاية» محصوراً بالمصرح لهم/المباشرين عدا Superuser).
2. المديرون على مستوى القطاع / الإدارة العامة (SECTOR_HEAD / GENERAL_MANAGER):
   يرون جميع المراسلات والموضوعات داخل قطاعهم / إدارتهم العامة والوحدات التابعة لها،
   ويُعزلون عن القطاعات والوحدات الأخرى خارج نطاقهم، مع بقاء «سري للغاية» محصوراً بالمباشرين والمصرح لهم صراحة.
3. الموظف العادي / مشرف القسم / السكرتارية:
   لا يرى إلا المراسلات الموجهة إليه مباشرة (منشئ، مالك حالي، طرف إحالة، مكلف بمهمة، أو مفوض ضمن نطاق وحدته)
   أو المراسلات المخصصة لقسمه / وحدته التنظيمية (org_unit)، مع بقاء «سري للغاية» محصوراً بالمباشرين والمصرح لهم فقط.
4. الاستثناءات الصريحة على مستوى الموضوع (DENY / GRANT) تتغلب دائماً.
"""
from django.apps import apps
from django.db.models import Q, QuerySet
from django.utils import timezone


ORG_WIDE_MANAGER_ROLE_CODES = frozenset({"SYSTEM_ADMIN", "CHAIRMAN"})
SCOPED_MANAGER_ROLE_CODES = frozenset({"SECTOR_HEAD", "GENERAL_MANAGER", "SECTOR_DIR_ADMIN"})
MANAGER_ROLE_CODES = ORG_WIDE_MANAGER_ROLE_CODES | SCOPED_MANAGER_ROLE_CODES


class CorrespondenceAccessPolicy:
    @classmethod
    def get_active_assignments(cls, user):
        if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
            return []
        UserRoleAssignment = apps.get_model("accounts", "UserRoleAssignment")
        return list(
            UserRoleAssignment.objects.filter(user=user, is_active=True).select_related(
                "role", "sector", "org_unit", "transaction_type"
            )
        )

    @classmethod
    def get_active_role_codes(cls, user) -> set[str]:
        if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
            return set()
        if getattr(user, "is_superuser", False) or getattr(user, "is_system_admin", False):
            return {"SYSTEM_ADMIN"}
        return {a.role.code for a in cls.get_active_assignments(user)}

    @classmethod
    def is_org_wide_manager(cls, user) -> bool:
        """هل يمتلك المستخدم صلاحية قيادية على مستوى المنشأة بالكامل (Superuser / Admin / رئيس المجلس)؟"""
        if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
            return False
        if getattr(user, "is_superuser", False) or getattr(user, "is_system_admin", False):
            return True
        for a in cls.get_active_assignments(user):
            if a.role.code in ORG_WIDE_MANAGER_ROLE_CODES and a.sector_id is None:
                return True
        return False

    @classmethod
    def is_manager(cls, user) -> bool:
        """هل يندرج المستخدم ضمن الطبقة القيادية/الإدارية (يرى جميع مراسلات نطاقه)؟"""
        if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
            return False
        if getattr(user, "is_superuser", False) or getattr(user, "is_system_admin", False):
            return True
        return bool(cls.get_active_role_codes(user) & MANAGER_ROLE_CODES)

    @classmethod
    def get_user_scope_boundaries(cls, user) -> dict:
        """
        حساب حدود العزل للقطاعات والوحدات التنظيمية للمستخدم الحالي.
        """
        if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
            return {
                "is_org_wide": False,
                "allowed_sector_ids": set(),
                "allowed_unit_ids": set(),
                "manager_unit_ids": set(),
            }

        if cls.is_org_wide_manager(user):
            return {
                "is_org_wide": True,
                "allowed_sector_ids": set(),
                "allowed_unit_ids": set(),
                "manager_unit_ids": set(),
            }

        assignments = cls.get_active_assignments(user)
        allowed_sector_ids: set[int] = set()
        allowed_unit_ids: set[int] = set()
        manager_unit_ids: set[int] = set()

        current_unit = getattr(user, "current_unit", None)
        if current_unit is not None:
            allowed_sector_ids.add(current_unit.sector_id)
            allowed_unit_ids.add(current_unit.id)

        for a in assignments:
            if a.sector_id is not None:
                allowed_sector_ids.add(a.sector_id)
            elif a.org_unit is not None:
                allowed_sector_ids.add(a.org_unit.sector_id)

            role_code = a.role.code
            if role_code == "SECTOR_HEAD":
                if a.org_unit is not None:
                    desc = a.org_unit.get_descendant_ids()
                    allowed_unit_ids.update(desc)
                    manager_unit_ids.update(desc)
                elif a.sector_id is not None:
                    OrgUnit = apps.get_model("organization", "OrgUnit")
                    sec_units = set(
                        OrgUnit.objects.filter(sector_id=a.sector_id, is_active=True).values_list("id", flat=True)
                    )
                    allowed_unit_ids.update(sec_units)
                    manager_unit_ids.update(sec_units)
            elif role_code in ("GENERAL_MANAGER", "SECTOR_DIR_ADMIN"):
                target_unit = a.org_unit or current_unit
                if target_unit is not None:
                    desc = target_unit.get_descendant_ids()
                    allowed_unit_ids.update(desc)
                    manager_unit_ids.update(desc)
                elif a.sector_id is not None:
                    OrgUnit = apps.get_model("organization", "OrgUnit")
                    sec_units = set(
                        OrgUnit.objects.filter(sector_id=a.sector_id, is_active=True).values_list("id", flat=True)
                    )
                    allowed_unit_ids.update(sec_units)
                    manager_unit_ids.update(sec_units)
            elif role_code == "SUPERVISOR":
                target_unit = a.org_unit or current_unit
                if target_unit is not None:
                    allowed_unit_ids.update(target_unit.get_descendant_ids())
            else:
                if a.org_unit_id is not None:
                    allowed_unit_ids.add(a.org_unit_id)

        return {
            "is_org_wide": False,
            "allowed_sector_ids": allowed_sector_ids,
            "allowed_unit_ids": allowed_unit_ids,
            "manager_unit_ids": manager_unit_ids,
        }

    @classmethod
    def get_active_delegations(cls, user):
        if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
            return []
        Delegation = apps.get_model("accounts", "Delegation")
        now = timezone.now()
        return list(
            Delegation.objects.filter(
                delegate=user,
                is_active=True,
                revoked_at__isnull=True,
                valid_from__lte=now,
                valid_to__gte=now,
            ).select_related("delegator", "scope_unit")
        )

    @classmethod
    def describe_user_scope(cls, user) -> dict:
        """وصف مقروء لطبقة الصلاحية وعزل القطاعات والوحدات للعرض في الواجهة والجداول."""
        if not user or not getattr(user, "is_authenticated", False):
            return {"tier": "guest", "label": "غير مسجل", "detail": "يلزم تسجيل الدخول"}

        unit = getattr(user, "current_unit", None)
        sector = getattr(user, "current_sector", None)
        unit_name = unit.name if unit else "جميع الوحدات"
        sector_name = sector.name if sector else "جميع القطاعات"

        if getattr(user, "is_superuser", False):
            return {
                "tier": "superuser",
                "is_manager": True,
                "label": "مدير النظام الأعلى — يرى جميع المراسلات عبر كل القطاعات بلا استثناء",
                "short_label": "يرى جميع المراسلات (Superuser)",
                "unit_name": unit_name,
                "sector_name": sector_name,
            }
        if cls.is_org_wide_manager(user):
            return {
                "tier": "manager",
                "is_manager": True,
                "label": "قيادة عليا — يرى جميع المراسلات عبر القطاعات (عدا السري للغاية غير الموجه له)",
                "short_label": "مدير أعلى: جميع القطاعات",
                "unit_name": unit_name,
                "sector_name": sector_name,
            }
        if cls.is_manager(user):
            role_codes = cls.get_active_role_codes(user)
            if "SECTOR_HEAD" in role_codes:
                return {
                    "tier": "manager",
                    "is_manager": True,
                    "label": f"رئيس قطاع ({sector_name}) — يرى جميع مراسلات قطاعه فقط مع عزل القطاعات الأخرى",
                    "short_label": f"مدير قطاع ({sector_name}) فقط",
                    "unit_name": unit_name,
                    "sector_name": sector_name,
                }
            if "SECTOR_DIR_ADMIN" in role_codes:
                return {
                    "tier": "manager",
                    "is_manager": True,
                    "label": f"مسؤول قطاع / إدارة عامة ({unit_name}) — سكرتارية وإدارة مستخدمي النطاق فقط (غير Superuser)",
                    "short_label": f"مسؤول نطاق ({unit_name})",
                    "unit_name": unit_name,
                    "sector_name": sector_name,
                }
            return {
                "tier": "manager",
                "is_manager": True,
                "label": f"مدير عام ({unit_name}) — يرى جميع مراسلات وحدته وأقسامها فقط (معزول عن القطاعات والوحدات الأخرى)",
                "short_label": f"مدير عام: نطاق ({unit_name})",
                "unit_name": unit_name,
                "sector_name": sector_name,
            }
        return {
            "tier": "employee",
            "is_manager": False,
            "label": f"موظف / قسم ({unit_name}) — يرى المراسلات الموجهة له أو لقسمه فقط",
            "short_label": f"موجه له أو لقسم ({unit_name}) فقط",
            "unit_name": unit_name,
            "sector_name": sector_name,
        }

    @classmethod
    def _is_direct_subject_party(cls, user, subject) -> bool:
        """هل المستخدم طرف مباشر في الموضوع (منشئ، مالك حالي، طرف إحالة، أو مكلف بمهمة)؟"""
        if subject.created_by_id == user.id or subject.current_owner_id == user.id:
            return True

        ReferralRecipient = apps.get_model("workflow", "ReferralRecipient")
        if ReferralRecipient.objects.filter(
            Q(referral__subject=subject)
            & (Q(target_user=user) | Q(received_by=user) | Q(referral__referred_by=user))
        ).exists():
            return True

        Task = apps.get_model("workflow", "Task")
        if Task.objects.filter(
            Q(subject=subject) & (Q(assigned_to=user) | Q(assigned_by=user))
        ).exists():
            return True

        return False

    CHAIN_ROLE_CODES = frozenset({"SECTOR_HEAD", "GENERAL_MANAGER", "SUPERVISOR"})
    LEADERSHIP_ROLE_CODES = frozenset(
        {"SECTOR_HEAD", "GENERAL_MANAGER", "SUPERVISOR", "SECTOR_DIR_ADMIN", "CHAIRMAN", "SYSTEM_ADMIN"}
    )

    @classmethod
    def get_chain_unit_ids(cls, user) -> set[int]:
        """
        الوحدات التي يقع موظفوها ضمن التسلسل الإداري للمستخدم: رئيس القطاع، المدير العام، مشرف القسم.
        قاعدة التسلسل: لا يعمل موظف في موضوع دون علم تسلسله الإداري ولو لم يُوجَّه إليه منهم مباشرة.
        """
        if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
            return set()
        OrgUnit = apps.get_model("organization", "OrgUnit")
        current_unit = getattr(user, "current_unit", None)
        ids: set[int] = set()
        for a in cls.get_active_assignments(user):
            code = a.role.code
            if code not in cls.CHAIN_ROLE_CODES:
                continue
            if code == "SECTOR_HEAD" and a.org_unit is None and a.sector_id is not None:
                ids.update(OrgUnit.objects.filter(sector_id=a.sector_id, is_active=True).values_list("id", flat=True))
                continue
            target = a.org_unit or current_unit
            if target is not None:
                ids.update(target.get_descendant_ids())
            elif a.sector_id is not None and code != "SUPERVISOR":
                ids.update(OrgUnit.objects.filter(sector_id=a.sector_id, is_active=True).values_list("id", flat=True))
        return ids

    @classmethod
    def get_chain_employee_ids(cls, user) -> set[int]:
        """معرّفات الموظفين (غير القياديين) في الوحدات الواقعة ضمن تسلسل المستخدم، دون المستخدم نفسه."""
        unit_ids = cls.get_chain_unit_ids(user)
        if not unit_ids:
            return set()
        User = apps.get_model("accounts", "User")
        UserRoleAssignment = apps.get_model("accounts", "UserRoleAssignment")
        leaders = set(
            UserRoleAssignment.objects.filter(is_active=True, role__code__in=cls.LEADERSHIP_ROLE_CODES)
            .values_list("user_id", flat=True)
        )
        qs = User.objects.filter(is_active=True, employee__current_unit_id__in=unit_ids).exclude(id=user.id)
        return {uid for uid in qs.values_list("id", flat=True) if uid not in leaders and uid}

    @classmethod
    def get_gm_chain_employee_ids(cls, user) -> set[int]:
        """موظفو الوحدات التابعة للمدير العام فقط (للسري للغاية): لا يشمل المشرف ولا سكرتارية المدير العام."""
        if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
            return set()
        current_unit = getattr(user, "current_unit", None)
        unit_ids: set[int] = set()
        for a in cls.get_active_assignments(user):
            if a.role.code != "GENERAL_MANAGER":
                continue
            target = a.org_unit or current_unit
            if target is not None:
                unit_ids.update(target.get_descendant_ids())
        if not unit_ids:
            return set()
        User = apps.get_model("accounts", "User")
        UserRoleAssignment = apps.get_model("accounts", "UserRoleAssignment")
        leaders = set(
            UserRoleAssignment.objects.filter(is_active=True, role__code__in=cls.LEADERSHIP_ROLE_CODES)
            .values_list("user_id", flat=True)
        )
        qs = User.objects.filter(is_active=True, employee__current_unit_id__in=unit_ids).exclude(id=user.id)
        return {uid for uid in qs.values_list("id", flat=True) if uid not in leaders}

    @classmethod
    def get_delegated_chain_employee_ids(cls, delegation) -> set[int]:
        """موظفو تسلسل المفوِّض داخل نطاق وحدة التفويض (إن وُجد). السكرتارية ترى ما يُوجَّه لموظفي المدير الذي تنوب عنه."""
        ids = cls.get_chain_employee_ids(delegation.delegator)
        if not ids or delegation.scope_unit_id is None:
            return ids
        User = apps.get_model("accounts", "User")
        scope = delegation.scope_unit.get_descendant_ids()
        return set(
            User.objects.filter(id__in=ids, employee__current_unit_id__in=scope).values_list("id", flat=True)
        )

    @classmethod
    def _chain_directed_q(cls, employee_ids) -> Q:
        return (
            Q(current_owner_id__in=employee_ids)
            | (Q(referrals__recipients__target_user_id__in=employee_ids) & ~Q(referrals__recipients__status="WITHDRAWN"))
            | Q(tasks__assigned_to_id__in=employee_ids)
        )

    @classmethod
    def _is_directed_to_chain_employee(cls, user, subject) -> bool:
        return cls._subject_directed_to(subject, cls.get_chain_employee_ids(user))

    @classmethod
    def _subject_directed_to(cls, subject, employee_ids) -> bool:
        if not employee_ids:
            return False
        if subject.current_owner_id in employee_ids:
            return True
        ReferralRecipient = apps.get_model("workflow", "ReferralRecipient")
        Task = apps.get_model("workflow", "Task")
        if ReferralRecipient.objects.filter(
            referral__subject=subject, target_user_id__in=employee_ids
        ).exclude(status="WITHDRAWN").exists():
            return True
        return Task.objects.filter(subject=subject, assigned_to_id__in=employee_ids).exists()

    @classmethod
    def _closed_dept_unit_ids(cls, subject):
        """وحدات من تعامل مع الموضوع (المنشئ والمالك والمحال إليهم والمحيلون) + وحدة الموضوع."""
        ids = {subject.org_unit_id}
        ReferralRecipient = apps.get_model("workflow", "ReferralRecipient")
        uids = {subject.created_by_id, subject.current_owner_id}
        for tu, rb in ReferralRecipient.objects.filter(referral__subject=subject).values_list("target_user_id", "referral__referred_by_id"):
            uids.add(tu); uids.add(rb)
        User = apps.get_model("accounts", "User")
        for u in User.objects.filter(id__in={x for x in uids if x}).select_related("employee"):
            if u.employee_id and u.employee.current_unit_id:
                ids.add(u.employee.current_unit_id)
        ids.discard(None)
        return ids

    @classmethod
    def _is_closed_dept_viewer(cls, user, subject) -> bool:
        """موضوع مغلق غير سري للغاية: كل موظفي قسم من تعامل معه يطّلعون عليه (داخل قطاعهم)."""
        if subject.status != "CLOSED" or subject.confidentiality.overrides_hierarchy:
            return False
        unit = getattr(user, "current_unit", None)
        if unit is None:
            return False
        if subject.sector_id not in cls.get_user_scope_boundaries(user)["allowed_sector_ids"]:
            return False
        return unit.id in cls._closed_dept_unit_ids(subject)

    @classmethod
    def can_view_subject(cls, user, subject, _visited_delegators=None) -> bool:
        if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
            return False
        if getattr(user, "is_superuser", False):
            return True

        SubjectAccessGrant = apps.get_model("subjects", "SubjectAccessGrant")
        ReferralRecipient = apps.get_model("workflow", "ReferralRecipient")

        # 1. المنع الصريح يتقدم على كل قاعدة
        if SubjectAccessGrant.objects.filter(subject=subject, user=user, access_type="DENY").exists():
            return False

        # 2. المنح الصريح للموضوع
        if SubjectAccessGrant.objects.filter(subject=subject, user=user, access_type="GRANT").exists():
            return True

        # 3. المراسلة موجهة مباشرة للمستخدم
        if cls._is_direct_subject_party(user, subject):
            return True

        # 4. التحقق من التفويض (سكرتارية عن مسؤول) مع احترام عزل scope_unit والسرية الفائقة
        visited = set(_visited_delegators or set())
        visited.add(user.id)
        for delegation in cls.get_active_delegations(user):
            if delegation.delegator_id in visited:
                continue
            if not delegation.allows("SUBJECT_VIEW"):
                continue
            if subject.confidentiality.overrides_hierarchy and not delegation.allow_confidential:
                continue
            if not subject.confidentiality.overrides_hierarchy:
                chain_ids = cls.get_delegated_chain_employee_ids(delegation)
                if chain_ids and cls._subject_directed_to(subject, chain_ids):
                    return True
            if delegation.scope_unit_id is not None:
                if subject.org_unit_id not in delegation.scope_unit.get_descendant_ids():
                    continue
            if cls.can_view_subject(delegation.delegator, subject, _visited_delegators=visited):
                return True

        # 5. السرية الفائقة (سري للغاية): محصورة بالمباشرين والمصرح لهم صراحة فقط
        if subject.confidentiality.overrides_hierarchy:
            # المدير العام الأعلى تنظيميًا من الموظف المنفذ يرى «سري للغاية» الموجّه لموظف في إدارته (دون المشرف ولا السكرتارية)
            # عبر التفويض (سكرتارية المدير العام) لا تُورَّث هذه القاعدة؛ تبقى لشخص المدير العام فقط
            if _visited_delegators:
                return False
            return cls._subject_directed_to(subject, cls.get_gm_chain_employee_ids(user))

        # 5ب. التسلسل الإداري يعلم بما يُوجَّه لموظفيه (رئيس القطاع / المدير العام / مشرف القسم)
        if cls._is_directed_to_chain_employee(user, subject):
            return True
        # 5ج. بعد الإغلاق: كل موظفي القسم الذي تعامل مع الموضوع (غير السري للغاية)
        if cls._is_closed_dept_viewer(user, subject):
            return True

        # 6. عزل القطاعات والوحدات التنظيمية في الطبقة المركزية
        boundaries = cls.get_user_scope_boundaries(user)
        if boundaries["is_org_wide"]:
            return True

        # طبقة المدير على مستوى القطاع / الإدارة العامة (ضمن قطاعه ووحداته التابعة فقط)
        if cls.is_manager(user):
            sector_ok = (
                not boundaries["allowed_sector_ids"]
                or subject.sector_id in boundaries["allowed_sector_ids"]
            )
            if not sector_ok:
                return False
            role_codes = cls.get_active_role_codes(user)
            if "SECTOR_HEAD" in role_codes:
                return True
            # المدير العام محصور بالوحدات التابعة لإدارته العامة داخل قطاعه
            if boundaries["manager_unit_ids"]:
                return subject.org_unit_id in boundaries["manager_unit_ids"]
            return True

        # 7. طبقة الموظف العادي / مشرف القسم: يرى المراسلات المخصصة لقسمه داخل قطاعه أو المحالة لوحدته
        unit = getattr(user, "current_unit", None)
        # الرؤية تتبع التوجيه: الموظف المختص لا يرى بحكم وحدته فقط، بل بإحالة باسمه أو بتكليفه؛ رئيس الوحدة وسكرتاريتها يرون ما يخص وحدتهم.
        if not (cls.get_active_role_codes(user) & {"SUPERVISOR", "GENERAL_MANAGER", "SECTOR_DIR_ADMIN", "SECRETARIAT"}):
            unit = None
        if unit is not None and subject.sector_id in boundaries["allowed_sector_ids"]:
            if subject.org_unit_id in boundaries["allowed_unit_ids"]:
                return True
            if ReferralRecipient.objects.filter(
                referral__subject=subject,
                target_unit=unit,
                target_user__isnull=True,
            ).exists():
                return True

        return False

    @classmethod
    def get_visible_subjects_q(cls, user: object) -> Q:
        """
        بناء استعلام Q() على مستوى قاعدة البيانات لصلاحيات رؤية الموضوعات
        (قطاع/وحدة/سرية/أطراف مباشرة/منح واستثناءات) دون تحميل كل السجلات في الذاكرة.
        """
        if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
            return Q(pk__in=[])
        if getattr(user, "is_superuser", False):
            return Q()

        SubjectAccessGrant = apps.get_model("subjects", "SubjectAccessGrant")

        # 1. المعرفات الممنوعة صراحة (DENY)
        denied_subject_ids = set(
            SubjectAccessGrant.objects.filter(user=user, access_type="DENY").values_list("subject_id", flat=True)
        )
        deny_filter = ~Q(id__in=denied_subject_ids) if denied_subject_ids else Q()

        # 2. المنح الصريح (GRANT)
        grant_subject_ids = set(
            SubjectAccessGrant.objects.filter(user=user, access_type="GRANT").values_list("subject_id", flat=True)
        )
        grant_q = Q(id__in=grant_subject_ids) if grant_subject_ids else Q(pk__in=[])

        # 3. الأطراف المباشرة في الموضوع
        direct_q = (
            Q(created_by=user)
            | Q(current_owner=user)
            | Q(referrals__recipients__target_user=user)
            | Q(referrals__recipients__received_by=user)
            | Q(referrals__referred_by=user)
            | Q(tasks__assigned_to=user)
            | Q(tasks__assigned_by=user)
        )

        # 4. التفويضات الفعالة للمستخدم (سكرتارية / إنابة معتمدة)
        delegation_q = Q(pk__in=[])
        for delegation in cls.get_active_delegations(user):
            if not delegation.allows("SUBJECT_VIEW"):
                continue
            del_user = delegation.delegator
            d_direct = (
                Q(created_by=del_user)
                | Q(current_owner=del_user)
                | Q(referrals__recipients__target_user=del_user)
                | Q(referrals__recipients__received_by=del_user)
                | Q(referrals__referred_by=del_user)
                | Q(tasks__assigned_to=del_user)
                | Q(tasks__assigned_by=del_user)
            )
            if not delegation.allow_confidential:
                d_direct &= Q(confidentiality__overrides_hierarchy=False)
            if delegation.scope_unit_id is not None:
                d_direct &= Q(org_unit_id__in=delegation.scope_unit.get_descendant_ids())
            delegation_q |= d_direct

            # نطاق المدير المفوض إذا كان المفوض مديراً
            if cls.is_manager(del_user):
                d_bounds = cls.get_user_scope_boundaries(del_user)
                d_scope = Q(confidentiality__overrides_hierarchy=False)
                if d_bounds["allowed_sector_ids"]:
                    d_scope &= Q(sector_id__in=d_bounds["allowed_sector_ids"])
                if d_bounds["manager_unit_ids"]:
                    d_scope &= Q(org_unit_id__in=d_bounds["manager_unit_ids"])
                if delegation.scope_unit_id is not None:
                    d_scope &= Q(org_unit_id__in=delegation.scope_unit.get_descendant_ids())
                delegation_q |= d_scope

        # 5. الصلاحية الهرمية / النطاق المؤسسي (تُحجب تلقائياً عن السري للغاية)
        scope_q = Q(pk__in=[])
        boundaries = cls.get_user_scope_boundaries(user)

        if boundaries["is_org_wide"]:
            scope_q = Q(confidentiality__overrides_hierarchy=False)
        elif cls.is_manager(user):
            role_codes = cls.get_active_role_codes(user)
            sec_filter = Q(sector_id__in=boundaries["allowed_sector_ids"]) if boundaries["allowed_sector_ids"] else Q()
            if "SECTOR_HEAD" in role_codes:
                scope_q = Q(confidentiality__overrides_hierarchy=False) & sec_filter
            elif boundaries["manager_unit_ids"]:
                scope_q = (
                    Q(confidentiality__overrides_hierarchy=False)
                    & sec_filter
                    & Q(org_unit_id__in=boundaries["manager_unit_ids"])
                )
            else:
                scope_q = Q(confidentiality__overrides_hierarchy=False) & sec_filter
        else:
            # كادر تنفيذي / مشرف قسم: يرى موضوعات قسمه ووحدته المحالة
            unit = getattr(user, "current_unit", None)
            if not (cls.get_active_role_codes(user) & {"SUPERVISOR", "GENERAL_MANAGER", "SECTOR_DIR_ADMIN", "SECRETARIAT"}):
                unit = None
            if unit is not None:
                sec_filter = Q(sector_id__in=boundaries["allowed_sector_ids"]) if boundaries["allowed_sector_ids"] else Q()
                unit_filter = Q(org_unit_id__in=boundaries["allowed_unit_ids"]) if boundaries["allowed_unit_ids"] else Q(org_unit=unit)
                unit_ref_filter = Q(
                    referrals__recipients__target_unit=unit,
                    referrals__recipients__target_user__isnull=True,
                )
                scope_q = Q(confidentiality__overrides_hierarchy=False) & sec_filter & (unit_filter | unit_ref_filter)

        # 5ب. التسلسل الإداري: ما يُوجَّه لموظفين تحت رئيس القطاع / المدير العام / المشرف (غير السري للغاية)
        chain_q = Q(pk__in=[])
        chain_employee_ids = cls.get_chain_employee_ids(user)
        if chain_employee_ids:
            chain_q = Q(confidentiality__overrides_hierarchy=False) & cls._chain_directed_q(chain_employee_ids)

        for delegation in cls.get_active_delegations(user):
            if not delegation.allows("SUBJECT_VIEW"):
                continue
            d_ids = cls.get_delegated_chain_employee_ids(delegation)
            if d_ids:
                chain_q |= Q(confidentiality__overrides_hierarchy=False) & cls._chain_directed_q(d_ids)

        gm_ids = cls.get_gm_chain_employee_ids(user)
        if gm_ids:
            chain_q |= Q(confidentiality__overrides_hierarchy=True) & cls._chain_directed_q(gm_ids)

        closed_q = Q(pk__in=[])
        _u = getattr(user, "current_unit", None)
        if _u is not None and boundaries["allowed_sector_ids"]:
            _p = "employee__current_unit"
            closed_q = (
                Q(status="CLOSED", confidentiality__overrides_hierarchy=False, sector_id__in=boundaries["allowed_sector_ids"])
                & (Q(org_unit=_u)
                   | Q(created_by__employee__current_unit=_u)
                   | Q(current_owner__employee__current_unit=_u)
                   | Q(referrals__recipients__target_user__employee__current_unit=_u)
                   | Q(referrals__referred_by__employee__current_unit=_u))
            )

        positive_q = grant_q | direct_q | delegation_q | scope_q | chain_q | closed_q
        return positive_q & deny_filter

    @classmethod
    def filter_visible_subjects(cls, queryset: QuerySet, user: object) -> QuerySet:
        """تصفية الموضوعات على مستوى قاعدة البيانات باستخدام Q() مباشرة دون إرهاق الذاكرة."""
        if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
            return queryset.none()
        if getattr(user, "is_superuser", False):
            return queryset
        return queryset.filter(cls.get_visible_subjects_q(user)).distinct()

    @classmethod
    def can_view_document(cls, user, doc) -> bool:
        """
        التحقق المركزي من صلاحية الاطلاع على المستند مع تأمين المستندات السرية
        وعزل القطاعات والوحدات حتى للمستندات غير المرتبطة بموضوع.
        """
        if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
            return False
        if getattr(user, "is_superuser", False):
            return True

        SubjectDocumentLink = apps.get_model("documents", "SubjectDocumentLink")
        if hasattr(doc, "_prefetched_objects_cache") and "subjectdocumentlink_set" in doc._prefetched_objects_cache:
            links = list(doc.subjectdocumentlink_set.all())
        elif hasattr(doc, "_prefetched_objects_cache") and "subjects" in doc._prefetched_objects_cache:
            subjects_list = list(doc.subjects.all())
            if subjects_list:
                visible_subjects = [s for s in subjects_list if cls.can_view_subject(user, s)]
                if not visible_subjects:
                    return False
                if doc.confidentiality.overrides_hierarchy:
                    if doc.created_by_id == user.id:
                        return True
                    if any(cls._is_direct_subject_party(user, s) for s in visible_subjects):
                        return True
                    if any(a.role.can_view_top_secret for a in cls.get_active_assignments(user)):
                        return True
                    return False
                return True
            links = []
        else:
            links = list(
                SubjectDocumentLink.objects.filter(document=doc).select_related(
                    "subject__confidentiality", "subject__sector", "subject__org_unit"
                )
            )
        if links:
            visible_subjects = [link.subject for link in links if cls.can_view_subject(user, link.subject)]
            if not visible_subjects:
                return False
            if doc.confidentiality.overrides_hierarchy:
                # إذا كان المستند نفسه «سري للغاية» حتى لو ارتبط بموضوع عادي:
                # لا يراه إلا منشئ المستند أو طرف مباشر في الموضوع أو حامل صلاحية السري للغاية
                if doc.created_by_id == user.id:
                    return True
                if any(cls._is_direct_subject_party(user, s) for s in visible_subjects):
                    return True
                if any(a.role.can_view_top_secret for a in cls.get_active_assignments(user)):
                    return True
                return False
            return True

        # مستند غير مرتبط بموضوع (Standalone)
        if doc.created_by_id == user.id:
            return True
        if doc.confidentiality.overrides_hierarchy:
            return False

        boundaries = cls.get_user_scope_boundaries(user)
        if boundaries["is_org_wide"]:
            return True

        creator = getattr(doc, "created_by", None)
        creator_unit = getattr(creator, "current_unit", None) if creator else None
        creator_sector_id = creator_unit.sector_id if creator_unit else None

        if doc.confidentiality.rank >= 2:
            # المستندات السرية غير المرتبطة تتطلب صلاحية الاطلاع على السري مع عزل القطاع/الوحدة
            has_conf_flag = any(a.role.can_view_confidential for a in cls.get_active_assignments(user))
            if not has_conf_flag:
                return False

        if cls.is_manager(user):
            if creator_sector_id and creator_sector_id not in boundaries["allowed_sector_ids"]:
                return False
            role_codes = cls.get_active_role_codes(user)
            if "SECTOR_HEAD" in role_codes:
                return creator_sector_id in boundaries["allowed_sector_ids"]
            if boundaries["manager_unit_ids"] and creator_unit:
                return creator_unit.id in boundaries["manager_unit_ids"]
            return False

        # الموظف العادي يرى المستندات غير المرتبطة المنشأة داخل وحدته فقط
        user_unit = getattr(user, "current_unit", None)
        if user_unit and creator_unit and user_unit.id == creator_unit.id:
            return True
        return False
