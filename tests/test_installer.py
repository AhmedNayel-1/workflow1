# -*- coding: utf-8 -*-
"""
اختبارات حقيقية لبنية التثبيت (install.bat / run_server.bat / scripts/install_helper.py).
تعمل هذه الاختبارات مباشرة بمكتبة Python القياسية (unittest) ولا تعتمد على بيانات وهمية:
- فحص صيغة Windows Batch الفعلية على القرص (CRLF بدون BOM، صحة التسميات goto/call،
  خلو الكتل القوسية من ::، واقتباس جميع المسارات المحتملة للمسافات والرموز والعربية).
- تشغيل فعلي لأداة scripts/install_helper.py على مسارات عربية تحتوي مسافات ورموز،
  بما يشمل تقييم الأولويات، استبعاد WindowsApps والبيئات الافتراضية venv، محاكاة
  مخرجات py -0p و reg query بلغات مختلفة، وفحص wheelhouse و check-venv و check-port.
"""
import importlib.util
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


import ast

PROJECT_DIR = Path(__file__).resolve().parent.parent
HELPER_PATH = PROJECT_DIR / "scripts" / "install_helper.py"
BAT_FILES = [
    PROJECT_DIR / "install.bat",
    PROJECT_DIR / "install_offline.bat",
    PROJECT_DIR / "run_server.bat",
    PROJECT_DIR / "scripts" / "backup.bat",
    PROJECT_DIR / "scripts" / "restore.bat",
]


class BatchFilesIntegrityTests(unittest.TestCase):
    def test_all_batch_files_are_strict_crlf_without_bom(self):
        for bat in BAT_FILES:
            self.assertTrue(bat.is_file(), f"Missing batch file: {bat}")
            raw = bat.read_bytes()
            self.assertFalse(
                raw.startswith(b"\xef\xbb\xbf"),
                f"{bat.name} must NOT contain UTF-8 BOM (breaks @echo off in cmd.exe)",
            )
            self.assertIn(b"\r\n", raw, f"{bat.name} must use CRLF line endings")
            lf_only = raw.replace(b"\r\n", b"").count(b"\n")
            cr_only = raw.replace(b"\r\n", b"").count(b"\r")
            self.assertEqual(lf_only, 0, f"{bat.name} contains {lf_only} standalone LF bytes")
            self.assertEqual(cr_only, 0, f"{bat.name} contains {cr_only} standalone CR bytes")
            text = raw.decode("utf-8")
            if bat.name != "install.bat":
                self.assertIn("chcp 65001", text)

    def test_batch_labels_blocks_and_safety_rules(self):
        quoted_path_vars = (
            "%PROJECT_DIR%",
            "%HELPER%",
            "%VENV_PY%",
            "%BEST_PY%",
            "%RAW_CAND%",
            "%DIR_CAND%",
            "%SEL_OUT%",
        )

        for bat in BAT_FILES:
            text = bat.read_text(encoding="utf-8")
            lines = text.splitlines()

            defined_labels = set()
            referenced_labels = []
            paren_depth = 0

            for idx, line in enumerate(lines, start=1):
                stripped = line.strip()
                if stripped.startswith(":"):
                    if stripped.startswith("::"):
                        self.assertEqual(
                            paren_depth,
                            0,
                            f"{bat.name}:{idx} uses '::' inside parenthesized block",
                        )
                    else:
                        lbl = stripped[1:].split()[0].lower()
                        defined_labels.add(lbl)
                    continue

                if re.match(r"^rem(\s|$)", stripped, re.IGNORECASE):
                    continue

                for m in re.finditer(r"\b(?:goto|call)\s+:([A-Za-z0-9_]+)", line, re.IGNORECASE):
                    referenced_labels.append((idx, m.group(1).lower()))

                # تجاهل متغيرات المسار فقط إذا وردت غير محاطة باقتباس مزدوج
                for var in quoted_path_vars:
                    pos = 0
                    while True:
                        found = line.find(var, pos)
                        if found == -1:
                            break
                        quotes_before = line[:found].count('"') - line[:found].count('\\"')
                        self.assertEqual(
                            quotes_before % 2,
                            1,
                            f"{bat.name}:{idx} has unquoted path variable {var}: {line}",
                        )
                        pos = found + len(var)

                # ضمان عدم تمرير نصوص عربية داخل python -c
                if " -c " in line:
                    after_c = line.split(" -c ", 1)[1]
                    has_non_ascii = any(ord(ch) > 127 for ch in after_c)
                    self.assertFalse(
                        has_non_ascii,
                        f"{bat.name}:{idx} passes non-ASCII inside -c command line: {line}",
                    )

                # حساب عمق الأقواس التقريبي خارج علامات التنصيص مع تجاهل ^( و ^)
                in_quote = False
                i = 0
                while i < len(line):
                    ch = line[i]
                    if ch == "^" and not in_quote:
                        i += 2
                        continue
                    if ch == '"':
                        in_quote = not in_quote
                    elif not in_quote:
                        if ch == "(":
                            paren_depth += 1
                        elif ch == ")" and paren_depth > 0:
                            paren_depth -= 1
                    i += 1

            for idx, lbl in referenced_labels:
                self.assertIn(
                    lbl,
                    defined_labels,
                    f"{bat.name}:{idx} jumps/calls undefined label :{lbl}",
                )

    def test_install_offline_and_run_server_required_directives(self):
        install_txt = (PROJECT_DIR / "install.bat").read_text(encoding="utf-8")
        self.assertNotIn("Astral", install_txt)
        for token in ("py -%%V", "python -c", "-m venv", "-m pip install -r", "migrate --check", "migrate --noinput", "check-port 127.0.0.1", "runserver 127.0.0.1:%SERVER_PORT%", "pause"):
            self.assertIn(token, install_txt, f"Missing in install.bat: {token}")
        # لا يجوز أن يحذف التثبيت قاعدة البيانات أو يعيد تحميل البيانات التجريبية تلقائياً فوق قاعدة موجودة
        for forbidden in ("del ", "flush", "erase ", "rmdir"):
            self.assertNotIn(forbidden, install_txt.lower())
        self.assertIn("if defined HAD_DB goto :db_ready", install_txt)

        offline_txt = (PROJECT_DIR / "install_offline.bat").read_text(encoding="utf-8")
        for token in (
            'set "PYTHONHOME="',
            'set "PYTHONPATH="',
            'set "VIRTUAL_ENV="',
            'set "PIP_REQUIRE_VIRTUALENV="',
            'set "PIP_NO_INDEX=1"',
            "check-wheelhouse",
            "--no-index --find-links=",
            '--exclude-dir "%PROJECT_DIR%venv"',
            "makemigrations --noinput",
            "migrate --noinput",
            "seed_demo_data",
            "ensure-superuser",
            "collectstatic --noinput",
            '"%VENV_PY%" "%PROJECT_DIR%manage.py" check',
        ):
            self.assertIn(token, offline_txt, f"Missing required directive in install_offline.bat: {token}")
        self.assertNotIn("pip install --upgrade pip", offline_txt)

        run_txt = (PROJECT_DIR / "run_server.bat").read_text(encoding="utf-8")
        for token in (
            'set "PYTHONHOME="',
            'set "PYTHONPATH="',
            "migrate --check",
            "check-port 127.0.0.1 %SERVER_PORT%",
            "runserver 127.0.0.1:%SERVER_PORT%",
        ):
            self.assertIn(token, run_txt, f"Missing required directive in run_server.bat: {token}")

    def test_no_read_only_model_property_assignments_in_views(self):
        readonly_props = {
            "is_overdue",
            "overdue_days",
            "file_extension",
            "preview_kind",
            "is_for_info_only",
            "current_unit",
            "current_sector",
        }
        violations = []
        for py_file in sorted(PROJECT_DIR.rglob("*.py")):
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Attribute) and target.attr in readonly_props:
                            violations.append(f"{py_file.relative_to(PROJECT_DIR)}:{node.lineno}:{target.attr}")
        self.assertEqual(violations, [], f"Found invalid assignments to read-only @property: {violations}")


class InstallHelperExecutionTests(unittest.TestCase):
    def setUp(self):
        self._tmp_root = Path(tempfile.mkdtemp(prefix="اختبار المثبت (x86) & "))
        spec = importlib.util.spec_from_file_location("install_helper", str(HELPER_PATH))
        self.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.helper)

    def tearDown(self):
        shutil.rmtree(self._tmp_root, ignore_errors=True)

    def _make_fake_python(self, rel_path: str, probe_line: str) -> Path:
        exe = self._tmp_root / rel_path
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_text(
            f"#!/bin/sh\nprintf '%s\\n' '{probe_line}'\nexit 0\n",
            encoding="utf-8",
        )
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return exe

    def test_probe_current_python_via_subprocess(self):
        proc = subprocess.run(
            [sys.executable, str(HELPER_PATH), "probe"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        parts = proc.stdout.strip().split("|")
        self.assertEqual(len(parts), 3)
        score, ver, reason = int(parts[0]), parts[1], parts[2]
        self.assertTrue(ver.startswith(f"{sys.version_info.major}.{sys.version_info.minor}."))

        has_pip = (
            importlib.util.find_spec("ensurepip") is not None
            or importlib.util.find_spec("pip") is not None
        )
        if has_pip:
            self.assertGreater(score, 0)
            self.assertEqual(reason, "OK")
        else:
            # في بيئة لينكس مجردة بدون ensurepip/pip يرفض probe البيئة بدقة
            self.assertEqual(score, 0)
            self.assertEqual(reason, "MISSING:ensurepip/pip")

            # وعند توفر pip في بيئة متوافقة يرجع OK مع أولوية النسخة الصحيحة
            extra_site = self._tmp_root / "site_with_pip"
            (extra_site / "pip").mkdir(parents=True)
            (extra_site / "pip" / "__init__.py").write_text("", encoding="utf-8")
            env = os.environ.copy()
            env["PYTHONPATH"] = str(extra_site)
            proc2 = subprocess.run(
                [sys.executable, str(HELPER_PATH), "probe"],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            )
            score2, _, reason2 = proc2.stdout.strip().split("|")
            self.assertGreater(int(score2), 0)
            self.assertEqual(reason2, "OK")

    def test_select_prioritizes_311_and_filters_incompatible_or_excluded(self):
        # مسارات عربية ومسافات وأقواس ورمز &
        excluded_venv = self._tmp_root / "مسار المشروع & التجريبي" / "venv"
        py_in_venv = self._make_fake_python(
            "مسار المشروع & التجريبي/venv/Scripts/python.exe",
            "410|3.11.9|OK",
        )
        py_winapps = self._make_fake_python(
            "LocalAppData/Microsoft/WindowsApps/python.exe",
            "410|3.11.9|OK",
        )
        py_old = self._make_fake_python("Python38/python.exe", "0|3.8.18|OLD_LT_310")
        py_new = self._make_fake_python("Python314/python.exe", "0|3.14.0|NEW_GT_313")
        py_is_venv = self._make_fake_python("OtherVenv/python.exe", "0|3.11.8|IS_VENV")
        py_312 = self._make_fake_python("Program Files (x86)/Python 312/python.exe", "360|3.12.6|OK")
        py_311 = self._make_fake_python("مجلد بايثون & أدوات/Python311/python.exe", "410|3.11.9|OK")

        # محاكاة مخرجات py -0p و reg query بلغات مختلفة (English Default + French Par défaut)
        cand_file = self._tmp_root / "candidates.txt"
        out_file = self._tmp_root / "selected.txt"
        cand_file.write_text(
            "\n".join(
                [
                    f" -V:3.11 *        {py_in_venv}",
                    str(py_winapps),
                    str(py_old),
                    str(py_new),
                    str(py_is_venv),
                    f"    ExecutablePath    REG_SZ    {py_312}",
                    f'    (Par défaut)    REG_SZ    "{py_311.parent}"',
                    str(py_311),  # مكرر لاختبار إزالة التكرار
                ]
            ),
            encoding="utf-8",
        )

        # تشغيل extract_candidate_paths مباشرة مع محاكاة مسارات Unix/Windows مختلطة
        extracted = self.helper.extract_candidate_paths(
            cand_file,
            extra_paths=[
                str(py_in_venv),
                str(py_winapps),
                str(py_old),
                str(py_new),
                str(py_is_venv),
                str(py_312),
                str(py_311),
                str(py_311),
            ],
            exclude_dirs=[str(excluded_venv)],
        )
        self.assertNotIn(str(py_in_venv), extracted)
        self.assertNotIn(str(py_winapps), extracted)
        self.assertEqual(extracted.count(str(py_311)), 1)

        # اختبار subprocess select عبر ملف نصي يضم المرشحين الصريحين
        direct_cand_file = self._tmp_root / "direct_candidates.txt"
        direct_cand_file.write_text("\n".join(extracted), encoding="utf-8")
        proc = subprocess.run(
            [
                sys.executable,
                str(HELPER_PATH),
                "select",
                str(direct_cand_file),
                str(out_file),
                "--exclude-dir",
                str(excluded_venv),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        selected = out_file.read_text(encoding="utf-8").strip()
        self.assertEqual(selected, f"{py_311}|3.11.9")

    def test_preflight_on_arabic_space_path(self):
        proj_dir = self._tmp_root / "مشروع السكرتارية & الأرشفة"
        proj_dir.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [sys.executable, str(HELPER_PATH), "preflight", str(proj_dir)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_real_venv_is_rejected_by_probe_and_checked_by_check_venv(self):
        venv_dir = self._tmp_root / "مسار عربي مع مسافات" / "venv"
        subprocess.run(
            [sys.executable, "-m", "venv", "--without-pip", str(venv_dir)],
            check=True,
            capture_output=True,
        )
        venv_py = venv_dir / "bin" / "python"
        self.assertTrue(venv_py.is_file())

        # مفسّر venv نفسه يجب أن يرجع IS_VENV كي لا يُختار لإعادة بناء venv
        probe_proc = subprocess.run(
            [str(venv_py), str(HELPER_PATH), "probe"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        score, _, reason = probe_proc.stdout.strip().split("|")
        self.assertEqual(score, "0")
        self.assertEqual(reason, "IS_VENV")

        # check-venv يقبل venv بلا pip إذا كان ensurepip متاحاً (يصلحه المثبّت بالخطوة 2)،
        # ويرفضه إذا لم يتوفر لا pip ولا ensurepip؛ التوقع يُحسب من مفسّر venv نفسه.
        avail = subprocess.run(
            [str(venv_py), "-c",
             "import importlib.util as u; print(int(u.find_spec('pip') is not None or u.find_spec('ensurepip') is not None))"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        check_missing_pip = subprocess.run(
            [sys.executable, str(HELPER_PATH), "check-venv", str(venv_dir)],
            capture_output=True,
        )
        self.assertEqual(check_missing_pip.returncode, 0 if avail == "1" else 1)

        # venv تالف (بلا pyvenv.cfg) يُرفض دائماً
        cfg = venv_dir / "pyvenv.cfg"
        cfg_text = cfg.read_text(encoding="utf-8")
        cfg.unlink()
        check_no_cfg = subprocess.run(
            [sys.executable, str(HELPER_PATH), "check-venv", str(venv_dir)],
            capture_output=True,
        )
        self.assertEqual(check_no_cfg.returncode, 1)
        cfg.write_text(cfg_text, encoding="utf-8")

        # بعد محاكاة توفر pip داخل site-packages ينجح check-venv، وإذا نُقل لمسار آخر يفشل
        site_pkgs = next(venv_dir.glob("lib/python*/site-packages"))
        (site_pkgs / "pip").mkdir()
        (site_pkgs / "pip" / "__init__.py").write_text("", encoding="utf-8")

        check_ok = subprocess.run(
            [sys.executable, str(HELPER_PATH), "check-venv", str(venv_dir)],
            capture_output=True,
        )
        self.assertEqual(check_ok.returncode, 0)

        relocated_dir = self._tmp_root / "مسار منقول آخر" / "venv"
        relocated_dir.parent.mkdir(parents=True, exist_ok=True)
        venv_dir.rename(relocated_dir)
        check_moved = subprocess.run(
            [sys.executable, str(HELPER_PATH), "check-venv", str(relocated_dir)],
            capture_output=True,
        )
        self.assertEqual(check_moved.returncode, 1)

    def test_check_wheelhouse_validation(self):
        wh_dir = self._tmp_root / "wheelhouse"
        wh_dir.mkdir()
        self.assertEqual(
            subprocess.run([sys.executable, str(HELPER_PATH), "check-wheelhouse", str(wh_dir)]).returncode,
            1,
        )
        (wh_dir / "openpyxl-3.1.5-py2.py3-none-any.whl").write_bytes(b"pkg")
        self.assertEqual(
            subprocess.run([sys.executable, str(HELPER_PATH), "check-wheelhouse", str(wh_dir)]).returncode,
            1,
        )
        (wh_dir / "Django-5.1.3-py3-none-any.whl").write_bytes(b"django")
        self.assertEqual(
            subprocess.run([sys.executable, str(HELPER_PATH), "check-wheelhouse", str(wh_dir)]).returncode,
            0,
        )

    def test_check_port_busy_and_free(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            port = srv.getsockname()[1]
            busy_rc = subprocess.run(
                [sys.executable, str(HELPER_PATH), "check-port", "127.0.0.1", str(port)]
            ).returncode
            self.assertEqual(busy_rc, 1)

        free_rc = subprocess.run(
            [sys.executable, str(HELPER_PATH), "check-port", "127.0.0.1", str(port)]
        ).returncode
        self.assertEqual(free_rc, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
