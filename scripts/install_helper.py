# -*- coding: utf-8 -*-
"""
مساعد التثبيت وفحص البيئة متعدد الأجهزة لنظام Windows / Linux.
مكتوب بمكتبة Python القياسية فقط لضمان عمله على أي إصدار Python 3 عند الاكتشاف الأولي،
دون الحاجة إلى حزم خارجية أو معالجة نصوص عربية هشة داخل cmd.exe.
"""
import importlib.util
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path


MIN_PYTHON = (3, 10)
MAX_PYTHON = (3, 15)
PREFERRED_SCORES = {
    (3, 11): 400,
    (3, 12): 350,
    (3, 10): 250,
    (3, 13): 150,
    (3, 14): 100,
    (3, 15): 50,
}


def _is_inside_venv() -> bool:
    """التحقق مما إذا كان المفسّر يعمل داخل بيئة افتراضية (venv/virtualenv) وليس تثبيتاً أساسياً."""
    base_prefix = getattr(sys, "base_prefix", sys.prefix)
    real_prefix = getattr(sys, "real_prefix", None)
    if real_prefix is not None:
        return True
    try:
        return os.path.normcase(os.path.realpath(sys.prefix)) != os.path.normcase(os.path.realpath(base_prefix))
    except OSError:
        return sys.prefix != base_prefix


def probe_current_python():
    """فحص نسخة Python التي تشغل هذا السكربت وإرجاع درجة ملاءمتها مع Django 5.1."""
    major_minor = sys.version_info[:2]
    ver_str = "{}.{}.{}".format(*sys.version_info[:3])

    required_mods = ("venv", "sqlite3", "ssl", "ctypes", "zlib")
    missing = [m for m in required_mods if importlib.util.find_spec(m) is None]

    # التحقق من توفر pip أو ensurepip لتثبيت المكتبات داخل venv
    has_pip_or_ensurepip = (
        importlib.util.find_spec("ensurepip") is not None
        or importlib.util.find_spec("pip") is not None
    )
    if not has_pip_or_ensurepip:
        missing.append("ensurepip/pip")

    # استبعاد بيئة Windows Store الوهمية إن وجدت
    exe_lower = (sys.executable or "").lower()
    if "windowsapps" in exe_lower:
        return 0, ver_str, "WINDOWS_STORE_ALIAS"

    # استبعاد البيئات الافتراضية حتى لا يُنشأ venv من venv أو يُحذف المفسّر أثناء إعادة البناء
    if _is_inside_venv():
        return 0, ver_str, "IS_VENV"

    if major_minor < MIN_PYTHON:
        return 0, ver_str, "OLD_LT_310"
    if major_minor > MAX_PYTHON:
        return 0, ver_str, "NEW_GT_313"
    if missing:
        return 0, ver_str, "MISSING:" + ",".join(missing)

    score = PREFERRED_SCORES.get(major_minor, 0)
    if score > 0 and sys.maxsize > 2**32:
        score += 10  # تفضيل 64-bit عند تساوي الإصدارات
    return score, ver_str, "OK"


def _norm_path_for_compare(path_obj: Path) -> str:
    try:
        return os.path.normcase(str(path_obj.resolve()))
    except OSError:
        return os.path.normcase(os.path.abspath(str(path_obj)))


def _is_under_dir(candidate: Path, excluded_dir: Path) -> bool:
    cand_norm = _norm_path_for_compare(candidate)
    excl_norm = _norm_path_for_compare(excluded_dir).rstrip("\\/")
    return cand_norm == excl_norm or cand_norm.startswith(excl_norm + os.sep) or cand_norm.startswith(excl_norm + "/")


def extract_candidate_paths(candidates_file: Path, extra_paths=None, exclude_dirs=None):
    """استخراج وتوحيد المسارات المرشحة من ملف البحث ومن الريجستري ومخرجات py -0p."""
    raw_lines = []
    if candidates_file and candidates_file.is_file():
        raw_lines.extend(
            candidates_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        )
    if extra_paths:
        raw_lines.extend(extra_paths)

    excluded = [Path(d) for d in (exclude_dirs or []) if str(d).strip()]
    seen_real = set()
    cleaned = []

    def add_path(p_str: str):
        p_str = (p_str or "").strip().strip('"').strip("'")
        if not p_str:
            return
        if "windowsapps" in p_str.lower():
            return
        p = Path(p_str)
        if not p.is_file():
            return
        for ex in excluded:
            if _is_under_dir(p, ex):
                return
        resolved = _norm_path_for_compare(p).lower()
        if resolved in seen_real:
            return
        seen_real.add(resolved)
        cleaned.append(str(p))

    # فحص سطر بسطر (يشمل مسارات مباشرة، أو مخرجات py -0p، أو مخرجات reg query)
    for line in raw_lines:
        s = line.strip()
        if not s:
            continue
        # مثال py -0p: " -V:3.11 *        C:\Python311\python.exe"
        # أو مخرجات reg query: "    ExecutablePath    REG_SZ    C:\...\python.exe"
        match = re.search(r'([A-Za-z]:\\[^\r\n"*?<>|]+\\python\.exe)(?:\s|$)', s, re.IGNORECASE)
        if match:
            add_path(match.group(1))
            continue
        # مسار نسبي أو لينكس/ماك أو مسار عام ينتهي بـ python أو python3 أو python3.x
        if re.search(r'(?:^|[\\/])python(?:3(?:\.\d+)?)?(?:\.exe)?$', s, re.IGNORECASE):
            add_path(s)
            continue
        # مجلد InstallPath من الريجستري (يعمل مع أي لغة لواجهة ويندوز مثل (Default) أو (Par défaut))
        reg_dir = re.search(r'REG_(?:EXPAND_)?SZ\s+([A-Za-z]:\\[^\r\n"*?<>|]+)', s, re.IGNORECASE)
        if reg_dir:
            cand_dir = Path(reg_dir.group(1).strip().rstrip("\\/"))
            if (cand_dir / "python.exe").is_file():
                add_path(str(cand_dir / "python.exe"))

    return cleaned


def run_probe_subprocess(exe_path: str):
    """تشغيل فحص سريع لملف تنفيذي مرشح وإرجاع (score, version, reason)."""
    try:
        proc = subprocess.run(
            [exe_path, str(Path(__file__).resolve()), "probe"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=12,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0, "?", "EXEC_FAILED"

    if proc.returncode != 0:
        return 0, "?", "EXIT_" + str(proc.returncode)

    lines = [ln.strip() for ln in proc.stdout.splitlines() if "|" in ln]
    if not lines:
        return 0, "?", "BAD_OUTPUT"
    parts = lines[-1].split("|", 2)
    if len(parts) != 3:
        return 0, "?", "PARSE_ERR"
    try:
        score = int(parts[0])
    except ValueError:
        score = 0
    return score, parts[1], parts[2]


def select_best_python(candidates):
    """تقييم جميع المرشحين واختيار الأفضل توافقاً مع Django 5.1 والمكتبات."""
    best = None
    report = []
    for exe in candidates:
        score, ver, reason = run_probe_subprocess(exe)
        report.append((exe, score, ver, reason))
        if score > 0:
            if best is None or score > best["score"]:
                best = {"path": exe, "score": score, "version": ver, "reason": reason}
    return best, report


def check_existing_venv(venv_dir: Path) -> bool:
    """التحقق من أن البيئة الافتراضية الحالية سليمة غير منقولة ومتوافقة."""
    scripts_py = venv_dir / "Scripts" / "python.exe"
    if not scripts_py.is_file():
        scripts_py = venv_dir / "bin" / "python"
    if not scripts_py.is_file():
        return False

    cfg = venv_dir / "pyvenv.cfg"
    if not cfg.is_file():
        return False
    try:
        cfg_lines = cfg.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    home_dir = None
    for line in cfg_lines:
        m = re.match(r"^\s*home\s*=\s*(.+?)\s*$", line, re.IGNORECASE)
        if m:
            home_dir = Path(m.group(1).strip().strip('"'))
            break
    if not home_dir or not home_dir.is_dir():
        return False

    expected_norm = _norm_path_for_compare(venv_dir).rstrip("\\/")
    activate_bat = venv_dir / "Scripts" / "activate.bat"
    activate_sh = venv_dir / "bin" / "activate"
    for act_file in (activate_bat, activate_sh):
        if act_file.is_file():
            try:
                act_text = act_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return False
            for line in act_text.splitlines():
                rec = None
                if act_file.name.lower() == "activate.bat":
                    m_bat = re.match(
                        r'^\s*(?:@?set\s+)?"?VIRTUAL_ENV\s*=\s*"?([^"\r\n]+)"?\s*$',
                        line,
                        re.IGNORECASE,
                    )
                    if m_bat:
                        rec = m_bat.group(1).strip()
                else:
                    m_sh = re.match(
                        r"^\s*(?:export\s+)?VIRTUAL_ENV=(['\"]?)(.+?)\1\s*$",
                        line,
                    )
                    if m_sh:
                        rec = m_sh.group(2).replace("'\"'\"'", "'").strip()
                if rec and not rec.startswith("$") and not rec.startswith("%"):
                    if _norm_path_for_compare(Path(rec)).rstrip("\\/") != expected_norm:
                        return False
                    break

    code = (
        "import importlib.util, os, sys, sqlite3, ssl, zlib, ctypes; "
        "v=sys.version_info[:2]; "
        "assert (3,10)<=v<=(3,13); "
        "assert importlib.util.find_spec('pip') is not None or importlib.util.find_spec('ensurepip') is not None; "
        "exp=os.environ['TARGET_VENV']; "
        "ok = os.path.samefile(exp, sys.prefix) if hasattr(os.path, 'samefile') else (os.path.realpath(exp).lower()==os.path.realpath(sys.prefix).lower()); "
        "assert ok"
    )
    env = os.environ.copy()
    env["TARGET_VENV"] = str(venv_dir.resolve())
    try:
        res = subprocess.run(
            [str(scripts_py), "-c", code],
            env=env,
            capture_output=True,
            timeout=12,
        )
        return res.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def check_wheelhouse(wheelhouse_dir: Path) -> bool:
    """التحقق من وجود مجلد wheelhouse صالح يحتوي على حزمة Django."""
    if not wheelhouse_dir.is_dir():
        return False
    files = list(wheelhouse_dir.iterdir())
    has_pkg = any(f.is_file() and f.name.lower().endswith((".whl", ".tar.gz", ".zip")) for f in files)
    has_django = any(f.is_file() and f.name.lower().startswith("django") for f in files)
    return has_pkg and has_django


def check_environment_preflight(project_dir: Path):
    """فحص صلاحية الكتابة والمساحة الحرة (مع عدم تعطيل التثبيت لأخطاء قياس غير جوهرية)."""
    probe = project_dir / f".write_probe_{os.getpid()}.tmp"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        print(f"[خطأ] لا توجد صلاحية كتابة داخل مجلد المشروع: {project_dir}\nالسبب: {exc}", file=sys.stderr)
        return 2

    try:
        usage = shutil.disk_usage(str(project_dir))
        free_mb = usage.free // (1024 * 1024)
        if free_mb < 400:
            print(f"[خطأ] المساحة الحرة على القرص غير كافية ({free_mb} MB متاح، المطلوب 400 MB على الأقل).", file=sys.stderr)
            return 3
        print(f"    [OK] المساحة الحرة المتاحة: {free_mb} MB.")
    except OSError:
        print("    [تنبيه] تعذر قياس المساحة الحرة على القرص؛ سيتم المتابعة.")
    return 0


def ensure_superuser(project_dir: Path):
    """ضمان إنشاء/تحديث حساب Superuser التجريبي (an / 123) دون أي رموز عربية في سطر الأوامر."""
    sys.path.insert(0, str(project_dir))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django  # noqa: WPS433

    django.setup()
    from django.contrib.auth import get_user_model  # noqa: WPS433

    user_model = get_user_model()
    user_obj, _ = user_model.objects.get_or_create(
        username="an",
        defaults={
            "first_name": "م. أحمد (Superuser)",
            "job_display_title": "مسؤول النظام الرئيسي (Superuser)",
            "is_staff": True,
            "is_superuser": True,
            "is_system_admin": True,
            "is_active": True,
        },
    )
    user_obj.first_name = "م. أحمد (Superuser)"
    user_obj.job_display_title = "مسؤول النظام الرئيسي (Superuser)"
    user_obj.is_staff = True
    user_obj.is_superuser = True
    user_obj.is_system_admin = True
    user_obj.is_active = True
    user_obj.set_password("123")
    user_obj.save()
    print("[OK] حساب Superuser (an / 123) جاهز ومفعّل.")
    return 0


def check_port_available(host: str, port: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        if sock.connect_ex((host, port)) == 0:
            return 1
    return 0


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return 1

    cmd = args[0]
    if cmd == "probe":
        score, ver, reason = probe_current_python()
        print(f"{score}|{ver}|{reason}")
        return 0

    if cmd == "preflight":
        proj = Path(args[1]).resolve()
        return check_environment_preflight(proj)

    if cmd == "select":
        # select <candidates_file> <out_result_file> [--exclude-dir <dir>]...
        cand_file = Path(args[1])
        out_file = Path(args[2])
        exclude_dirs = []
        i = 3
        while i < len(args):
            if args[i] == "--exclude-dir" and i + 1 < len(args):
                exclude_dirs.append(args[i + 1])
                i += 2
            else:
                exclude_dirs.append(args[i])
                i += 1
        candidates = extract_candidate_paths(cand_file, exclude_dirs=exclude_dirs)
        best, report = select_best_python(candidates)
        for exe, score, ver, reason in report:
            if score > 0:
                print(f"    [مرشح متوافق] Python {ver} (أولوية {score}): \"{exe}\"")
            else:
                print(f"    [مستبعد] Python {ver} ({reason}): \"{exe}\"")

        if best is None:
            out_file.write_text("", encoding="utf-8")
            return 1

        # كتابة المسار والنسخة في ملف نصي UTF-8 يقرؤه cmd بسهولة
        out_file.write_text(f"{best['path']}|{best['version']}\n", encoding="utf-8")
        return 0

    if cmd == "check-venv":
        venv_dir = Path(args[1]).resolve()
        return 0 if check_existing_venv(venv_dir) else 1

    if cmd == "check-wheelhouse":
        wh_dir = Path(args[1]).resolve()
        return 0 if check_wheelhouse(wh_dir) else 1

    if cmd == "ensure-superuser":
        proj = Path(args[1]).resolve()
        return ensure_superuser(proj)

    if cmd == "check-port":
        host = args[1] if len(args) > 1 else "127.0.0.1"
        port = int(args[2]) if len(args) > 2 else 8000
        return check_port_available(host, port)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
