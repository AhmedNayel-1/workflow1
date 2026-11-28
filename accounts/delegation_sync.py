"""ربط السكرتارية تلقائياً برئيس وحدتها (تفويض كامل بصلاحيات المسؤول)."""
from datetime import timedelta

from django.utils import timezone

PRINCIPAL_ORDER = ("CHAIRMAN", "SECTOR_HEAD", "GENERAL_MANAGER", "SUPERVISOR")


def sync_secretariat_delegations(Delegation, UserRoleAssignment, user_ids=None, unit_ids=None):
    """لكل تعيين سكرتارية نشط في وحدة: ينشئ تفويضاً ساري المفعول من رئيس الوحدة إن لم يوجد."""
    qs = UserRoleAssignment.objects.filter(is_active=True, role__code="SECRETARIAT", org_unit__isnull=False).select_related("user", "org_unit")
    if user_ids is not None:
        qs = qs.filter(user_id__in=user_ids)
    if unit_ids is not None:
        qs = qs.filter(org_unit_id__in=unit_ids)
    now = timezone.now()
    made = 0
    for a in qs:
        if not a.user.is_active:
            continue
        principal = None
        for code in PRINCIPAL_ORDER:
            principal = (UserRoleAssignment.objects.filter(is_active=True, role__code=code, org_unit_id=a.org_unit_id, user__is_active=True)
                         .exclude(user_id=a.user_id).select_related("user").first())
            if principal:
                break
        if principal is None:
            continue
        exists = Delegation.objects.filter(
            delegator_id=principal.user_id, delegate_id=a.user_id, delegation_type="SECRETARIAT",
            is_active=True, revoked_at__isnull=True, valid_from__lte=now, valid_to__gte=now,
        ).exists()
        if exists:
            continue
        Delegation.objects.create(
            delegator_id=principal.user_id, delegate_id=a.user_id, delegation_type="SECRETARIAT",
            scope_unit_id=a.org_unit_id, allowed_actions=[], allow_confidential=True,
            valid_from=now - timedelta(days=1), valid_to=now + timedelta(days=3650),
        )
        made += 1
    return made
