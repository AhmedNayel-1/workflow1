"""الإغلاق من نافذة الإجراء، طلب الإغلاق، وإشعار السلسلة."""
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from subjects import action_access as AA
from subjects.models import StepSuspension, SubjectAction
from workflow.models import Referral, ReferralRecipient

LBL_REQ = "طلب إغلاق الموضوع"
LBL_CLOSE = "أغلق الموضوع"
RS = ReferralRecipient.RecipientStatus


def open_steps(subject):
    return ReferralRecipient.objects.filter(referral__subject=subject, is_active_step=True).exclude(
        referral__purpose=Referral.Purpose.FOR_INFO)


def my_steps(user, subject):
    ids = [u.id for u in AA.eff_users(user)]
    q = Q(target_user_id__in=ids)
    unit = getattr(user, "current_unit", None)
    if unit is not None:
        q |= Q(target_unit=unit, target_user__isnull=True)
    return open_steps(subject).filter(q)


def blockers(subject, user=None):
    """خطوة مفتوحة لغير المُغلِق أو تعليق مفتوح يمنعان الإغلاق (لا يُتجاوزان بالإغلاق الاستثنائي)."""
    errs = []
    steps = open_steps(subject)
    if user is not None:
        steps = steps.exclude(id__in=my_steps(user, subject).values_list("id", flat=True))
    n = steps.count()
    if n:
        errs.append(f"توجد {n} خطوة مفتوحة لدى آخرين؛ يجب أن تنتهي أو تُسحب قبل الإغلاق.")
    if StepSuspension.objects.filter(subject=subject, lifted_at__isnull=True).exists():
        errs.append("توجد خطوة معلّقة لاستيفاء مستند؛ ألغِ التعليق أولاً.")
    return errs


def finish_own_steps(user, subject):
    now = timezone.now()
    refs = set()
    for st in my_steps(user, subject):
        st.status = RS.RESPONDED
        st.is_active_step = False
        st.responded_at = now
        st.save(update_fields=["status", "is_active_step", "responded_at"])
        refs.add(st.referral_id)
    for r in Referral.objects.filter(id__in=refs):
        if not r.recipients.filter(is_active_step=True).exists():
            r.is_completed = True
            r.completed_at = now
            r.save(update_fields=["is_completed", "completed_at"])


def chain_users(subject, exclude=None):
    seen, out = set(), []
    cands = [subject.created_by, subject.current_owner]
    for r in subject.referrals.select_related("referred_by").prefetch_related("recipients__target_user"):
        cands.append(r.referred_by)
        cands += [rc.target_user for rc in r.recipients.all()]
    for u in cands:
        if u is not None and u.id not in seen and (exclude is None or u.id != exclude.id) and u.is_active:
            seen.add(u.id)
            out.append(u)
    return out


def notify_chain(subject, actor, title, message):
    try:
        from notifications.services import NotificationService
        for u in chain_users(subject, actor):
            NotificationService.notify(recipient=u, subject=subject, category="SYSTEM", title=title, message=message,
                                       link_url=f"/subjects/{subject.id}/")
    except Exception:
        pass


def can_close_here(user, subject):
    from accounts.services import PermissionService
    return AA.head_level(user) and PermissionService.user_has_permission(
        user, "SUBJECT_CLOSE", sector=subject.sector, confidentiality_rank=subject.confidentiality.rank, subject=subject)


def request_closure(user, subject, rec, notes):
    sup = rec.referral.referred_by or subject.current_owner
    if sup is None or sup.id == user.id:
        raise ValidationError("لا يوجد مشرف لإرسال الطلب إليه.")
    SubjectAction.objects.create(subject=subject, user=user, choice=None, label=LBL_REQ, notes=notes, target_user=sup)
    from notifications.services import NotificationService
    NotificationService.notify(
        recipient=sup, subject=subject, category="SYSTEM", title=f"طلب إغلاق الموضوع {subject.internal_number}",
        message=f"يطلب {user.get_full_name() or user.username} إغلاق الموضوع." + (f" ملاحظات: {notes}" if notes else ""),
        link_url=f"/subjects/{subject.id}/")
    return sup
