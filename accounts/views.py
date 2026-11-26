from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from organization.models import Employee, OrgUnit, Sector
from audit.services import AuditService
from .models import (
    Delegation,
    LoginAuditLog,
    PermissionCode,
    Role,
    RolePermission,
    User,
    UserRoleAssignment,
)
from .services import PermissionService


def _get_client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def login_view(request):
    """شاشة تسجيل الدخول مع تسجيل محاولات الدخول الناجحة والفاشلة."""
    if request.user.is_authenticated:
        return redirect("core:dashboard")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        ip = _get_client_ip(request)
        ua = (request.META.get("HTTP_USER_AGENT") or "")[:250]

        user = authenticate(request, username=username, password=password)
        if user is not None and user.is_active:
            login(request, user)
            LoginAuditLog.objects.create(
                username_attempted=username,
                user=user,
                ip_address=ip,
                success=True,
                user_agent=ua,
            )
            AuditService.log_audit(
                actor=user,
                action="LOGIN_SUCCESS",
                model_name="User",
                object_id=user.id,
                ip_address=ip,
            )
            return redirect(request.GET.get("next") or "core:dashboard")

        LoginAuditLog.objects.create(
            username_attempted=username,
            user=None,
            ip_address=ip,
            success=False,
            user_agent=ua,
        )
        messages.error(request, "اسم المستخدم أو كلمة المرور غير صحيحة أو الحساب موقوف.")

    return render(request, "accounts/login.html")


@login_required
def logout_view(request):
    if request.method == "POST":
        AuditService.log_audit(
            actor=request.user,
            action="LOGOUT",
            model_name="User",
            object_id=request.user.id,
            ip_address=_get_client_ip(request),
        )
        logout(request)
    return redirect("accounts:login")


@login_required
def switch_user_view(request):
    """مبدّل المستخدمين السريع للاختبار المحلي قبل النشر (يُعطّل تلقائياً عند إيقاف DEBUG)."""
    if not getattr(settings, "ENABLE_DEV_ACCOUNT_SWITCHER", False):
        raise PermissionDenied("مبدّل المستخدمين متاح في وضع الاختبار المحلي فقط.")

    raw_val = (
        request.POST.get("user_id")
        or request.POST.get("target_user_id")
        or request.POST.get("username")
        or request.GET.get("user_id")
        or request.GET.get("username")
        or ""
    ).strip()

    target = None
    if raw_val:
        if raw_val.isdigit():
            target = User.objects.filter(id=int(raw_val), is_active=True).first()
        if not target:
            target = User.objects.filter(username=raw_val, is_active=True).first()
        if not target:
            target = User.objects.filter(username__iexact=raw_val, is_active=True).first()
        if not target and raw_val.isdigit():
            target = User.objects.filter(id=int(raw_val)).first()

    if not target:
        messages.error(request, f"تعذر تبديل الحساب: المستخدم ({raw_val or 'غير محدد'}) غير موجود أو غير مفعل في قاعدة البيانات.")
    else:
        prev_username = request.user.username
        login(request, target, backend="django.contrib.auth.backends.ModelBackend")
        AuditService.log_audit(
            actor=target,
            action="DEV_SWITCH_USER",
            model_name="User",
            object_id=target.id,
            before_state={"from_user": prev_username},
            after_state={"to_user": target.username},
            ip_address=_get_client_ip(request),
        )
        messages.info(request, f"تم التبديل محلياً إلى الحساب: {target.get_full_name() or target.username} ({target.job_display_title or 'مستخدم'})")

    next_url = request.POST.get("next") or request.GET.get("next") or request.META.get("HTTP_REFERER") or "core:dashboard"
    if isinstance(next_url, str) and next_url.startswith("/"):
        return redirect(next_url)
    return redirect("core:dashboard")


def create_user_account(actor, *, username, password, full_name, job_title="", emp_no="", unit_obj=None, role_obj=None,
                        sector_obj=None, is_secretariat=False, is_active=True, ip=None):
    """إنشاء مستخدم + موظف + إسناد دور (المنطق الأصلي لشاشة إدارة المستخدمين، مستخرج ليُعاد استخدامه في الاستيراد الجماعي)."""
    from django.db import transaction
    from core.models import SystemSequence
    from organization.models import PositionAssignment
    is_full_admin = bool(actor.is_superuser or actor.is_system_admin)
    forbidden_roles_for_scoped = {"SYSTEM_ADMIN", "CHAIRMAN", "SECTOR_DIR_ADMIN"}
    if not is_full_admin:
        if unit_obj is None:
            raise PermissionDenied("يجب تحديد الوحدة التنظيمية داخل نطاقك عند إنشاء المستخدم.")
        if not PermissionService.can_manage_target_user(
            actor,
            target_sector_id=sector_obj.id if sector_obj else None,
            target_unit_id=unit_obj.id,
        ):
            raise PermissionDenied("لا يمكنك إنشاء مستخدم خارج نطاق قطاعك أو إدارتك العامة.")
        if role_obj and role_obj.code in forbidden_roles_for_scoped:
            raise PermissionDenied("لا يمكنك إسناد دور قيادي أعلى أو مسؤول نظام.")

    with transaction.atomic():
        emp_obj = None
        if unit_obj is not None:
            final_emp_no = emp_no or SystemSequence.next_number("EMPLOYEE", "EMP")
            if Employee.objects.filter(employee_number=final_emp_no).exists():
                final_emp_no = SystemSequence.next_number("EMPLOYEE", "EMP")
            emp_obj = Employee.objects.create(
                employee_number=final_emp_no,
                full_name=full_name,
                job_title=job_title or (role_obj.name if role_obj else "موظف"),
                current_unit=unit_obj,
                is_active=is_active,
            )
            PositionAssignment.objects.create(
                employee=emp_obj,
                org_unit=unit_obj,
                position_title=emp_obj.job_title,
                start_date=timezone.localdate(),
                is_current=True,
            )

        new_user = User.objects.create(
            username=username,
            first_name=full_name,
            employee=emp_obj,
            job_display_title=job_title or (role_obj.name if role_obj else ""),
            is_secretariat=is_secretariat,
            is_active=is_active,
            is_superuser=False,
            is_staff=False,
            is_system_admin=False,
        )
        new_user.set_password(password)
        new_user.save()

        if role_obj is not None:
            UserRoleAssignment.objects.create(
                user=new_user,
                role=role_obj,
                sector=sector_obj,
                org_unit=unit_obj,
                is_active=True,
            )

        AuditService.log_audit(
            actor=actor,
            action="USER_CREATED",
            model_name="User",
            object_id=new_user.id,
            after_state={
                "username": username,
                "unit": unit_obj.code if unit_obj else None,
                "role": role_obj.code if role_obj else None,
            },
            ip_address=ip,
        )


@login_required
def users_list(request):
    """إدارة حسابات المستخدمين (Superuser بالكامل، ومسؤول القطاع/الإدارة العامة ضمن نطاقه فقط)."""
    if not PermissionService.can_manage_users(request.user):
        raise PermissionDenied("شاشة إدارة المستخدمين مخصصة لمدير النظام أو مسؤول القطاع/الإدارة العامة المفوض.")

    is_full_admin = bool(request.user.is_superuser or request.user.is_system_admin)
    bounds = PermissionService.get_scoped_admin_boundaries(request.user)
    forbidden_roles_for_scoped = {"SYSTEM_ADMIN", "CHAIRMAN", "SECTOR_DIR_ADMIN"}

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create_user":
            from django.db import transaction
            from core.models import SystemSequence
            from organization.models import PositionAssignment

            username = request.POST.get("username", "").strip()
            password = request.POST.get("password", "")
            full_name = request.POST.get("full_name", "").strip()
            job_title = request.POST.get("job_display_title", "").strip()
            emp_no = request.POST.get("employee_number", "").strip()
            unit_id = request.POST.get("org_unit_id") or None
            role_id = request.POST.get("role_id") or None
            sector_id = request.POST.get("sector_id") or None
            is_secretariat = request.POST.get("is_secretariat") == "on"
            is_active = request.POST.get("is_active", "on") == "on"

            if not username or not password or not full_name:
                messages.error(request, "اسم المستخدم وكلمة المرور والاسم الكامل حقول مطلوبة.")
            elif len(password) < 3:
                messages.error(request, "كلمة المرور يجب ألا تقل عن 3 أحرف.")
            elif User.objects.filter(username=username).exists():
                messages.error(request, f"اسم المستخدم ({username}) مسجل بالفعل.")
            else:
                unit_obj = get_object_or_404(OrgUnit, id=unit_id) if unit_id else None
                role_obj = get_object_or_404(Role, id=role_id) if role_id else None
                sector_obj = (
                    get_object_or_404(Sector, id=sector_id)
                    if sector_id
                    else (unit_obj.sector if unit_obj else None)
                )
                create_user_account(
                    request.user, username=username, password=password, full_name=full_name, job_title=job_title,
                    emp_no=emp_no, unit_obj=unit_obj, role_obj=role_obj, sector_obj=sector_obj,
                    is_secretariat=is_secretariat, is_active=is_active, ip=_get_client_ip(request),
                )
                messages.success(request, f"تم إنشاء حساب المستخدم ({full_name} / {username}) بنجاح.")

        elif action == "assign_role":
            user_obj = get_object_or_404(User, id=request.POST.get("user_id"))
            role_obj = get_object_or_404(Role, id=request.POST.get("role_id"))
            sector_id = request.POST.get("sector_id") or None
            unit_id = request.POST.get("org_unit_id") or None
            if not is_full_admin:
                if not PermissionService.can_manage_target_user(
                    request.user, target_user=user_obj, target_sector_id=sector_id, target_unit_id=unit_id
                ):
                    raise PermissionDenied("لا يمكنك تعديل أدوار مستخدم خارج نطاقك.")
                if role_obj.code in forbidden_roles_for_scoped:
                    raise PermissionDenied("لا يمكنك إسناد هذا الدور في مستواك.")
            UserRoleAssignment.objects.create(
                user=user_obj,
                role=role_obj,
                sector_id=sector_id,
                org_unit_id=unit_id,
            )
            AuditService.log_audit(
                actor=request.user,
                action="ASSIGN_ROLE",
                model_name="UserRoleAssignment",
                object_id=user_obj.id,
                after_state={"role": role_obj.code, "sector_id": sector_id, "org_unit_id": unit_id},
                ip_address=_get_client_ip(request),
            )
            messages.success(request, f"تم إسناد الدور ({role_obj.name}) إلى {user_obj.username}.")

        elif action == "remove_role":
            assignment = get_object_or_404(UserRoleAssignment, id=request.POST.get("assignment_id"))
            if not is_full_admin and not PermissionService.can_manage_target_user(request.user, target_user=assignment.user):
                raise PermissionDenied("لا يمكنك سحب أدوار مستخدم خارج نطاقك.")
            AuditService.log_audit(
                actor=request.user,
                action="REMOVE_ROLE",
                model_name="UserRoleAssignment",
                object_id=assignment.user_id,
                before_state={"role": assignment.role.code},
                ip_address=_get_client_ip(request),
            )
            assignment.delete()
            messages.info(request, "تم إزالة الدور من المستخدم.")

        elif action == "toggle_active":
            user_obj = get_object_or_404(User, id=request.POST.get("user_id"))
            if not is_full_admin and not PermissionService.can_manage_target_user(request.user, target_user=user_obj):
                raise PermissionDenied("لا يمكنك تعديل حالة مستخدم خارج نطاقك.")
            if user_obj.id != request.user.id and not (user_obj.is_superuser and not is_full_admin):
                user_obj.is_active = not user_obj.is_active
                user_obj.deactivated_at = None if user_obj.is_active else timezone.now()
                user_obj.save(update_fields=["is_active", "deactivated_at"])
                AuditService.log_audit(
                    actor=request.user,
                    action="TOGGLE_USER_ACTIVE",
                    model_name="User",
                    object_id=user_obj.id,
                    after_state={"is_active": user_obj.is_active},
                    ip_address=_get_client_ip(request),
                )
                messages.success(request, "تم تحديث حالة الحساب بنجاح.")

        elif action == "delete_user":
            user_obj = get_object_or_404(User, id=request.POST.get("user_id"))
            if user_obj.id == request.user.id:
                messages.error(request, "لا يمكنك حذف حسابك الشخصي أثناء تسجيل الدخول.")
            elif user_obj.is_superuser or user_obj.is_system_admin:
                raise PermissionDenied("لا يمكن حذف حساب مدير النظام الأعلى.")
            elif not is_full_admin and not PermissionService.can_manage_target_user(request.user, target_user=user_obj):
                raise PermissionDenied("لا يمكنك حذف مستخدم خارج نطاق قطاعك أو إدارتك العامة.")
            else:
                target_username = user_obj.username
                target_id = user_obj.id
                emp_obj = user_obj.employee
                try:
                    user_obj.role_assignments.all().delete()
                    user_obj.notifications.all().delete()
                    user_obj.delete()
                    if emp_obj is not None:
                        try:
                            emp_obj.delete()
                        except ProtectedError:
                            pass
                    AuditService.log_audit(
                        actor=request.user,
                        action="USER_DELETED",
                        model_name="User",
                        object_id=target_id,
                        before_state={"username": target_username},
                        ip_address=_get_client_ip(request),
                    )
                    messages.success(request, f"تم حذف المستخدم ({target_username}) نهائياً.")
                except ProtectedError:
                    user_obj.is_active = False
                    user_obj.deactivated_at = timezone.now()
                    user_obj.save(update_fields=["is_active", "deactivated_at"])
                    AuditService.log_audit(
                        actor=request.user,
                        action="USER_DEACTIVATED_PROTECTED",
                        model_name="User",
                        object_id=target_id,
                        before_state={"username": target_username},
                        reason="مرتبط بسجلات تاريخية؛ تم إيقافه بدلاً من الحذف",
                        ip_address=_get_client_ip(request),
                    )
                    messages.warning(request, f"المستخدم ({target_username}) مرتبط بمراسلات تاريخية؛ تم إيقاف حسابه حفاظاً على سلامة السجل.")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            from django.http import JsonResponse
            msgs = list(messages.get_messages(request))
            ok = any(m.level_tag == "success" for m in msgs) and not any(m.level_tag == "error" for m in msgs)
            return JsonResponse({"ok": ok, "message": " ".join(str(m) for m in msgs), "error": "" if ok else " ".join(str(m) for m in msgs)}, status=200 if ok else 400)
        return redirect("accounts:users_list")

    users_qs = User.objects.select_related("employee__current_unit__sector").prefetch_related(
        "role_assignments__role", "role_assignments__sector", "role_assignments__org_unit"
    )
    all_users = list(users_qs)
    if is_full_admin:
        users = all_users
        roles = Role.objects.all()
        sectors = Sector.objects.all()
        org_units = OrgUnit.objects.select_related("sector", "unit_type", "parent").all()
    else:
        users = [
            u for u in all_users
            if not u.is_superuser and not u.is_system_admin and PermissionService.can_manage_target_user(request.user, target_user=u)
        ]
        roles = Role.objects.exclude(code__in=forbidden_roles_for_scoped)
        sectors = Sector.objects.filter(id__in=bounds["sector_ids"])
        org_units = OrgUnit.objects.filter(id__in=bounds["unit_ids"]).select_related("sector", "unit_type", "parent")

    for u in users:
        u.scope_info = PermissionService.describe_user_scope(u)
    employees = Employee.objects.all()
    return render(
        request,
        "accounts/users.html",
        {
            "users": users,
            "roles": roles,
            "sectors": sectors,
            "org_units": org_units,
            "employees": employees,
            "is_full_admin": is_full_admin,
        },
    )


@login_required
def permissions_matrix(request):
    """عرض وإدارة مصفوفة الصلاحيات وضوابط السرية — متاحة حصرياً للـ Superuser فقط."""
    if not request.user.is_superuser:
        raise PermissionDenied("شاشة إدارة الصلاحيات مخصصة لمدير النظام الأعلى (Superuser) فقط.")

    if request.method == "POST":
        op = request.POST.get("op")
        if op == "toggle":
            role = get_object_or_404(Role, id=request.POST.get("role_id"))
            perm = get_object_or_404(PermissionCode, id=request.POST.get("permission_id"))
            max_rank = int(request.POST.get("max_confidentiality_rank", "3"))
            existing = RolePermission.objects.filter(role=role, permission=perm).first()
            if existing:
                existing.delete()
                messages.info(request, f"تم سحب صلاحية ({perm.name}) من دور ({role.name}).")
            else:
                RolePermission.objects.create(
                    role=role, permission=perm, max_confidentiality_rank=max_rank
                )
                messages.success(request, f"تم منح صلاحية ({perm.name}) لدور ({role.name}).")
        elif op == "toggle_role_flag":
            role = get_object_or_404(Role, id=request.POST.get("role_id"))
            flag_name = request.POST.get("flag_name", "")
            allowed_flags = {
                "allow_hierarchical_view",
                "can_view_confidential",
                "can_view_top_secret",
                "can_download_secret_attachments",
            }
            if flag_name in allowed_flags:
                new_val = not getattr(role, flag_name)
                setattr(role, flag_name, new_val)
                role.save(update_fields=[flag_name])
                AuditService.log_audit(
                    actor=request.user,
                    action="UPDATE_ROLE_FLAG",
                    model_name="Role",
                    object_id=role.id,
                    after_state={"flag": flag_name, "value": new_val},
                    ip_address=_get_client_ip(request),
                )
                messages.success(request, f"تم تحديث ضابط الأمان للدور ({role.name}).")
        return redirect("accounts:permissions_matrix")

    roles = Role.objects.prefetch_related("permissions").all()
    permissions = PermissionCode.objects.all()
    role_perm_map = {
        (rp.role_id, rp.permission_id): rp
        for rp in RolePermission.objects.all()
    }
    return render(
        request,
        "accounts/permissions_matrix.html",
        {
            "roles": roles,
            "permissions": permissions,
            "role_perm_map": role_perm_map,
            "manager_role_codes": {"SYSTEM_ADMIN", "CHAIRMAN", "SECTOR_HEAD", "GENERAL_MANAGER"},
        },
    )


@login_required
def delegations_view(request):
    """إدارة السكرتارية والإنابة المؤقتة مع الاحتفاظ بالسجل التاريخي."""
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create_delegation":
            if not PermissionService.user_has_permission(request.user, "DELEGATION_MANAGE"):
                raise PermissionDenied("ليس لديك صلاحية إنشاء تفويض أو إنابة.")
            delegate = get_object_or_404(User, id=request.POST.get("delegate_id"))
            delegator_id = request.POST.get("delegator_id")
            delegator = get_object_or_404(User, id=delegator_id) if delegator_id else request.user
            allowed_actions = request.POST.getlist("allowed_actions")
            valid_from = parse_datetime(request.POST.get("valid_from", "")) or timezone.now()
            valid_to = parse_datetime(request.POST.get("valid_to", "")) or (
                timezone.now() + timezone.timedelta(days=30)
            )
            if timezone.is_naive(valid_from):
                valid_from = timezone.make_aware(valid_from)
            if timezone.is_naive(valid_to):
                valid_to = timezone.make_aware(valid_to)

            delegation = Delegation.objects.create(
                delegator=delegator,
                delegate=delegate,
                delegation_type=request.POST.get("delegation_type", Delegation.DelegationType.SECRETARIAT),
                scope_unit_id=request.POST.get("scope_unit_id") or None,
                allowed_actions=allowed_actions,
                allow_confidential=request.POST.get("allow_confidential") == "on",
                valid_from=valid_from,
                valid_to=valid_to,
            )
            AuditService.log_audit(
                actor=request.user,
                action="CREATE_DELEGATION",
                model_name="Delegation",
                object_id=delegation.id,
                after_state={"delegator": delegator.username, "delegate": delegate.username},
                ip_address=_get_client_ip(request),
            )
            messages.success(request, "تم تسجيل التفويض بنجاح.")
        elif action == "revoke":
            delegation = get_object_or_404(Delegation, id=request.POST.get("delegation_id"))
            if delegation.delegator_id != request.user.id and not PermissionService.user_has_permission(
                request.user, "DELEGATION_MANAGE"
            ):
                raise PermissionDenied("لا تملك صلاحية إلغاء هذا التفويض.")
            delegation.is_active = False
            delegation.revoked_at = timezone.now()
            delegation.revoked_reason = request.POST.get("revoked_reason", "إلغاء يدوي")
            delegation.save(update_fields=["is_active", "revoked_at", "revoked_reason"])
            AuditService.log_audit(
                actor=request.user,
                action="REVOKE_DELEGATION",
                model_name="Delegation",
                object_id=delegation.id,
                reason=delegation.revoked_reason,
                ip_address=_get_client_ip(request),
            )
            messages.info(request, "تم إلغاء التفويض مع الاحتفاظ بسجله التاريخي.")
        return redirect("accounts:delegations")

    delegations = Delegation.objects.select_related("delegator", "delegate", "scope_unit").all()
    users = User.objects.filter(is_active=True)
    org_units = OrgUnit.objects.filter(is_active=True)
    permission_codes = PermissionCode.objects.all()
    return render(
        request,
        "accounts/delegations.html",
        {
            "delegations": delegations,
            "users": users,
            "org_units": org_units,
            "permission_codes": permission_codes,
        },
    )
