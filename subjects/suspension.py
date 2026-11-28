"""تعليق خطوة لاستيفاء مستند: تعليق جزئي، إشعارات، استئناف تلقائي، إيقاف احتساب الاستحقاق، تذكير."""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.services import PermissionService
from subjects.models import StepSuspension, Subject, SubjectAction, SubjectStatusHistory
from workflow.models import Referral, ReferralRecipient

LBL_SUS = "علّق الخطوة لاستيفاء مستند"
LBL_CANCEL = "ألغى تعليق الخطوة"


def active_for(subject):
    return StepSuspension.objects.filter(subject=subject, lifted_at__isnull=True).select_related("requested_user", "requested_unit", "holder")


def _steps(subject):
    return ReferralRecipient.objects.filter(referral__subject=subject, is_active_step=True).exclude(referral__purpose=Referral.Purpose.FOR_INFO)


def _all_suspended(subject):
    ids = set(_steps(subject).values_list("id", flat=True))
    sus = set(active_for(subject).values_list("recipient_id", flat=True))
    return bool(ids) and ids <= sus


def _set_status(subject, new, user, why):
    old = subject.status
    if old == new:
        return
    Subject.objects.filter(id=subject.id).update(status=new, last_action_at=timezone.now())
    subject.status = new
    SubjectStatusHistory.objects.create(subject=subject, from_status=old, to_status=new, changed_by=user, reason=why)


def _notify(user, subject, title, msg, cat="SUSPENSION"):
    if user is None:
        return
    try:
        from notifications.services import NotificationService
        NotificationService.notify(recipient=user, subject=subject, category=cat, title=title, message=msg,
                                   link_url=f"/subjects/{subject.id}/")
    except Exception:
        pass


def _notify_requested(user, subject, item):
    """إشعار على الشاشة فقط؛ لا صلاحية اطلاع ولا دور للمطلوب منه (يفتح صفحة طلب الإلغاء)."""
    from notifications.models import Notification
    secret = subject.confidentiality.overrides_hierarchy
    Notification.objects.create(
        recipient=user, category="SUSPENSION",
        title="مطلوب منك مستند" if secret else f"مطلوب منك مستند للموضوع {subject.internal_number}",
        message=f"المطلوب: {item}" if not secret else "طلب استيفاء مستند.",
        link_url=f"/subjects/{subject.id}/suspension-request/", reason_for_level="طلب استيفاء")


@transaction.atomic
def request_cancel(user, subject):
    sus = [s for s in active_for(subject) if can_supply(user, s)]
    if not sus:
        raise ValidationError("لا يوجد طلب موجّه إليك.")
    name = user.get_full_name() or user.username
    for s in sus:
        SubjectAction.objects.create(subject=subject, user=user, choice=None, label="طلب إلغاء تعليق الخطوة", notes=s.required_item)
        _notify(s.holder, subject, f"طلب إلغاء تعليق: {subject.internal_number}",
                f"يطلب {name} إلغاء التعليق على: {s.required_item}")


def _recipients_of(s):
    if s.requested_user_id:
        return [s.requested_user]
    if s.requested_unit_id:
        from accounts.models import User
        users = [u for u in User.objects.filter(is_active=True) if getattr(u, "current_unit", None) and u.current_unit.id == s.requested_unit_id]
        heads = [u for u in users if PermissionService.get_effective_role_codes(u) & {"SUPERVISOR", "SECTOR_HEAD", "GENERAL_MANAGER", "SECRETARIAT"}]
        return heads or users[:3]
    return []


@transaction.atomic
def suspend_step(user, subject, rec, item, user_id=None, unit_id=None, follow_up=None):
    from accounts.models import User
    from organization.models import OrgUnit
    item = (item or "").strip()
    if not item:
        raise ValidationError("اكتب المستند أو الإجراء المطلوب.")
    ru = User.objects.filter(id=user_id, is_active=True).first() if user_id else None
    un = OrgUnit.objects.filter(id=unit_id).first() if (unit_id and not ru) else None
    if not ru and not un:
        raise ValidationError("حدّد الشخص أو الوحدة المطلوب منها المستند.")
    if active_for(subject).filter(recipient=rec).exists():
        raise ValidationError("هذه الخطوة معلّقة بالفعل.")
    prior = subject.status if subject.status != Subject.Status.SUSPENDED else Subject.Status.IN_PROGRESS
    s = StepSuspension.objects.create(subject=subject, recipient=rec, holder=user, required_item=item, requested_user=ru,
                                      requested_unit=un, follow_up_date=follow_up, prior_status=prior)
    SubjectAction.objects.create(subject=subject, user=user, choice=None, label=LBL_SUS,
                                 notes=f"المطلوب: {item} — من: {s.requested_label}", target_user=ru)
    for t in _recipients_of(s):
        _notify_requested(t, subject, item)
    if _all_suspended(subject):
        _set_status(subject, Subject.Status.SUSPENDED, user, f"تعليق لاستيفاء: {item}")
    return s


def _lift(subject, s, user, kind, notes=""):
    now = timezone.now()
    fully = subject.status == Subject.Status.SUSPENDED
    if fully:
        began = max(a.suspended_at for a in active_for(subject)).date()
        days = (timezone.localdate() - began).days
        if days > 0 and subject.due_date:
            Subject.objects.filter(id=subject.id).update(due_date=subject.due_date + timedelta(days=days))
            subject.due_date = subject.due_date + timedelta(days=days)
    s.lifted_at, s.lifted_by, s.lift_kind = now, user, kind
    s.save(update_fields=["lifted_at", "lifted_by", "lift_kind"])
    if fully:
        _set_status(subject, s.prior_status or Subject.Status.IN_PROGRESS, user, "إلغاء التعليق")
    h = s.holder
    _notify(h, subject, f"عاد الموضوع {subject.internal_number} إليك",
            f"أُلغي تعليق الخطوة بواسطة {user.get_full_name() or user.username}: " + s.required_item)


def can_supply(user, s):
    if s.requested_user_id:
        return s.requested_user_id == user.id
    u = getattr(user, "current_unit", None)
    return bool(s.requested_unit_id and u is not None and u.id == s.requested_unit_id)


def can_cancel(user, subject, ch):
    sus = list(active_for(subject))
    if not sus:
        return False
    return any(s.holder_id == user.id for s in sus) or bool(ch.get("takeover"))


@transaction.atomic
def cancel(user, subject, note=""):
    for s in list(active_for(subject)):
        SubjectAction.objects.create(subject=subject, user=user, choice=None, label=LBL_CANCEL, notes=s.required_item)
        _lift(subject, s, user, "CANCEL")


def release_for_takeover(user, subject):
    """عند تولّي المشرف الموضوع تُلغى التعليقات على الخطوات المسحوبة."""
    if active_for(subject).exists():
        cancel(user, subject)


def send_due_reminders():
    """تذكير المتابعة: يُستدعى عند فتح القائمة (لا يوجد مجدول في النظام)."""
    today = timezone.localdate()
    n = 0
    for s in StepSuspension.objects.filter(lifted_at__isnull=True, reminded=False, follow_up_date__lt=today).select_related("subject", "holder", "requested_user"):
        _notify(s.holder, s.subject, f"حان موعد متابعة المستند: {s.subject.internal_number}",
                f"لم يُستلم بعد: {s.required_item} (من {s.requested_label}).")
        for t in _recipients_of(s):
            _notify(t, s.subject, f"تذكير: مستند مطلوب للموضوع {s.subject.internal_number}", f"المطلوب: {s.required_item}")
        s.reminded = True
        s.save(update_fields=["reminded"])
        n += 1
    return n
