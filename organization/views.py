import json
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from accounts.models import User
from accounts.services import PermissionService
from audit.services import AuditService
from .models import Company, Employee, OrgUnit, OrgUnitType, PositionAssignment, Sector


def _ensure_holding_umbrella():
    """ضمان وجود مظلة الشركة القابضة لكهرباء مصر وشركة غرب الدلتا لإنتاج الكهرباء دون المساس بالهيكل الحالي."""
    holding, _ = Company.objects.get_or_create(
        code="EEHC",
        defaults={
            "name": "الشركة القابضة لكهرباء مصر",
            "short_name": "الشركة القابضة",
            "is_holding": True,
            "is_active": True,
        },
    )
    wdepco, _ = Company.objects.get_or_create(
        code="WDEPCO",
        defaults={
            "name": "شركة غرب الدلتا لإنتاج الكهرباء",
            "short_name": "غرب الدلتا",
            "is_holding": False,
            "parent_company": holding,
            "is_active": True,
        },
    )
    if wdepco.parent_company_id is None:
        wdepco.parent_company = holding
        wdepco.save(update_fields=["parent_company"])
    Sector.objects.filter(company__isnull=True).update(company=wdepco)
    return holding, wdepco


def _infer_unit_level(unit: OrgUnit) -> str:
    ut_code = (unit.unit_type.code if unit.unit_type_id else "").upper()
    if ut_code in {"CHAIRMAN", "L1"} or (unit.parent_id is None and "رئيس" in (unit.name or "")):
        return "L1"
    if ut_code in {"SECTOR", "MAIN_SECTOR", "L2"} or (unit.unit_type_id and unit.unit_type.level_order == 2):
        return "L2"
    if ut_code in {"SUB_SECTOR", "L3"} or (unit.unit_type_id and unit.unit_type.level_order == 3):
        return "L3"
    if ut_code in {"GENERAL_DEPT", "GENERAL_DIRECTORATE", "L4"} or (unit.unit_type_id and unit.unit_type.level_order == 4):
        return "L4"
    if ut_code in {"SECRETARIAT", "L6"} or "سكرتارية" in (unit.name or ""):
        return "L6"
    return "L5"


@login_required
def org_tree(request):
    """عرض وإدارة الهيكل التنظيمي الديناميكي متعدد الشركات والقطاعات تحت مظلة الشركة القابضة."""
    if not PermissionService.user_has_permission(request.user, "ORG_VIEW"):
        raise PermissionDenied("ليس لديك صلاحية الاطلاع على الهيكل التنظيمي.")

    holding_company, west_delta = _ensure_holding_umbrella()

    if request.method == "POST":
        if not PermissionService.user_has_permission(request.user, "ORG_MANAGE"):
            raise PermissionDenied("ليس لديك صلاحية تعديل الهيكل التنظيمي.")
        action = request.POST.get("action")
        company_redirect = request.POST.get("company_filter", "").strip()
        if action == "create_company":
            code = request.POST.get("code", "").strip().upper()
            name = request.POST.get("name", "").strip()
            short_name = request.POST.get("short_name", "").strip() or name[:40]
            if not code or not name:
                messages.error(request, "كود الشركة واسمها مطلوبان.")
            elif Company.objects.filter(code=code).exists():
                messages.error(request, f"كود الشركة ({code}) مسجل بالفعل.")
            else:
                with transaction.atomic():
                    new_comp = Company.objects.create(
                        code=code,
                        name=name,
                        short_name=short_name,
                        is_holding=False,
                        parent_company=holding_company,
                        is_active=True,
                    )
                    # إنشاء قطاع رئيسي ووحدة رئاسة مجلس إدارة للشركة الجديدة دون المساس بشركة غرب الدلتا
                    root_sec = Sector.objects.create(
                        code=f"{code}_BOARD",
                        name=f"رئاسة مجلس الإدارة ({short_name})",
                        company=new_comp,
                    )
                    t_chair = OrgUnitType.objects.filter(code="CHAIRMAN").first() or OrgUnitType.objects.order_by("level_order").first()
                    if t_chair is not None:
                        OrgUnit.objects.create(
                            code=f"UNIT_{code}_CHAIR",
                            name=f"مكتب رئيس مجلس إدارة {short_name}",
                            unit_type=t_chair,
                            sector=root_sec,
                        )
                    AuditService.log_audit(
                        actor=request.user,
                        action="COMPANY_CREATED",
                        model_name="Company",
                        object_id=new_comp.id,
                        after_state={"code": code, "name": name, "parent": holding_company.code},
                    )
                company_redirect = code
                messages.success(request, f"تمت إضافة الشركة الشقيقة ({name}) تحت مظلة الشركة القابضة بنجاح.")
        elif action == "create_sector":
            code = request.POST.get("code", "").strip().upper()
            name = request.POST.get("name", "").strip()
            company_id = request.POST.get("company_id") or west_delta.id
            if code and name:
                Sector.objects.get_or_create(
                    code=code,
                    defaults={"name": name, "company_id": company_id},
                )
                messages.success(request, f"تمت إضافة القطاع ({name}) بنجاح.")
        elif action == "create_unit":
            code = request.POST.get("code", "").strip().upper()
            name = request.POST.get("name", "").strip()
            unit_type_id = request.POST.get("unit_type_id")
            sector_id = request.POST.get("sector_id")
            parent_id = request.POST.get("parent_id") or None
            if not sector_id and parent_id:
                parent_obj = OrgUnit.objects.filter(id=parent_id).first()
                if parent_obj:
                    sector_id = parent_obj.sector_id
            if code and name and unit_type_id and sector_id:
                OrgUnit.objects.create(
                    code=code,
                    name=name,
                    unit_type_id=unit_type_id,
                    sector_id=sector_id,
                    parent_id=parent_id,
                )
                messages.success(request, f"تمت إضافة الوحدة التنظيمية ({name}) بنجاح.")
        if company_redirect and company_redirect != "ALL":
            return redirect(f"/organization/?company={company_redirect}")
        return redirect("organization:org_tree")

    selected_company_code = request.GET.get("company", "").strip().upper() or "ALL"
    subsidiaries = list(
        Company.objects.filter(is_holding=False, is_active=True).prefetch_related(
            "sectors__org_units__unit_type",
            "sectors__org_units__parent",
            "sectors__org_units__manager_employee",
        )
    )
    selected_company = (
        next((c for c in subsidiaries if c.code == selected_company_code), None)
        if selected_company_code and selected_company_code != "ALL"
        else None
    )

    sectors_qs = Sector.objects.select_related("company").prefetch_related(
        "org_units__unit_type", "org_units__parent", "org_units__manager_employee"
    )
    if selected_company:
        sectors = list(sectors_qs.filter(company=selected_company))
    else:
        sectors = list(sectors_qs.all())

    unit_types = list(OrgUnitType.objects.all())
    all_units = list(
        OrgUnit.objects.filter(is_active=True)
        .select_related("sector__company", "unit_type", "parent", "manager_employee")
        .order_by("unit_type__level_order", "id")
    )
    visible_units = [u for u in all_units if (not selected_company or (u.sector and u.sector.company_id == selected_company.id))]
    employees = list(Employee.objects.filter(is_active=True).select_related("current_unit", "user_account"))

    # تجميع المستخدمين والموظفين تحت كل وحدة تنظيمية لعرضهم مباشرة في الشجرة التفاعلية
    unit_users_map: dict[int, list[dict]] = {}
    for emp in employees:
        if not emp.current_unit_id:
            continue
        user_acc = getattr(emp, "user_account", None)
        if user_acc and not user_acc.is_active:
            continue
        unit_users_map.setdefault(emp.current_unit_id, []).append(
            {
                "employee_id": emp.id,
                "user_id": user_acc.id if user_acc else None,
                "username": user_acc.username if user_acc else emp.employee_number,
                "full_name": (user_acc.get_full_name() if user_acc else "") or emp.full_name,
                "job_title": (user_acc.job_display_title if user_acc else "") or emp.job_title,
                "is_secretariat": bool(user_acc.is_secretariat) if user_acc else False,
                "has_account": bool(user_acc),
            }
        )

    tree_units_payload = []
    for u in visible_units:
        comp = u.sector.company if u.sector else west_delta
        level_code = _infer_unit_level(u)
        u_users = unit_users_map.get(u.id, [])
        tree_units_payload.append(
            {
                "id": u.id,
                "code": u.code,
                "name": u.name,
                "parent_id": u.parent_id,
                "parent_code": u.parent.code if u.parent else "",
                "sector_id": u.sector_id,
                "sector_name": u.sector.name if u.sector else "",
                "company_code": comp.code if comp else "WDEPCO",
                "company_name": comp.name if comp else west_delta.name,
                "level": level_code,
                "unit_type": u.unit_type.name if u.unit_type else "",
                "level_order": u.unit_type.level_order if u.unit_type else 5,
                "users_count": len(u_users),
                "users": u_users,
            }
        )

    tree_companies_payload = [
        {
            "id": c.id,
            "code": c.code,
            "name": c.name,
            "short_name": c.short_name or c.name,
            "units_count": sum(1 for u in all_units if u.sector and u.sector.company_id == c.id),
        }
        for c in subsidiaries
        if (not selected_company or c.id == selected_company.id)
    ]

    org_tree_payload_json = json.dumps(
        {
            "holding": {
                "id": holding_company.id,
                "code": holding_company.code,
                "name": holding_company.name,
                "short_name": holding_company.short_name or holding_company.name,
            },
            "selected_company_code": selected_company_code,
            "companies": tree_companies_payload,
            "units": tree_units_payload,
        },
        ensure_ascii=False,
    )

    can_manage = PermissionService.user_has_permission(request.user, "ORG_MANAGE")

    return render(
        request,
        "organization/org_tree.html",
        {
            "holding_company": holding_company,
            "west_delta": west_delta,
            "subsidiaries": subsidiaries,
            "companies": subsidiaries,
            "selected_company": selected_company,
            "current_company": selected_company,
            "selected_company_code": selected_company_code,
            "sectors": sectors,
            "unit_types": unit_types,
            "all_units": all_units,
            "visible_units": visible_units,
            "employees": employees,
            "can_manage": can_manage,
            "org_tree_payload_json": org_tree_payload_json,
        },
    )


def _parse_json_or_post(request):
    if request.content_type and "application/json" in request.content_type:
        try:
            return json.loads(request.body.decode("utf-8") or "{}")
        except Exception:
            return {}
    return request.POST


@login_required
@require_POST
def move_unit_view(request):
    """نقل وحدة تنظيمية (بالسحب والإفلات أو القائمة) إلى وحدة أب جديدة مع منع الحلقات الدائرية."""
    if not PermissionService.user_has_permission(request.user, "ORG_MANAGE"):
        return JsonResponse({"ok": False, "error": "ليس لديك صلاحية تعديل الهيكل التنظيمي."}, status=403)

    data = _parse_json_or_post(request)
    unit_id = str(data.get("unit_id") or "").strip()
    unit_code = str(data.get("unit_code") or "").strip()
    new_parent_id = str(data.get("new_parent_id") or "").strip()
    new_parent_code = str(data.get("new_parent_code") or "").strip()

    unit = (
        OrgUnit.objects.select_related("unit_type", "sector__company").filter(id=int(unit_id), is_active=True).first()
        if unit_id.isdigit()
        else OrgUnit.objects.select_related("unit_type", "sector__company").filter(code=unit_code, is_active=True).first()
    )
    new_parent = (
        OrgUnit.objects.select_related("unit_type", "sector__company").filter(id=int(new_parent_id), is_active=True).first()
        if new_parent_id.isdigit()
        else OrgUnit.objects.select_related("unit_type", "sector__company").filter(code=new_parent_code, is_active=True).first()
    )

    if not unit or not new_parent:
        return JsonResponse({"ok": False, "error": "الوحدة التنظيمية أو الوحدة الهدف غير موجودة."}, status=404)

    if _infer_unit_level(unit) == "L1" or unit.parent_id is None:
        return JsonResponse({"ok": False, "error": "لا يمكن نقل قمة الهيكل التنظيمي (L1)."}, status=400)

    if unit.id == new_parent.id:
        return JsonResponse({"ok": False, "error": "لا يمكن نقل الوحدة التنظيمية إلى نفسها."}, status=400)

    if unit.is_ancestor_of(new_parent):
        return JsonResponse({"ok": False, "error": "لا يمكن نقل وحدة تنظيمية إلى إحدى الوحدات الفرعية التابعة لها."}, status=400)

    old_parent_name = unit.parent.name if unit.parent else "—"
    with transaction.atomic():
        unit.parent = new_parent
        target_sector = new_parent.sector
        update_fields = ["parent"]
        if target_sector and unit.sector_id != target_sector.id:
            unit.sector = target_sector
            update_fields.append("sector")
        unit.save(update_fields=update_fields)

        if target_sector:
            descendant_ids = unit.get_descendant_ids() - {unit.id}
            if descendant_ids:
                OrgUnit.objects.filter(id__in=descendant_ids).update(sector=target_sector)

        AuditService.log_audit(
            actor=request.user,
            action="ORG_UNIT_MOVED",
            model_name="OrgUnit",
            object_id=unit.id,
            before_state={"parent": old_parent_name},
            after_state={"parent": new_parent.name, "sector": unit.sector.name if unit.sector else ""},
        )

    return JsonResponse(
        {
            "ok": True,
            "message": f"تم نقل «{unit.name}» لتصبح تابعة لـ «{new_parent.name}» بنجاح.",
            "unit_id": unit.id,
            "new_parent_id": new_parent.id,
        }
    )


@login_required
@require_POST
def move_user_view(request):
    """نقل موظف / مستخدم بالسحب والإفلات إلى وحدة تنظيمية أخرى مع تحديث سجل التنقلات."""
    if not PermissionService.user_has_permission(request.user, "ORG_MANAGE"):
        return JsonResponse({"ok": False, "error": "ليس لديك صلاحية نقل المستخدمين داخل الهيكل التنظيمي."}, status=403)

    data = _parse_json_or_post(request)
    employee_id = str(data.get("employee_id") or "").strip()
    user_id = str(data.get("user_id") or "").strip()
    username = str(data.get("username") or "").strip()
    target_unit_id = str(data.get("target_unit_id") or "").strip()
    target_unit_code = str(data.get("target_unit_code") or "").strip()

    target_unit = (
        OrgUnit.objects.select_related("sector").filter(id=int(target_unit_id), is_active=True).first()
        if target_unit_id.isdigit()
        else OrgUnit.objects.select_related("sector").filter(code=target_unit_code, is_active=True).first()
    )
    if not target_unit:
        return JsonResponse({"ok": False, "error": "الوحدة التنظيمية الهدف غير موجودة."}, status=404)

    employee = None
    if employee_id.isdigit():
        employee = Employee.objects.select_related("current_unit", "user_account").filter(id=int(employee_id), is_active=True).first()
    elif user_id.isdigit():
        user_obj = User.objects.select_related("employee__current_unit").filter(id=int(user_id), is_active=True).first()
        employee = user_obj.employee if user_obj else None
    elif username:
        user_obj = User.objects.select_related("employee__current_unit").filter(username=username, is_active=True).first()
        employee = user_obj.employee if user_obj else Employee.objects.filter(employee_number=username, is_active=True).first()

    if not employee:
        return JsonResponse({"ok": False, "error": "سجل الموظف/المستخدم غير موجود أو غير مرتبط بوحدة."}, status=404)

    if employee.current_unit_id == target_unit.id:
        return JsonResponse({"ok": True, "message": "الموظف موجود بالفعل في هذه الوحدة."})

    old_unit_name = employee.current_unit.name if employee.current_unit else "—"
    today = timezone.localdate()
    with transaction.atomic():
        PositionAssignment.objects.filter(employee=employee, is_current=True).update(
            is_current=False,
            end_date=today,
        )
        employee.current_unit_id = target_unit.id
        employee.save(update_fields=["current_unit"])
        PositionAssignment.objects.create(
            employee=employee,
            org_unit=target_unit,
            position_title=employee.job_title or "موظف",
            start_date=today,
            is_current=True,
            notes=f"نقل تنظيمي من «{old_unit_name}» إلى «{target_unit.name}»",
        )
        AuditService.log_audit(
            actor=request.user,
            action="USER_UNIT_MOVED",
            model_name="Employee",
            object_id=employee.id,
            before_state={"unit": old_unit_name},
            after_state={"unit": target_unit.name},
        )

    return JsonResponse(
        {
            "ok": True,
            "message": f"تم نقل «{employee.full_name}» إلى «{target_unit.name}» بنجاح.",
            "employee_id": employee.id,
            "target_unit_id": target_unit.id,
        }
    )
