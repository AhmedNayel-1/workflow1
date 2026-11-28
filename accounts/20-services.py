"""
محرك الصلاحيات متعدد الأبعاد (Multi-Dimensional Permission Engine).
يقيّم: المستخدم + الدور + الوحدة التنظيمية + القطاع + نوع المعاملة + درجة السرية + التفويض + استثناءات الموضوع.
قاعدة ذهبية: المنع الصريح بسبب السرية يتغلب دائماً على صلاحية الاطلاع الهرمي، مع عزل القطاعات والوحدات.
"""
from typing import Optional
from django.apps import apps
from django.db.models import Q, QuerySet
from django.utils import timezone
from organization.models import OrgUnit
from .models import Delegation, RolePermission, User, UserRoleAssignment
from .permissions_layer import CorrespondenceAccessPolicy


def _active_ids(ids):
    return set(User.objects.filter(id__in=ids, is_active=True).values_list("id", flat=True))


class PermissionService:
    # مستوى أعلى = سلطة إدارية أعلى. الدور غير المدرج لا يمكن لمسؤول النطاق إسناده.
    ROLE_ASSIGNMENT_LEVELS = {
        "SYSTEM_ADMIN": 1000, "CHAIRMAN": 900, "SECTOR_HEAD": 800,
        "GENERAL_MANAGER": 700, "SECTOR_DIR_ADMIN": 600, "SUPERVISOR": 500,
        "SPECIALIST": 400, "SECRETARIAT": 300,
    }

    @classmethod
    def can_assign_role(cls, actor: User, role_code: str, target_user: Optional[User] = None) -> bool:
        """مسؤول النطاق لا يسند دوراً أعلى أو مساوياً لمستواه ولا يعدّل أدوار حسابه الشخصي."""
        if not actor or not actor.is_authenticated or not actor.is_active:
            return False
        if actor.is_superuser or actor.is_system_admin:
            return True
        if not cls.can_manage_users(actor):
            return False
        if target_user is not None and target_user.id == actor.id:
            return False
        target_level = cls.ROLE_ASSIGNMENT_LEVELS.get(role_code)
        if target_level is None:
            return False
        actor_codes = cls.get_effective_role_codes(actor)
        actor_levels = [cls.ROLE_ASSIGNMENT_LEVELS[code] for code in actor_codes if code in cls.ROLE_ASSIGNMENT_LEVELS]
        return bool(actor_levels) and target_level < max(actor_levels)
    @staticmethod
    def is_manager(user: User) -> bool:
        return CorrespondenceAccessPolicy.is_manager(user)

    @staticmethod
    def is_org_wide_manager(user: User) -> bool:
        return CorrespondenceAccessPolicy.is_org_wide_manager(user)

    @staticmethod
    def get_user_scope_boundaries(user: User) -> dict:
        return CorrespondenceAccessPolicy.get_user_scope_boundaries(user)

    @staticmethod
    def describe_user_scope(user: User) -> dict:
        return CorrespondenceAccessPolicy.describe_user_scope(user)

    @classmethod
    def can_manage_users(cls, user: User) -> bool:
        if not user or not user.is_authenticated or not user.is_active:
            return False
        if user.is_superuser or user.is_system_admin:
            return True
        return cls.user_has_permission(user, "USERS_MANAGE_SCOPED")

    @classmethod
    def get_scoped_admin_boundaries(cls, user: User) -> dict:
        """تحديد حدود القطاع والوحدات التنظيمية التي يملك مسؤول القطاع / الإدارة العامة إدارتها."""
        if not user or not user.is_authenticated or not user.is_active:
            return {"is_full_admin": False, "sector_ids": set(), "unit_ids": set()}
        if user.is_superuser or user.is_system_admin:
            return {"is_full_admin": True, "sector_ids": set(), "unit_ids": set()}

        sector_ids: set[int] = set()
        unit_ids: set[int] = set()
        assignments = cls.get_active_assignments(user)
        for a in assignments:
            if a.org_unit is not None:
                desc = a.org_unit.get_descendant_ids()
                unit_ids.update(desc)
                sector_ids.add(a.org_unit.sector_id)
            elif a.sector_id is not None:
                sector_ids.add(a.sector_id)
                unit_ids.update(
                    OrgUnit.objects.filter(sector_id=a.sector_id, is_active=True).values_list("id", flat=True)
                )

        if user.current_unit is not None and not unit_ids:
            unit_ids.update(user.current_unit.get_descendant_ids())
            sector_ids.add(user.current_unit.sector_id)
        elif user.current_sector is not None and not sector_ids:
            sector_ids.add(user.current_sector.id)
            unit_ids.update(
                OrgUnit.objects.filter(sector_id=user.current_sector.id, is_active=True).values_list("id", flat=True)
            )
        return {"is_full_admin": False, "sector_ids": sector_ids, "unit_ids": unit_ids}

    @classmethod
    def can_manage_target_user(
        cls, actor: User, target_user: Optional[User] = None, target_sector_id=None, target_unit_id=None
    ) -> bool:
        """التحقق من صلاحية إدارة مستخدم أو وحدة داخل نطاق مسؤول القطاع / الإدارة العامة."""
        if not cls.can_manage_users(actor):
            return False
        if actor.is_superuser or actor.is_system_admin:
            return True

        bounds = cls.get_scoped_admin_boundaries(actor)
        if bounds["is_full_admin"]:
            return True

        if target_user is not None:
            if target_user.is_superuser or target_user.is_system_admin:
                return False
            t_unit = target_user.current_unit
            t_sector = target_user.current_sector
            if t_unit is not None:
                if t_unit.id not in bounds["unit_ids"]:
                    return False
            elif t_sector is not None:
                if t_sector.id not in bounds["sector_ids"]:
                    return False
            else:
                return False

        if target_unit_id:
            if int(target_unit_id) not in bounds["unit_ids"]:
                return False
        if target_sector_id:
            if int(target_sector_id) not in bounds["sector_ids"]:
                return False
        return True

    @staticmethod
    def get_active_assignments(user: User, sector=None, org_unit=None, transaction_type=None) -> QuerySet:
        if not user or not user.is_authenticated or not user.is_active:
            return UserRoleAssignment.objects.none()
        qs = UserRoleAssignment.objects.filter(user=user, is_active=True).select_related(
            "role", "sector", "org_unit", "transaction_type"
        )
        if sector is not None:
            qs = qs.filter(Q(sector__isnull=True) | Q(sector=sector))
        if transaction_type is not None:
            qs = qs.filter(Q(transaction_type__isnull=True) | Q(transaction_type=transaction_type))
        return qs

    @staticmethod
    def _assignment_matches_unit(assignment: UserRoleAssignment, org_unit) -> bool:
        if org_unit is None or assignment.org_unit_id is None:
            return True
        if assignment.role.code in {"SYSTEM_ADMIN", "CHAIRMAN"} and assignment.sector_id is None:
            return True
        if assignment.role.code in {"SECTOR_HEAD", "GENERAL_MANAGER", "SUPERVISOR"} or assignment.role.allow_hierarchical_view:
            return org_unit.id in assignment.org_unit.get_descendant_ids()
        return assignment.org_unit_id == org_unit.id

    @staticmethod
    def get_active_delegations_for_delegate(user: User) -> QuerySet:
        if not user or not user.is_authenticated or not user.is_active:
            return Delegation.objects.none()
        now = timezone.now()
        return Delegation.objects.filter(
            delegate=user,
            is_active=True,
            revoked_at__isnull=True,
            valid_from__lte=now,
            valid_to__gte=now,
        ).select_related("delegator", "scope_unit")

    @classmethod
    def get_acting_delegation(cls, user: User, action_code: str, subject=None) -> Optional[Delegation]:
        """التحقق مما إذا كان المستخدم يعمل بتفويض ساري عن مسؤول آخر لتنفيذ إجراء محدد."""
        for delegation in cls.get_active_delegations_for_delegate(user):
            if delegation.allows(action_code):
                if subject is not None:
                    if subject.confidentiality.overrides_hierarchy and not delegation.allow_confidential:
                        continue
                    if delegation.scope_unit and subject.org_unit_id:
                        allowed_ids = delegation.scope_unit.get_descendant_ids()
                        if subject.org_unit_id not in allowed_ids:
                            continue
                return delegation
        return None

    @classmethod
    def user_has_permission(
        cls,
        user: User,
        perm_code: str,
        sector=None,
        transaction_type=None,
        confidentiality_rank: int = 1,
        subject=None,
    ) -> bool:
        if not user or not user.is_authenticated or not user.is_active:
            return False
        if user.is_superuser or user.is_system_admin:
            return True

        effective_sector = sector or (subject.sector if subject is not None else None)
        effective_tx = transaction_type or (subject.transaction_type if subject is not None else None)
        assignments = list(
            cls.get_active_assignments(user, sector=effective_sector, transaction_type=effective_tx)
        )

        # تطبيق عزل الوحدة التنظيمية عند توفر موضوع (ما لم يكن المستخدم طرفاً مباشراً في نفس القطاع)
        if subject is not None and assignments:
            is_direct = CorrespondenceAccessPolicy._is_direct_subject_party(user, subject)
            if not is_direct:
                assignments = [a for a in assignments if cls._assignment_matches_unit(a, subject.org_unit)]

        role_ids = [a.role_id for a in assignments]
        if role_ids:
            has_perm = RolePermission.objects.filter(
                role_id__in=role_ids,
                permission__code=perm_code,
                max_confidentiality_rank__gte=confidentiality_rank,
            ).exists()
            if has_perm:
                return True

        # التحقق عبر التفويض / الإنابة
        delegation = cls.get_acting_delegation(user, perm_code, subject=subject)
        if delegation is not None:
            return cls.user_has_permission(
                delegation.delegator,
                perm_code,
                sector=effective_sector,
                transaction_type=effective_tx,
                confidentiality_rank=confidentiality_rank,
                subject=subject,
            )
        return False

    @classmethod
    def can_view_subject(cls, user: User, subject) -> bool:
        """تفويض فحص رؤية الموضوع إلى الطبقة المنطقية الموحدة CorrespondenceAccessPolicy."""
        return CorrespondenceAccessPolicy.can_view_subject(user, subject)

    @classmethod
    def filter_visible_subjects(cls, queryset: QuerySet, user: User) -> QuerySet:
        """تصفية الموضوعات وفق الطبقة المنطقية الموحدة مع عزل القطاعات والوحدات."""
        return CorrespondenceAccessPolicy.filter_visible_subjects(queryset, user)

    @classmethod
    def can_view_document(cls, user: User, doc) -> bool:
        """تفويض فحص رؤية المستند (المرتبط أو المستقل) إلى الطبقة المنطقية الموحدة."""
        return CorrespondenceAccessPolicy.can_view_document(user, doc)

    @classmethod
    def can_download_attachment(cls, user: User, attachment) -> bool:
        """صلاحية مستقلة لتنزيل أو طباعة المرفقات مع احترام السرية الفائقة وعزل القطاعات والوحدات."""
        if not user or not user.is_authenticated or not user.is_active:
            return False
        if user.is_superuser:
            return True

        SubjectDocumentLink = apps.get_model("documents", "SubjectDocumentLink")
        doc = attachment.document_version.document

        # 1. يجب أن يكون المستخدم مصرحاً له برؤية المستند نفسه (مرتبط بموضوع أو مستقل)
        if not cls.can_view_document(user, doc):
            return False

        if hasattr(doc, "_prefetched_objects_cache") and "subjectdocumentlink_set" in doc._prefetched_objects_cache:
            links = list(doc.subjectdocumentlink_set.all())
        elif hasattr(doc, "_prefetched_objects_cache") and "subjects" in doc._prefetched_objects_cache:
            links = [type("MockLink", (), {"subject": s})() for s in doc.subjects.all()]
        else:
            links = list(
                SubjectDocumentLink.objects.filter(document=doc).select_related(
                    "subject__confidentiality", "subject__sector", "subject__org_unit", "subject__transaction_type"
                )
            )
        visible_subjects = [link.subject for link in links if cls.can_view_subject(user, link.subject)]
        primary_subject = visible_subjects[0] if visible_subjects else None
        context_sector = (
            primary_subject.sector
            if primary_subject is not None
            else (doc.created_by.current_sector if doc.created_by else None)
        )

        # 2. التحقق من صلاحية ATTACHMENT_DOWNLOAD بمستوى السرية المطلوب
        has_dl_perm = False
        if visible_subjects:
            has_dl_perm = any(
                cls.user_has_permission(
                    user,
                    "ATTACHMENT_DOWNLOAD",
                    sector=s.sector,
                    confidentiality_rank=doc.confidentiality.rank,
                    subject=s,
                )
                for s in visible_subjects
            )
        else:
            has_dl_perm = cls.user_has_permission(
                user,
                "ATTACHMENT_DOWNLOAD",
                sector=context_sector,
                confidentiality_rank=doc.confidentiality.rank,
            )

        if not has_dl_perm:
            # التحقق من التفويض الساري لتنزيل مرفق سري
            delegation = cls.get_acting_delegation(user, "ATTACHMENT_DOWNLOAD", subject=primary_subject)
            if delegation is None or (doc.confidentiality.overrides_hierarchy and not delegation.allow_confidential):
                return False
            return cls.can_download_attachment(delegation.delegator, attachment)

        # 3. للمرفقات «سري للغاية»: يشترط ضابط تنزيل مرفقات السري للغاية على الدور أو تفويض سري صريح
        if doc.confidentiality.overrides_hierarchy:
            assignments = cls.get_active_assignments(user, sector=context_sector)
            if any(a.role.can_download_secret_attachments for a in assignments):
                return True
            if doc.created_by_id == user.id:
                return True
            delegation = cls.get_acting_delegation(user, "ATTACHMENT_DOWNLOAD", subject=primary_subject)
            if delegation and delegation.allow_confidential:
                delegator_assignments = cls.get_active_assignments(delegation.delegator, sector=context_sector)
                return any(a.role.can_download_secret_attachments for a in delegator_assignments)
            return False

        return True

    @classmethod
    def get_effective_role_codes(cls, user: User, sector=None) -> set[str]:
        """إرجاع أكواد الأدوار الفعلية للمستخدم."""
        if not user or not user.is_authenticated or not user.is_active:
            return set()
        if user.is_superuser or user.is_system_admin:
            return {"SYSTEM_ADMIN"}
        return {a.role.code for a in cls.get_active_assignments(user, sector=sector)}

    ENTRY_ROLE_CODES = {"CHAIRMAN", "SECTOR_HEAD", "GENERAL_MANAGER", "SUPERVISOR", "SECTOR_DIR_ADMIN", "SECRETARIAT"}

    @classmethod
    def can_register_subject(cls, user: User) -> bool:
        """قاعدة المستخدم: الرؤساء (قطاع/إدارة/قسم) وسكرتاريتهم فقط يسجّلون موضوعاً؛ الموظف المختص لا يسجّل."""
        if not user or not user.is_authenticated or not user.is_active:
            return False
        if user.is_superuser or user.is_system_admin:
            return True
        if not (cls.get_effective_role_codes(user) & cls.ENTRY_ROLE_CODES):
            return False
        return cls.user_has_permission(user, "SUBJECT_CREATE")

    @classmethod
    def can_act_on_subject(cls, user: User, subject) -> bool:
        """
        التحقق من أن المستخدم يملك العهدة التنفيذية الحالية للموضوع
        (المالك الحالي، أو مفوض سكرتارية يعمل نيابة عنه ضمن وحدته، أو مستلم خطوة إحالة نشطة).
        الاطلاع الهرمي وحده لا يعطي حق تعديل الموضوع أو إحالات رئيس القطاع.
        """
        if not user or not user.is_authenticated or not user.is_active:
            return False
        if user.is_superuser or user.is_system_admin:
            return True
        if subject.current_owner_id == user.id:
            return True

        # التحقق من السكرتارية المفوضة عن المالك الحالي (مع احترام scope_unit والسرية)
        for delegation in cls.get_active_delegations_for_delegate(user):
            if delegation.allows("REFERRAL_CREATE"):
                if subject.confidentiality.overrides_hierarchy and not delegation.allow_confidential:
                    continue
                if delegation.scope_unit and subject.org_unit_id:
                    if subject.org_unit_id not in delegation.scope_unit.get_descendant_ids():
                        continue
                if delegation.delegator_id == subject.current_owner_id:
                    return True

        # التحقق من وجود خطوة إحالة نشطة موجهة للمستخدم أو لوحدته (ليست للعلم فقط)
        ReferralRecipient = apps.get_model("workflow", "ReferralRecipient")
        active_qs = ReferralRecipient.objects.filter(
            referral__subject=subject,
            is_active_step=True,
        ).exclude(referral__purpose="FOR_INFO")

        if active_qs.filter(target_user=user).exists():
            return True
        if user.current_unit and active_qs.filter(target_unit=user.current_unit, target_user__isnull=True).exists():
            return True

        for delegation in cls.get_active_delegations_for_delegate(user):
            if delegation.allows("REFERRAL_CREATE"):
                if subject.confidentiality.overrides_hierarchy and not delegation.allow_confidential:
                    continue
                if delegation.scope_unit and subject.org_unit_id:
                    if subject.org_unit_id not in delegation.scope_unit.get_descendant_ids():
                        continue
                if active_qs.filter(target_user=delegation.delegator).exists():
                    return True
        return False

    @classmethod
    def can_distribute_decision(cls, user: User, decision) -> bool:
        """توزيع القرار: المعتمد، أو صاحب صلاحية التوزيع (مشرف القسم، سكرتارية القسم، الموظف المختص) وهو في عهدته."""
        subject = decision.subject
        rank = subject.confidentiality.rank
        if cls.user_has_permission(user, "DECISION_APPROVE", sector=subject.sector, confidentiality_rank=rank, subject=subject):
            return True
        return cls.can_act_on_subject(user, subject) and cls.user_has_permission(
            user, "DECISION_DISTRIBUTE", sector=subject.sector, confidentiality_rank=rank, subject=subject
        )

    @classmethod
    def get_incoming_routing_scope(cls, user: User, subject):
        """نطاق توجيه الوارد: للأسفل فقط (من هم تحت سلطة المستخدم الهرمية). يرجع (user_ids, unit_ids, own_unit)."""
        unit = getattr(user, "current_unit", None)
        if user.is_superuser or user.is_system_admin or not unit:
            if not (user.is_superuser or user.is_system_admin):
                return set(), set(), None
            own_ids = set(OrgUnit.objects.filter(is_active=True).values_list("id", flat=True))
            unit = None
        else:
            own_ids = unit.get_descendant_ids()
        allowed_users = set(cls._get_downward_referral_targets(user, subject).values_list("id", flat=True))
        allowed_units = set(cls.get_allowed_referral_units_raw(user, subject).values_list("id", flat=True))
        unit_ids = {i for i in own_ids if i in allowed_units and (unit is None or i != unit.id)}
        user_ids = set(
            User.objects.filter(is_active=True, employee__current_unit_id__in=own_ids, id__in=allowed_users)
            .exclude(id=user.id).values_list("id", flat=True)
        )
        return user_ids, unit_ids, unit

    @classmethod
    def get_allowed_referral_targets(cls, user: User, subject) -> QuerySet:
        if getattr(subject, "origin_type", "") and getattr(subject, "direction", "") != "OUT" and not (user.is_superuser or user.is_system_admin):
            ids, _u, _r = cls.get_incoming_routing_scope(user, subject)
            return User.objects.filter(id__in=ids).select_related("employee__current_unit")
        return cls.get_allowed_referral_targets_raw(user, subject)

    @classmethod
    def get_allowed_referral_units(cls, user: User, subject) -> QuerySet:
        if getattr(subject, "origin_type", "") and getattr(subject, "direction", "") != "OUT" and not (user.is_superuser or user.is_system_admin):
            _ids, uids, _r = cls.get_incoming_routing_scope(user, subject)
            return OrgUnit.objects.filter(id__in=uids, is_active=True).select_related("sector")
        return cls.get_allowed_referral_units_raw(user, subject)

    @classmethod
    def get_allowed_referral_targets_raw(cls, user: User, subject) -> QuerySet:
        """الهرمية للأسفل + إعادة العهدة للأعلى لمن سبق أن أحال الموضوع في السلسلة."""
        down = cls._get_downward_referral_targets(user, subject)
        if not user or not user.is_authenticated or not user.is_active:
            return down
        if user.is_superuser or user.is_system_admin:
            return down
        Referral = apps.get_model("workflow", "Referral")
        upstream_ids = set(
            Referral.objects.filter(subject=subject).exclude(referred_by=user).values_list("referred_by_id", flat=True)
        )
        if subject.created_by_id and subject.created_by_id != user.id:
            upstream_ids.add(subject.created_by_id)
        # إعادة العهدة للأعلى فقط لمن ليس تحته؛ المستلم الحالي أو من أحيل إليه يعيد لمن أحال إليه ولمن تقدمه في السلسلة
        my_chain_ids = set(
            apps.get_model("workflow", "ReferralRecipient").objects.filter(
                referral__subject=subject, target_user=user
            ).values_list("referral__referred_by_id", flat=True)
        )
        if not my_chain_ids:
            return down
        return User.objects.filter(
            Q(id__in=set(down.values_list("id", flat=True))) | Q(id__in=upstream_ids & _active_ids(upstream_ids)),
            is_active=True,
        ).exclude(id=user.id).select_related("employee__current_unit").distinct()

    @classmethod
    def _get_downward_referral_targets(cls, user: User, subject) -> QuerySet:
        """
        تحديد المستخدمين المسموح بتوجيه الإحالة إليهم وفق التسلسل الهرمي وعزل القطاعات والوحدات:
        - رئيس مجلس الإدارة -> رؤساء القطاعات والمديرون العامون (في قطاع الموضوع أو المعنيين)
        - رئيس القطاع (أو سكرتاريته) -> المدير العام التابع للقطاع (أو المختص بالقطاع في السري للغاية فقط)
        - المدير العام (أو سكرتاريته) -> رئيس / مشرف القسم الأدنى التابع لنفس الإدارة والقطاع فقط
        - رئيس / مشرف القسم (أو سكرتارية القسم) -> الموظف المختص التابع لنفس القسم والقطاع فقط
        """
        if not user or not user.is_authenticated or not user.is_active:
            return User.objects.none()
        if user.is_superuser or user.is_system_admin:
            return User.objects.filter(is_active=True).exclude(id=user.id).select_related("employee__current_unit")

        effective_user = user
        delegation = cls.get_acting_delegation(user, "REFERRAL_CREATE", subject=subject)
        roles = cls.get_effective_role_codes(user, sector=subject.sector)
        if delegation and ("SECRETARIAT" in roles or not roles):
            effective_user = delegation.delegator
            roles = cls.get_effective_role_codes(effective_user, sector=subject.sector)

        if not roles and effective_user.current_unit and effective_user.current_unit.sector_id:
            # قطاع آخر أُحيل إليه الموضوع (مثل المالية والموارد البشرية في الإسكان): صلاحيته داخل قطاعه
            roles = cls.get_effective_role_codes(effective_user, sector=effective_user.current_unit.sector)
            if "SECRETARIAT" in roles:
                roles = set()

        base_qs = User.objects.filter(is_active=True).exclude(id=effective_user.id).select_related("employee__current_unit")

        if "CHAIRMAN" in roles:
            if subject.confidentiality.overrides_hierarchy:
                return base_qs
            sector_leaders = base_qs.filter(
                role_assignments__is_active=True,
                role_assignments__role__code__in=["SECTOR_HEAD", "GENERAL_MANAGER"],
            ).filter(
                Q(employee__current_unit__sector=subject.sector) | Q(role_assignments__sector=subject.sector)
            ).distinct()
            if sector_leaders.exists():
                return sector_leaders
            return base_qs.filter(
                role_assignments__is_active=True,
                role_assignments__role__code__in=["SECTOR_HEAD", "GENERAL_MANAGER", "SUPERVISOR"],
                employee__current_unit__sector=subject.sector,
            ).distinct()

        if "SECTOR_HEAD" in roles:
            if subject.confidentiality.overrides_hierarchy:
                return base_qs.filter(employee__current_unit__sector=subject.sector).distinct()
            # رئيس القطاع يوجه للمدير العام، أو مباشرة للمشرف/الموظف المختص (تتطلع المستويات بينهما)،
            # أو لنظيره رئيس قطاع آخر (مثلاً من قطاعات الإنتاج إلى المالية والموارد البشرية)
            own_unit = effective_user.current_unit
            sectors = {subject.sector_id}
            if own_unit and own_unit.sector_id:
                sectors.add(own_unit.sector_id)  # رئيس قطاع آخر أُحيل إليه الموضوع يوجه داخل قطاعه
            return base_qs.filter(
                Q(
                    employee__current_unit__sector_id__in=sectors,
                    role_assignments__is_active=True,
                    role_assignments__role__code__in=["GENERAL_MANAGER", "SUPERVISOR", "SPECIALIST"],
                )
                | Q(
                    role_assignments__is_active=True,
                    role_assignments__role__code="SECTOR_HEAD",
                )
                # قرار أحمد (Telegram 17622179): رئيس القطاع أو رئيس القطاعات يرفع إلى رئيس المجلس
                # حتى لو لم يكن رئيس المجلس ضمن سلسلة الموضوع (غير السري للغاية فقط).
                | Q(
                    role_assignments__is_active=True,
                    role_assignments__role__code="CHAIRMAN",
                )
            ).distinct()

        _own_sectors = {subject.sector_id} | ({effective_user.current_unit.sector_id} if effective_user.current_unit and effective_user.current_unit.sector_id else set())
        if "GENERAL_MANAGER" in roles:
            unit = effective_user.current_unit
            descendant_ids = unit.get_descendant_ids() if unit else set()
            qs = base_qs.filter(
                employee__current_unit__sector_id__in=_own_sectors,
                role_assignments__is_active=True,
                role_assignments__role__code="SUPERVISOR",
            )
            if descendant_ids:
                qs = qs.filter(employee__current_unit_id__in=descendant_ids)
            # المدير العام يوجه للمشرف المختص أو مباشرة للموظف المختص داخل إدارته
            emp_qs = base_qs.filter(
                employee__current_unit__sector_id__in=_own_sectors,
                role_assignments__is_active=True,
                role_assignments__role__code="SPECIALIST",
            )
            if descendant_ids:
                emp_qs = emp_qs.filter(employee__current_unit_id__in=descendant_ids)
            ids = set(qs.values_list("id", flat=True)) | set(emp_qs.values_list("id", flat=True))
            return base_qs.filter(id__in=ids).distinct()

        if "SUPERVISOR" in roles:
            target_unit_id = effective_user.current_unit.id if effective_user.current_unit else subject.org_unit_id
            qs = base_qs.filter(
                employee__current_unit__sector_id__in=_own_sectors,
                role_assignments__is_active=True,
                role_assignments__role__code="SPECIALIST",
            )
            if target_unit_id:
                qs = qs.filter(employee__current_unit_id=target_unit_id)
            return qs.distinct()

        return User.objects.none()

    @classmethod
    def get_allowed_referral_units_raw(cls, user: User, subject) -> QuerySet:
        """
        تحديد الوحدات التنظيمية المسموح بالإحالة إليها مع فرض عزل القطاعات والتسلسل الهرمي:
        - رئيس المجلس: الوحدات النشطة ضمن قطاع الموضوع
        - رئيس القطاع: الوحدات النشطة ضمن قطاع الموضوع فقط
        - المدير العام: الأقسام والوحدات الأدنى التابعة لإدارته العامة ضمن قطاع الموضوع فقط
        - رئيس/مشرف القسم: قسمه الحالي فقط
        - الموظف المختص: لا يحيل لوحدات أخرى
        """
        if not user or not user.is_authenticated or not user.is_active:
            return OrgUnit.objects.none()
        if user.is_superuser or user.is_system_admin:
            return OrgUnit.objects.filter(is_active=True).select_related("sector")

        effective_user = user
        delegation = cls.get_acting_delegation(user, "REFERRAL_CREATE", subject=subject)
        roles = cls.get_effective_role_codes(user, sector=subject.sector)
        if delegation and ("SECRETARIAT" in roles or not roles):
            effective_user = delegation.delegator
            roles = cls.get_effective_role_codes(effective_user, sector=subject.sector)

        if "CHAIRMAN" in roles:
            return OrgUnit.objects.filter(is_active=True, sector=subject.sector).select_related("sector")

        if "SECTOR_HEAD" in roles:
            return OrgUnit.objects.filter(is_active=True, sector=subject.sector).select_related("sector")

        if "GENERAL_MANAGER" in roles:
            unit = effective_user.current_unit
            descendant_ids = unit.get_descendant_ids() if unit else set()
            qs = OrgUnit.objects.filter(is_active=True, sector=subject.sector).select_related("sector")
            if descendant_ids:
                child_ids = descendant_ids - {unit.id}
                if child_ids:
                    qs = qs.filter(id__in=child_ids)
                else:
                    qs = qs.filter(id__in=descendant_ids)
            return qs

        if "SUPERVISOR" in roles:
            unit = effective_user.current_unit
            if unit and unit.sector_id == subject.sector_id:
                return OrgUnit.objects.filter(id=unit.id, is_active=True).select_related("sector")
            return OrgUnit.objects.none()

        return OrgUnit.objects.none()
