"""من يرى زر «إجراء» وماذا يستطيع: صاحب العهدة، المستلم، أو عضو في السلسلة (مساهمة / تولٍّ عند الغياب)."""
from django.db import transaction
from django.utils import timezone

from accounts.services import PermissionService
from subjects.models import Subject, SubjectAction
from workflow.models import Referral, ReferralRecipient

HEAD_ROLES = {"CHAIRMAN", "SECTOR_HEAD", "GENERAL_MANAGER", "SUPERVISOR", "SECRETARIAT"}
LBL_CONTRIB = "مساهمة / إضافة معلومة"
LBL_PARTICIPANT = "أضاف مشاركاً في التنفيذ"
LBL_ACK = "استلم الموضوع المرفوض"
LBL_TAKEOVER = "تولّى الموضوع بدلاً من"
RS = ReferralRecipient.RecipientStatus


def eff_users(user):
    out = [user]
    for d in PermissionService.get_active_delegations_for_delegate(user):
        if d.allows("REFERRAL_CREATE"):
            out.append(d.delegator)
    return out


def head_level(user):
    if getattr(user, "is_superuser", False) or getattr(user, "is_system_admin", False):
        return True
    return any(PermissionService.get_effective_role_codes(u) & HEAD_ROLES for u in eff_users(user))


def _latest_referral(subject):
    return subject.referrals.order_by("-id").first()


def returned_info(subject):
    lr = _latest_referral(subject)
    if lr is None:
        return None
    rc = lr.recipients.filter(status=RS.RETURNED).select_related("target_user").first()
    if rc is None:
        return None
    u = rc.target_user
    return {"by": (u.get_full_name() or u.username) if u else str(rc.target_unit), "reason": rc.response_notes, "at": rc.responded_at}


def owner_mode(user, subject):
    """صاحب العهدة (أو سكرتاريته) من مستوى الرئاسة، لا خطوة نشطة على الموضوع، ولم يُوجَّه أو عادت إليه العهدة."""
    if not user or not user.is_authenticated or subject.status == Subject.Status.CLOSED:
        return False
    ids = {u.id for u in eff_users(user)}
    if subject.current_owner_id not in ids or not head_level(user):
        return False
    if ReferralRecipient.objects.filter(referral__subject=subject, is_active_step=True).exclude(referral__purpose=Referral.Purpose.FOR_INFO).exists():
        return False
    lr = _latest_referral(subject)
    return lr is None or lr.recipients.filter(status__in=[RS.RETURNED, RS.WITHDRAWN]).exists()


def returned_pending_ack(user, subject):
    """موضوع مرفوض عاد للمرسل ولم يستلمه بعد."""
    info = returned_info(subject)
    if not info or not owner_mode(user, subject):
        return None
    if subject.actions.filter(user=user, label=LBL_ACK, created_at__gte=info["at"]).exists():
        return None
    return info


def chain_mode(user, subject):
    """عضو في السلسلة لا يملك العهدة الآن: مساهمة دائماً، وتولٍّ إن كان رئيساً وصاحب العهدة غائب."""
    none = {"contribute": False, "takeover": False, "holder": ""}
    if not user or not user.is_authenticated or subject.status == Subject.Status.CLOSED:
        return none
    ids = {u.id for u in eff_users(user)}
    holder = subject.current_owner
    holder_name = (holder.get_full_name() or holder.username) if holder else ""
    sent_any = subject.referrals.filter(referred_by_id__in=ids).exists()
    was_recipient = ReferralRecipient.objects.filter(referral__subject=subject, target_user_id__in=ids).exclude(referral__purpose=Referral.Purpose.FOR_INFO).exists()
    above = False
    hu = getattr(holder, "current_unit", None)
    if getattr(user, "is_superuser", False) or getattr(user, "is_system_admin", False):
        above = True
    elif hu is not None:
        for u in eff_users(user):
            uu = getattr(u, "current_unit", None)
            if uu is not None and uu.id != hu.id and uu.is_ancestor_of(hu) and PermissionService.get_effective_role_codes(u) & HEAD_ROLES:
                above = True
                break
    head = head_level(user)
    return {"contribute": sent_any or was_recipient or above,
            "takeover": (sent_any or above) and head and subject.current_owner_id not in ids, "holder": holder_name}


@transaction.atomic
def take_over(user, subject, reason):
    from audit.services import AuditService
    from django.core.exceptions import ValidationError
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("اكتب سبب التولّي (مثل غياب صاحب العهدة).")
    subject = Subject.objects.select_for_update().get(id=subject.id)
    old = subject.current_owner
    old_name = (old.get_full_name() or old.username) if old else "—"
    now = timezone.now()
    steps = ReferralRecipient.objects.select_for_update().filter(referral__subject=subject, is_active_step=True).exclude(referral__purpose=Referral.Purpose.FOR_INFO)
    refs = set()
    for st in steps:
        st.status = RS.WITHDRAWN
        st.is_active_step = False
        st.response_notes = reason
        st.responded_at = now
        st.save(update_fields=["status", "is_active_step", "response_notes", "responded_at"])
        refs.add(st.referral_id)
    for r in Referral.objects.filter(id__in=refs):
        if not r.recipients.filter(is_active_step=True).exists():
            r.is_withdrawn = True
            r.is_completed = True
            r.completed_at = now
            r.save(update_fields=["is_withdrawn", "is_completed", "completed_at"])
    subject.current_owner = user
    subject.save(update_fields=["current_owner"])
    SubjectAction.objects.create(subject=subject, user=user, choice=None, label=f"{LBL_TAKEOVER} {old_name}", notes=reason)
    AuditService.record_activity(subject=subject, action_type="SUBJECT_TAKEOVER", actor_user=user,
                                 description=f"{user} تولّى الموضوع بدلاً من {old_name} — {reason}", metadata={"reason": reason, "old": old_name})
    return old
