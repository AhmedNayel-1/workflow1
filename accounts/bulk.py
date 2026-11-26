"""استيراد مستخدمين دفعة واحدة (CSV / Excel) فوق منطق إنشاء المستخدم الحالي ونفس صلاحياته."""
import csv
import io
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from organization.models import OrgUnit
from .models import Role, User
from .services import PermissionService
from .views import _get_client_ip, create_user_account

MAX_ROWS = 500
HEADERS = ["الاسم الكامل", "اسم المستخدم", "كلمة المرور", "المسمى الوظيفي", "الوحدة (الكود أو الاسم)", "الدور (الكود أو الاسم)", "الرقم الوظيفي", "سكرتارية (نعم/لا)"]
SAMPLE = [
    ["أحمد محمد علي", "ahmed.ali", "ChangeMe#1", "مدير الإدارة", "UNIT_PERSONNEL_GD", "", "EMP-1001", "لا"],
    ["منى حسن", "mona.hassan", "ChangeMe#2", "سكرتير", "قسم التنقلات", "", "", "نعم"],
]
FORBIDDEN = {"SYSTEM_ADMIN", "CHAIRMAN", "SECTOR_DIR_ADMIN"}


def _guard(user):
    if not PermissionService.can_manage_users(user):
        raise PermissionDenied("الاستيراد الجماعي مخصص لمدير النظام أو مسؤول القطاع/الإدارة العامة المفوض.")


def _norm(v):
    return str(v if v is not None else "").strip()


def _read_rows(f):
    name = (f.name or "").lower()
    data = f.read()
    if name.endswith((".xlsx", ".xlsm")):
        import openpyxl
        ws = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True).active
        rows = [[_norm(c) for c in r] for r in ws.iter_rows(values_only=True)]
    else:
        text = data.decode("utf-8-sig", errors="replace")
        try:
            dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = [[_norm(c) for c in r] for r in csv.reader(io.StringIO(text), dialect)]
    rows = [r for r in rows if any(r)]
    if rows and rows[0] and ("اسم المستخدم" in rows[0][1:2] or "الاسم الكامل" in rows[0][:1] or rows[0][0].lower() in ("full_name", "name")):
        rows = rows[1:]
    return rows


def _validate(actor, rows):
    is_full = bool(actor.is_superuser or actor.is_system_admin)
    units = list(OrgUnit.objects.filter(is_active=True).select_related("sector"))
    by_code = {u.code.lower(): u for u in units}
    by_name = {}
    for u in units:
        by_name.setdefault(u.name.strip(), []).append(u)
    roles = list(Role.objects.all())
    r_code = {r.code.lower(): r for r in roles}
    r_name = {r.name.strip(): r for r in roles}
    existing = set(User.objects.values_list("username", flat=True))
    seen = set()
    out = []
    for i, r in enumerate(rows, start=2):
        r = (r + [""] * 8)[:8]
        full_name, username, password, job, unit_s, role_s, emp_no, sec_s = r
        errs = []
        if not full_name:
            errs.append("الاسم الكامل مطلوب")
        if not username:
            errs.append("اسم المستخدم مطلوب")
        elif username in existing:
            errs.append("اسم المستخدم مسجل بالفعل")
        elif username in seen:
            errs.append("اسم المستخدم مكرر داخل الملف")
        if not password:
            errs.append("كلمة المرور مطلوبة")
        elif len(password) < 3:
            errs.append("كلمة المرور أقل من 3 أحرف")
        unit = None
        if not unit_s:
            errs.append("الوحدة مطلوبة")
        else:
            unit = by_code.get(unit_s.lower())
            if unit is None:
                m = by_name.get(unit_s.strip(), [])
                if len(m) == 1:
                    unit = m[0]
                elif len(m) > 1:
                    errs.append("اسم الوحدة مكرر، استخدم الكود")
                else:
                    errs.append("وحدة غير معروفة")
        role = None
        if role_s:
            role = r_code.get(role_s.lower()) or r_name.get(role_s.strip())
            if role is None:
                errs.append("دور غير معروف")
            elif not is_full and role.code in FORBIDDEN:
                errs.append("لا يمكنك إسناد هذا الدور")
        if unit is not None and not is_full and not PermissionService.can_manage_target_user(
            actor, target_sector_id=unit.sector_id, target_unit_id=unit.id
        ):
            errs.append("الوحدة خارج نطاقك")
        if username:
            seen.add(username)
        out.append({
            "line": i, "full_name": full_name, "username": username, "password": password, "job": job,
            "unit": unit.name if unit else unit_s, "unit_id": unit.id if unit else None,
            "role": role.name if role else role_s, "role_id": role.id if role else None,
            "emp_no": emp_no, "secretariat": sec_s.strip() in ("نعم", "yes", "Yes", "1", "true", "True"),
            "errors": errs,
        })
    return out


@login_required
@require_http_methods(["GET", "POST"])
def bulk_users(request):
    _guard(request.user)
    ctx = {"max_rows": MAX_ROWS}
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "preview":
            f = request.FILES.get("file")
            if not f:
                messages.error(request, "اختر ملفاً أولاً.")
                return redirect("accounts:bulk_users")
            try:
                rows = _read_rows(f)
            except Exception:
                messages.error(request, "تعذّرت قراءة الملف. استخدم القالب (CSV أو xlsx).")
                return redirect("accounts:bulk_users")
            if not rows:
                messages.error(request, "الملف فارغ.")
                return redirect("accounts:bulk_users")
            if len(rows) > MAX_ROWS:
                messages.error(request, f"الحد الأقصى {MAX_ROWS} صفاً في الملف الواحد.")
                return redirect("accounts:bulk_users")
            checked = _validate(request.user, rows)
            token = uuid.uuid4().hex
            request.session["bulk_users"] = {"token": token, "rows": [r for r in checked if not r["errors"]]}
            ctx.update(preview=checked, token=token, ok_count=sum(1 for r in checked if not r["errors"]), bad_count=sum(1 for r in checked if r["errors"]))
        elif action == "confirm":
            data = request.session.get("bulk_users")
            if not data or data.get("token") != request.POST.get("token"):
                messages.error(request, "انتهت صلاحية المعاينة. ارفع الملف مرة أخرى.")
                return redirect("accounts:bulk_users")
            request.session.pop("bulk_users", None)
            results = []
            # إعادة التحقق قبل الإنشاء (قد تتغير البيانات بين المعاينة والتأكيد)
            existing = set(User.objects.values_list("username", flat=True))
            for r in data["rows"]:
                if r["username"] in existing:
                    results.append({**r, "status": "تخطّي: اسم المستخدم مسجل بالفعل"})
                    continue
                try:
                    unit = OrgUnit.objects.get(id=r["unit_id"])
                    role = Role.objects.get(id=r["role_id"]) if r["role_id"] else None
                    create_user_account(
                        request.user, username=r["username"], password=r["password"], full_name=r["full_name"],
                        job_title=r["job"], emp_no=r["emp_no"], unit_obj=unit, role_obj=role, sector_obj=unit.sector,
                        is_secretariat=r["secretariat"], is_active=True, ip=_get_client_ip(request),
                    )
                    existing.add(r["username"])
                    results.append({**r, "status": "تم الإنشاء"})
                except Exception as exc:  # noqa: BLE001
                    results.append({**r, "status": "فشل: " + (str(exc) or exc.__class__.__name__)})
            for r in results:
                r["password"] = ""
            ctx.update(results=results, created=sum(1 for r in results if r["status"] == "تم الإنشاء"), failed=sum(1 for r in results if r["status"] != "تم الإنشاء"))
    return render(request, "accounts/bulk_users.html", ctx)


@login_required
def bulk_template(request, fmt):
    _guard(request.user)
    if fmt == "xlsx":
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.sheet_view.rightToLeft = True
        ws.append(HEADERS)
        for r in SAMPLE:
            ws.append(r)
        for col, w in zip("ABCDEFGH", (22, 18, 16, 20, 28, 24, 14, 16)):
            ws.column_dimensions[col].width = w
        buf = io.BytesIO()
        wb.save(buf)
        resp = HttpResponse(buf.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = 'attachment; filename="users_template.xlsx"'
        return resp
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HEADERS)
    w.writerows(SAMPLE)
    resp = HttpResponse("\ufeff" + buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="users_template.csv"'
    return resp
