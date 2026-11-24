"""
نظام النسخ الاحتياطي والاستعادة الآمن لمنظومة السكرتارية والأرشفة:
- يدعم SQLite (نسخ آمن أثناء التشغيل عبر sqlite3.Connection.backup + فحص PRAGMA integrity_check)
  و SQL Server عند تفعيل DB_ENGINE=mssql (عبر sqlcmd أو pyodbc).
- ينسخ خزينة المرفقات SECURE_STORAGE_ROOT بالتزامن مع قاعدة البيانات.
- يولّد backup_manifest.json ببصمات SHA-256 لقاعدة البيانات وكل مرفق.
- يخزن النسخ خارج مجلد الكود (..\correspondence_backups افتراضياً) مع الاحتفاظ بآخر 30 نسخة.
- يشترط تأكيداً صريحاً والتحقق من البصمات قبل الاستعادة لمنع الكتابة الخاطئة أو استعادة نسخة تالفة.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent


def load_project_env(env_path: Path | None = None) -> dict[str, str]:
    """قراءة متغيرات البيئة من ملف .env ثم دمجها مع os.environ دون أي كلمات مرور ثابتة."""
    values: dict[str, str] = {}
    target = env_path or (BASE_DIR / ".env")
    if target.is_file():
        for raw_line in target.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            key = k.strip()
            val = v.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
            values[key] = os.environ.get(key, val)
    for k, v in os.environ.items():
        values[k] = v
    return values


def resolve_paths(
    *,
    base_dir: Path | None = None,
    backup_root: Path | None = None,
    vault_root: Path | None = None,
    sqlite_path: Path | None = None,
) -> dict[str, Path]:
    project_dir = Path(base_dir or BASE_DIR).resolve()
    env = load_project_env(project_dir / ".env")

    vault_cfg = env.get("SECURE_STORAGE_ROOT", "storage_vault")
    resolved_vault = Path(vault_root) if vault_root else (
        Path(vault_cfg) if Path(vault_cfg).is_absolute() else (project_dir / vault_cfg)
    )

    sqlite_cfg = env.get("SQLITE_PATH", "db.sqlite3")
    resolved_sqlite = Path(sqlite_path) if sqlite_path else (
        Path(sqlite_cfg) if Path(sqlite_cfg).is_absolute() else (project_dir / sqlite_cfg)
    )

    if backup_root:
        resolved_backup_root = Path(backup_root).resolve()
    else:
        env_bk = env.get("BACKUP_ROOT", "").strip()
        resolved_backup_root = (
            Path(env_bk).resolve()
            if env_bk
            else (project_dir.parent / "correspondence_backups").resolve()
        )

    # منع تخزين النسخ الاحتياطية داخل مجلد الكود نفسه
    try:
        resolved_backup_root.relative_to(project_dir)
        raise ValueError(
            f"لا يجوز وضع مجلد النسخ الاحتياطية داخل مجلد الكود ({resolved_backup_root}). حدد مساراً خارجياً مثل ..\\correspondence_backups."
        )
    except ValueError as exc:
        if "لا يجوز وضع" in str(exc):
            raise

    return {
        "project_dir": project_dir,
        "vault_dir": resolved_vault.resolve(),
        "sqlite_path": resolved_sqlite.resolve(),
        "backup_root": resolved_backup_root,
    }


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_vault_with_hashes(src_vault: Path, dst_vault: Path) -> list[dict[str, Any]]:
    dst_vault.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    if not src_vault.exists():
        return records
    for item in sorted(src_vault.rglob("*")):
        if item.is_file():
            rel = item.relative_to(src_vault).as_posix()
            target = dst_vault / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            records.append(
                {
                    "relative_path": rel,
                    "size": target.stat().st_size,
                    "sha256": sha256_file(target),
                }
            )
    return records


def _backup_sqlite(src_db: Path, dst_db: Path) -> None:
    if not src_db.is_file():
        raise FileNotFoundError(f"ملف قاعدة البيانات SQLite غير موجود: {src_db}")
    src_conn = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True, timeout=30.0)
    dst_conn = sqlite3.connect(str(dst_db), timeout=30.0)
    try:
        src_conn.backup(dst_conn)
        dst_conn.commit()
        check = dst_conn.execute("PRAGMA integrity_check;").fetchone()
        if not check or check[0].lower() != "ok":
            raise RuntimeError(f"فشل فحص سلامة نسخة SQLite الاحتياطية: {check}")
    finally:
        dst_conn.close()
        src_conn.close()


def _restore_sqlite(src_backup_db: Path, dst_live_db: Path) -> None:
    dst_live_db.parent.mkdir(parents=True, exist_ok=True)
    if dst_live_db.is_file():
        pre_safety = dst_live_db.with_suffix(".pre_restore.sqlite3")
        _backup_sqlite(dst_live_db, pre_safety)
    src_conn = sqlite3.connect(f"file:{src_backup_db}?mode=ro", uri=True, timeout=30.0)
    dst_conn = sqlite3.connect(str(dst_live_db), timeout=30.0)
    try:
        check = src_conn.execute("PRAGMA integrity_check;").fetchone()
        if not check or check[0].lower() != "ok":
            raise RuntimeError(f"النسخة الاحتياطية المحددة تالفة (PRAGMA integrity_check): {check}")
        src_conn.backup(dst_conn)
        dst_conn.commit()
    finally:
        dst_conn.close()
        src_conn.close()


def _run_mssql_sql(sql_statement: str, env: dict[str, str], *, use_master: bool = True) -> None:
    host = env.get("DB_HOST", "localhost")
    port = env.get("DB_PORT", "1433")
    user = env.get("DB_USER", "")
    password = env.get("DB_PASSWORD", "")
    driver = env.get("DB_ODBC_DRIVER", "ODBC Driver 17 for SQL Server")
    target_db = "master" if use_master else env.get("DB_NAME", "CorrespondenceDB")

    # استخدام sqlcmd إذا كان مثبتاً على الخادم
    sqlcmd_exe = shutil.which("sqlcmd")
    if sqlcmd_exe:
        cmd = [sqlcmd_exe, "-S", f"{host},{port}", "-d", target_db, "-b", "-Q", sql_statement]
        if user:
            cmd.extend(["-U", user, "-P", password])
        else:
            cmd.append("-E")
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            raise RuntimeError(f"فشل تنفيذ أمر SQL Server عبر sqlcmd: {res.stderr or res.stdout}")
        return

    # بديل عبر pyodbc
    try:
        import pyodbc  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "تعذر العثور على أداة sqlcmd أو مكتبة pyodbc لتنفيذ النسخ الاحتياطي/الاستعادة على SQL Server."
        ) from exc

    auth_part = f"UID={user};PWD={password};" if user else "Trusted_Connection=yes;"
    conn_str = f"DRIVER={{{driver}}};SERVER={host},{port};DATABASE={target_db};{auth_part}TrustServerCertificate=yes;"
    conn = pyodbc.connect(conn_str, autocommit=True)
    try:
        cur = conn.cursor()
        cur.execute(sql_statement)
        while cur.nextset():
            pass
    finally:
        conn.close()


def _backup_mssql(dst_bak: Path, env: dict[str, str]) -> None:
    db_name = env.get("DB_NAME", "CorrespondenceDB")
    safe_db = db_name.replace("]", "]]")
    safe_path = str(dst_bak.resolve()).replace("'", "''")
    sql = f"BACKUP DATABASE [{safe_db}] TO DISK = N'{safe_path}' WITH INIT, FORMAT, CHECKSUM, NAME = N'Correspondence_Full_Backup';"
    _run_mssql_sql(sql, env, use_master=True)


def _restore_mssql(src_bak: Path, env: dict[str, str]) -> None:
    db_name = env.get("DB_NAME", "CorrespondenceDB")
    safe_db = db_name.replace("]", "]]")
    safe_path = str(src_bak.resolve()).replace("'", "''")
    sql = (
        f"ALTER DATABASE [{safe_db}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
        f"RESTORE DATABASE [{safe_db}] FROM DISK = N'{safe_path}' WITH REPLACE, RECOVERY; "
        f"ALTER DATABASE [{safe_db}] SET MULTI_USER;"
    )
    _run_mssql_sql(sql, env, use_master=True)


def enforce_retention(backup_root: Path, keep_last: int = 30) -> list[str]:
    """الاحتفاظ بآخر N نسخ صالحة وحذف الأقدم فقط."""
    if not backup_root.exists() or keep_last < 1:
        return []
    snapshots = sorted(
        [
            p
            for p in backup_root.iterdir()
            if p.is_dir() and p.name.startswith("backup_") and (p / "backup_manifest.json").is_file()
        ],
        key=lambda p: p.name,
        reverse=True,
    )
    deleted: list[str] = []
    for old_dir in snapshots[keep_last:]:
        shutil.rmtree(old_dir)
        deleted.append(old_dir.name)
    return deleted


def create_backup(
    *,
    base_dir: Path | None = None,
    backup_root: Path | None = None,
    vault_root: Path | None = None,
    sqlite_path: Path | None = None,
    keep_last: int = 30,
    tag: str = "",
) -> dict[str, Any]:
    paths = resolve_paths(
        base_dir=base_dir,
        backup_root=backup_root,
        vault_root=vault_root,
        sqlite_path=sqlite_path,
    )
    env = load_project_env(paths["project_dir"] / ".env")
    db_engine = env.get("DB_ENGINE", "sqlite").lower()

    paths["backup_root"].mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now()
    suffix = f"_{tag}" if tag else ""
    base_name = f"backup_{now.strftime('%Y%m%d_%H%M%S_%f')}{suffix}"
    snapshot_dir = paths["backup_root"] / base_name
    staging_dir = paths["backup_root"] / f".staging_{base_name}"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        db_filename = "database.bak" if db_engine == "mssql" else "database.sqlite3"
        db_dst = staging_dir / db_filename

        if db_engine == "mssql":
            _backup_mssql(db_dst, env)
        else:
            _backup_sqlite(paths["sqlite_path"], db_dst)

        db_hash = sha256_file(db_dst) if db_dst.is_file() else ""
        vault_files = _copy_vault_with_hashes(paths["vault_dir"], staging_dir / "storage_vault")

        manifest = {
            "version": 1,
            "created_at": now.isoformat(),
            "db_engine": db_engine,
            "db_file": db_filename,
            "db_sha256": db_hash,
            "db_size": db_dst.stat().st_size if db_dst.is_file() else 0,
            "vault_file_count": len(vault_files),
            "vault_files": vault_files,
        }
        (staging_dir / "backup_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        staging_dir.rename(snapshot_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    pruned = enforce_retention(paths["backup_root"], keep_last=keep_last)
    return {
        "snapshot_dir": snapshot_dir,
        "manifest": manifest,
        "pruned": pruned,
    }


def verify_backup_snapshot(snapshot_dir: Path) -> dict[str, Any]:
    manifest_path = snapshot_dir / "backup_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"ملف بيانات التحقق backup_manifest.json غير موجود في: {snapshot_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    db_file = snapshot_dir / manifest["db_file"]
    if not db_file.is_file():
        raise FileNotFoundError(f"ملف قاعدة البيانات غير موجود داخل النسخة الاحتياطية: {db_file}")
    if manifest.get("db_sha256") and sha256_file(db_file) != manifest["db_sha256"]:
        raise RuntimeError("فشل التحقق من بصمة SHA-256 لقاعدة البيانات الاحتياطية؛ النسخة تالفة أو معدلة!")

    vault_dir = snapshot_dir / "storage_vault"
    for entry in manifest.get("vault_files", []):
        target = vault_dir / entry["relative_path"]
        if not target.is_file():
            raise FileNotFoundError(f"مرفق مفقود داخل النسخة الاحتياطية: {entry['relative_path']}")
        if sha256_file(target) != entry["sha256"]:
            raise RuntimeError(f"تلف في بصمة SHA-256 للمرفق الاحتياطي: {entry['relative_path']}")

    return manifest


def restore_backup(
    snapshot_dir: Path,
    *,
    confirm_token: str,
    base_dir: Path | None = None,
    backup_root: Path | None = None,
    vault_root: Path | None = None,
    sqlite_path: Path | None = None,
) -> dict[str, Any]:
    if confirm_token != "RESTORE":
        raise PermissionError("يجب تأكيد الاستعادة بكتابة كلمة التأكيد الصريحة (RESTORE).")

    manifest = verify_backup_snapshot(snapshot_dir)
    paths = resolve_paths(
        base_dir=base_dir,
        backup_root=backup_root,
        vault_root=vault_root,
        sqlite_path=sqlite_path,
    )
    env = load_project_env(paths["project_dir"] / ".env")
    db_engine = manifest.get("db_engine", env.get("DB_ENGINE", "sqlite")).lower()

    db_src = snapshot_dir / manifest["db_file"]
    if db_engine == "mssql":
        _restore_mssql(db_src, env)
    else:
        _restore_sqlite(db_src, paths["sqlite_path"])

    # استعادة خزينة الملفات بسلامة ذرية عبر مجلد مؤقت
    live_vault = paths["vault_dir"]
    live_vault.parent.mkdir(parents=True, exist_ok=True)
    temp_vault = live_vault.parent / f".restore_vault_{os.getpid()}"
    if temp_vault.exists():
        shutil.rmtree(temp_vault)
    _copy_vault_with_hashes(snapshot_dir / "storage_vault", temp_vault)

    old_vault_bak = live_vault.parent / f".vault_pre_restore_{os.getpid()}"
    if old_vault_bak.exists():
        shutil.rmtree(old_vault_bak)
    if live_vault.exists():
        live_vault.rename(old_vault_bak)
    temp_vault.rename(live_vault)
    if old_vault_bak.exists():
        shutil.rmtree(old_vault_bak, ignore_errors=True)

    return {
        "restored_from": snapshot_dir,
        "db_engine": db_engine,
        "vault_files_restored": len(manifest.get("vault_files", [])),
    }


def list_backups(backup_root: Path) -> list[Path]:
    if not backup_root.exists():
        return []
    return sorted(
        [
            p
            for p in backup_root.iterdir()
            if p.is_dir() and p.name.startswith("backup_") and (p / "backup_manifest.json").is_file()
        ],
        key=lambda p: p.name,
        reverse=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="أداة النسخ الاحتياطي والاستعادة المتزامنة للنظام")
    sub = parser.add_subparsers(dest="command", required=True)

    p_bak = sub.add_parser("backup", help="إنشاء نسخة احتياطية كاملة (قاعدة البيانات + الخزينة)")
    p_bak.add_argument("--keep", type=int, default=30)

    p_lst = sub.add_parser("list", help="عرض النسخ الاحتياطية المتوفرة")
    p_lst.add_argument("--limit", type=int, default=30)

    p_res = sub.add_parser("restore", help="استعادة نسخة احتياطية محددة")
    p_res.add_argument("--snapshot", default="", help="اسم أو مسار النسخة الاحتياطية (أو الأحدث مع --latest)")
    p_res.add_argument("--latest", action="store_true", help="استخدام أحدث نسخة احتياطية")
    p_res.add_argument("--confirm", default="", help="كلمة التأكيد RESTORE")

    args = parser.parse_args(argv)
    paths = resolve_paths()

    if args.command == "backup":
        res = create_backup(keep_last=args.keep)
        m = res["manifest"]
        print(f"[OK] تم إنشاء النسخة الاحتياطية بنجاح: {res['snapshot_dir']}")
        print(f"     المحرك: {m['db_engine']} | عدد مرفقات الخزينة: {m['vault_file_count']}")
        if res["pruned"]:
            print(f"     تم تدوير وحذف ({len(res['pruned'])}) نسخ قديمة تتجاوز حد {args.keep} نسخة.")
        return 0

    if args.command == "list":
        snaps = list_backups(paths["backup_root"])[: args.limit]
        if not snaps:
            print(f"لا توجد نسخ احتياطية في: {paths['backup_root']}")
            return 0
        for idx, sp in enumerate(snaps, start=1):
            print(f"  {idx:2d}. {sp.name}")
        return 0

    if args.command == "restore":
        snaps = list_backups(paths["backup_root"])
        if args.latest:
            if not snaps:
                print("[خطأ] لا توجد أي نسخة احتياطية للاستعادة.", file=sys.stderr)
                return 1
            target = snaps[0]
        elif args.snapshot:
            cand = Path(args.snapshot)
            target = cand if cand.is_dir() else (paths["backup_root"] / args.snapshot)
        else:
            if not snaps:
                print("[خطأ] لا توجد نسخ احتياطية متوفرة في:", paths["backup_root"], file=sys.stderr)
                return 1
            print("النسخ الاحتياطية المتوفرة:")
            for idx, sp in enumerate(snaps[:30], start=1):
                print(f"  {idx:2d}. {sp.name}")
            choice = input("أدخل رقم أو اسم النسخة المطلوب استعادتها: ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(snaps[:30]):
                target = snaps[int(choice) - 1]
            else:
                target = paths["backup_root"] / choice

        confirm = args.confirm
        if not confirm:
            print(f"\n[تحذير] سيتم استبدال قاعدة البيانات الحالية وخزينة المرفقات بالنسخة: {target.name}")
            confirm = input("للمتابعة وتأكيد الاستعادة اكتب RESTORE بالضبط ثم اضغط Enter: ").strip()

        res = restore_backup(target, confirm_token=confirm)
        print(f"[OK] تمت الاستعادة بنجاح من: {res['restored_from']}")
        print(f"     تمت استعادة قاعدة البيانات ({res['db_engine']}) وعدد ({res['vault_files_restored']}) مرفق بالخزينة.")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
