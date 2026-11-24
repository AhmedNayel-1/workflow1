"""
خدمات المستندات والمرفقات:
- الترقيم المتزامن الآمن
- التحقق الأمني من الامتداد والحجم والمحتوى الفعلي (Magic Bytes) ومنع الملفات التنفيذية
- حساب SHA-256 والتحقق من سلامة الملفات واكتشاف التلف أو التعديل
- حفظ الملف داخل SECURE_STORAGE_ROOT خارج المجلدات العامة بأسماء آمنة
- دعم تعدد المرفقات وإصدار نسخ جديدة دون استبدال النسخ المعتمدة
"""
import hashlib
import mimetypes
import uuid
from pathlib import Path
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from audit.services import AuditService
from core.models import SystemSequence
from .models import Attachment, Document, DocumentVersion, SubjectDocumentLink


CANONICAL_MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".rtf": "application/rtf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".log": "text/plain",
    ".xml": "application/xml",
    ".yml": "text/yaml",
    ".yaml": "text/yaml",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".zip": "application/zip",
    ".rar": "application/vnd.rar",
    ".7z": "application/x-7z-compressed",
    ".dwg": "application/acad",
    ".dxf": "application/dxf",
}

EXECUTABLE_SIGNATURES = (b"MZ", b"\x7fELF", b"#!", b"\xca\xfe\xba\xbe")


class DocumentService:
    @staticmethod
    def validate_uploaded_file(uploaded_file) -> tuple[str, str]:
        if uploaded_file is None or not getattr(uploaded_file, "name", ""):
            raise ValidationError("اسم الملف المرفق غير صالح.")
        filename = Path(uploaded_file.name).name
        ext = Path(filename).suffix.lower()
        if ext not in settings.ALLOWED_UPLOAD_EXTENSIONS:
            raise ValidationError(
                f"امتداد الملف ({ext}) غير مسموح به أمنياً. الامتدادات المسموحة: {', '.join(sorted(settings.ALLOWED_UPLOAD_EXTENSIONS))}"
            )
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if uploaded_file.size <= 0:
            raise ValidationError("لا يمكن رفع ملف فارغ (حجم 0 بايت).")
        if uploaded_file.size > max_bytes:
            raise ValidationError(
                f"حجم الملف يتجاوز الحد الأقصى المسموح ({settings.MAX_UPLOAD_SIZE_MB} ميجابايت)."
            )

        # فحص المحتوى الفعلي للملف (Magic Bytes) لمنع تزوير الامتداد أو رفع ملفات تنفيذية
        pos = uploaded_file.tell() if hasattr(uploaded_file, "tell") else 0
        head = uploaded_file.read(64)
        if hasattr(uploaded_file, "seek"):
            uploaded_file.seek(pos)

        if any(head.startswith(sig) for sig in EXECUTABLE_SIGNATURES):
            raise ValidationError("محتوى الملف يطابق ملفاً تنفيذياً خطراً ولا يُسمح برفعه.")

        if ext == ".pdf" and not head.lstrip().startswith(b"%PDF-"):
            raise ValidationError("محتوى الملف لا يطابق صيغة PDF الحقيقية.")
        elif ext == ".png" and not head.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValidationError("محتوى الملف لا يطابق صيغة PNG الحقيقية.")
        elif ext in {".jpg", ".jpeg"} and not head.startswith(b"\xff\xd8\xff"):
            raise ValidationError("محتوى الملف لا يطابق صيغة JPEG الحقيقية.")
        elif ext == ".webp" and not (head.startswith(b"RIFF") and head[8:12] == b"WEBP"):
            raise ValidationError("محتوى الملف لا يطابق صيغة WebP الحقيقية.")
        elif ext in {".docx", ".xlsx"} and not (head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06")):
            raise ValidationError(f"محتوى الملف لا يطابق بنية {ext.upper()} الحقيقية.")
        elif ext in {".doc", ".xls"} and not (
            head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
            or head.startswith(b"PK\x03\x04")
            or (ext == ".doc" and head.lstrip().startswith(b"{\\rtf"))
        ):
            raise ValidationError(f"محتوى الملف لا يطابق بنية {ext.upper()} الحقيقية.")
        elif ext in {".txt", ".csv", ".tsv", ".json", ".md", ".log", ".xml", ".yml", ".yaml"} and b"\x00" in head:
            raise ValidationError("الملف النصي يحتوي على بايتات ثنائية غير صالحة.")

        guessed_mime, _ = mimetypes.guess_type(filename)
        canonical_mime = CANONICAL_MIME_BY_EXT.get(ext) or guessed_mime or "application/octet-stream"
        return ext, canonical_mime

    @classmethod
    def store_file_in_vault(cls, uploaded_file, doc_internal_number: str) -> tuple[str, str, int, str]:
        ext, mime_type = cls.validate_uploaded_file(uploaded_file)
        vault_root = Path(settings.SECURE_STORAGE_ROOT).resolve()
        sub_dir = (vault_root / doc_internal_number).resolve()
        if not sub_dir.is_relative_to(vault_root):
            raise ValidationError("مسار تخزين غير صالح.")
        sub_dir.mkdir(parents=True, exist_ok=True)

        safe_storage_name = f"{uuid.uuid4().hex}{ext}.vault"
        full_path = (sub_dir / safe_storage_name).resolve()
        rel_path = f"{doc_internal_number}/{safe_storage_name}"

        hasher = hashlib.sha256()
        total_size = 0
        with open(full_path, "wb") as dest:
            for chunk in uploaded_file.chunks():
                dest.write(chunk)
                hasher.update(chunk)
                total_size += len(chunk)

        return rel_path, hasher.hexdigest(), total_size, mime_type

    @staticmethod
    def verify_attachment_integrity(attachment: Attachment, force_rehash: bool = False) -> dict:
        """
        التحقق من وجود الملف وسلامته.
        في المعاينة والتحميل الاعتيادي: يتم التحقق فائق السرعة من وجود الملف ومطابقة حجمه مع السجل دون قراءة القرص كاملة.
        للملفات عالية السرية (rank >= 3) أو عند طلب force_rehash صراحة أو في الفحص المجدول: يُحسب SHA-256 كاملاً.
        """
        vault_root = Path(settings.SECURE_STORAGE_ROOT).resolve()
        vault_path = (vault_root / attachment.stored_relative_path).resolve()
        if not vault_path.is_relative_to(vault_root):
            return {
                "ok": False,
                "status": "INVALID_PATH",
                "label": "مسار غير صالح",
                "computed_sha256": None,
                "expected_sha256": attachment.sha256_hash,
                "vault_path": None,
            }
        if not vault_path.is_file():
            return {
                "ok": False,
                "status": "MISSING",
                "label": "الملف مفقود من الخزينة",
                "computed_sha256": None,
                "expected_sha256": attachment.sha256_hash,
                "vault_path": None,
            }

        stat_size = vault_path.stat().st_size
        if stat_size != attachment.file_size:
            return {
                "ok": False,
                "status": "TAMPERED",
                "label": "تحذير: حجم الملف في الخزينة غير مطابق للحجم المسجل",
                "computed_sha256": None,
                "expected_sha256": attachment.sha256_hash,
                "vault_path": None,
            }

        is_high_conf = False
        try:
            doc = getattr(attachment.document_version, "document", None)
            if doc and getattr(doc.confidentiality, "rank", 1) >= 3:
                is_high_conf = True
        except Exception:
            pass

        if not force_rehash and not is_high_conf:
            return {
                "ok": True,
                "status": "VALID",
                "label": "سليم ومطابق للبصمة الرقمية (فحص سريع)",
                "computed_sha256": attachment.sha256_hash,
                "expected_sha256": attachment.sha256_hash,
                "vault_path": vault_path,
            }

        hasher = hashlib.sha256()
        actual_size = 0
        with open(vault_path, "rb") as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                hasher.update(chunk)
                actual_size += len(chunk)
        computed = hasher.hexdigest()

        if computed != attachment.sha256_hash or actual_size != attachment.file_size:
            return {
                "ok": False,
                "status": "TAMPERED",
                "label": "تحذير: محتوى الملف تالف أو متغير عن البصمة الأصلية",
                "computed_sha256": computed,
                "expected_sha256": attachment.sha256_hash,
                "vault_path": None,
            }
        return {
            "ok": True,
            "status": "VALID",
            "label": "سليم ومطابق للبصمة الرقمية",
            "computed_sha256": computed,
            "expected_sha256": attachment.sha256_hash,
            "vault_path": vault_path,
        }

    @classmethod
    def _create_attachments_for_version(
        cls,
        *,
        doc: Document,
        version: DocumentVersion,
        uploaded_files: list,
        user,
        description: str = "",
        is_approved: bool = False,
    ) -> list[Attachment]:
        created = []
        for f in uploaded_files:
            if f is None:
                continue
            rel_path, sha256_hex, size_bytes, mime_type = cls.store_file_in_vault(
                f, doc.internal_number
            )
            att = Attachment.objects.create(
                document_version=version,
                original_filename=Path(f.name).name,
                stored_relative_path=rel_path,
                description=description,
                mime_type=mime_type,
                file_size=size_bytes,
                sha256_hash=sha256_hex,
                is_approved=is_approved,
                uploaded_by=user,
            )
            created.append(att)
        return created

    @classmethod
    @transaction.atomic
    def register_document(
        cls,
        *,
        title: str,
        doc_type,
        confidentiality,
        created_by,
        source_type: str = Document.SourceType.INCOMING,
        external_in_out_number: str = "",
        document_date=None,
        received_date=None,
        sender_entity: str = "",
        receiver_entity: str = "",
        summary: str = "",
        subject=None,
        is_primary_subject: bool = True,
        relation_type: str = SubjectDocumentLink.RelationType.PRIMARY,
        uploaded_file=None,
        uploaded_files: list | None = None,
        attachment_description: str = "",
        is_approved: bool = False,
    ) -> Document:
        internal_number = SystemSequence.next_number("DOCUMENT", "DOC")
        doc = Document.objects.create(
            internal_number=internal_number,
            external_in_out_number=external_in_out_number,
            doc_type=doc_type,
            title=title,
            document_date=document_date,
            received_date=received_date,
            sender_entity=sender_entity,
            receiver_entity=receiver_entity,
            confidentiality=confidentiality,
            summary=summary,
            source_type=source_type,
            status=Document.DocStatus.APPROVED if is_approved else Document.DocStatus.REGISTERED,
            current_version_number=1,
            created_by=created_by,
        )
        version = DocumentVersion.objects.create(
            document=doc,
            version_number=1,
            is_approved=False,
            status_label="معتمدة" if is_approved else "نسخة أولى",
            change_reason="تسجيل المستند الأولي",
            created_by=created_by,
        )
        files_list = list(uploaded_files or [])
        if uploaded_file is not None:
            files_list.insert(0, uploaded_file)
        if files_list:
            cls._create_attachments_for_version(
                doc=doc,
                version=version,
                uploaded_files=files_list,
                user=created_by,
                description=attachment_description,
                is_approved=is_approved,
            )
        if is_approved:
            version.is_approved = True
            version.save(update_fields=["is_approved"])

        AuditService.log_audit(
            actor=created_by,
            action="DOCUMENT_CREATED",
            model_name="Document",
            object_id=doc.id,
            after_state={
                "internal_number": doc.internal_number,
                "confidentiality": doc.confidentiality.code,
                "attachments_count": len(files_list),
            },
        )

        if subject is not None:
            SubjectDocumentLink.objects.create(
                subject=subject,
                document=doc,
                is_primary_subject=is_primary_subject,
                relation_type=relation_type,
                linked_by=created_by,
            )
            AuditService.record_activity(
                subject=subject,
                action_type="DOCUMENT_LINKED",
                actor_user=created_by,
                description=f"تسجيل وربط المستند ({doc.internal_number}): {doc.title}",
            )
        return doc

    @classmethod
    @transaction.atomic
    def add_attachments_to_version(
        cls,
        *,
        version: DocumentVersion,
        user,
        uploaded_files: list,
        attachment_description: str = "",
    ) -> list[Attachment]:
        ver = DocumentVersion.objects.select_for_update().select_related("document").get(id=version.id)
        if ver.is_approved:
            raise PermissionDenied("لا يمكن إضافة أو استبدال مرفق داخل نسخة معتمدة؛ يجب إنشاء نسخة جديدة بإجراء رسمي.")
        if not uploaded_files:
            raise ValidationError("يجب اختيار ملف واحد على الأقل للرفع.")
        created = cls._create_attachments_for_version(
            doc=ver.document,
            version=ver,
            uploaded_files=uploaded_files,
            user=user,
            description=attachment_description,
            is_approved=False,
        )
        AuditService.log_audit(
            actor=user,
            action="ATTACHMENT_ADDED",
            model_name="DocumentVersion",
            object_id=ver.id,
            after_state={"version": ver.version_number, "files": [a.original_filename for a in created]},
        )
        return created

    @classmethod
    @transaction.atomic
    def create_new_version(
        cls,
        *,
        document: Document,
        user,
        change_reason: str,
        is_approved: bool = False,
        uploaded_file=None,
        uploaded_files: list | None = None,
        attachment_description: str = "",
    ) -> DocumentVersion:
        if not (change_reason or "").strip():
            raise ValidationError("يجب كتابة سبب رسمي موثق عند إصدار نسخة جديدة من المستند.")

        doc = Document.objects.select_for_update().get(id=document.id)
        next_ver = doc.current_version_number + 1
        # تُنشأ مسودة أولاً لإرفاق الملفات قبل ختم الاعتماد (حماية لعدم تعديل النسخ المعتمدة)
        version = DocumentVersion.objects.create(
            document=doc,
            version_number=next_ver,
            is_approved=False,
            status_label="معتمدة" if is_approved else "مسودة",
            change_reason=change_reason.strip(),
            created_by=user,
        )

        files_list = list(uploaded_files or [])
        if uploaded_file is not None:
            files_list.insert(0, uploaded_file)
        if files_list:
            cls._create_attachments_for_version(
                doc=doc,
                version=version,
                uploaded_files=files_list,
                user=user,
                description=attachment_description,
                is_approved=is_approved,
            )

        if is_approved:
            version.is_approved = True
            version.save(update_fields=["is_approved"])
            doc.status = Document.DocStatus.APPROVED

        doc.current_version_number = next_ver
        doc.save(update_fields=["current_version_number", "status"])

        AuditService.log_audit(
            actor=user,
            action="DOCUMENT_VERSION_CREATED",
            model_name="DocumentVersion",
            object_id=version.id,
            after_state={
                "document": doc.internal_number,
                "version_number": next_ver,
                "is_approved": is_approved,
                "change_reason": version.change_reason,
            },
        )
        for subj in doc.subjects.all():
            AuditService.record_activity(
                subject=subj,
                action_type="DOCUMENT_VERSION_CREATED",
                actor_user=user,
                description=f"إصدار نسخة جديدة v{next_ver} للمستند ({doc.internal_number}): {version.change_reason}",
            )
        return version

    @classmethod
    @transaction.atomic
    def approve_version(cls, *, version: DocumentVersion, user) -> DocumentVersion:
        ver = DocumentVersion.objects.select_for_update().select_related("document").get(id=version.id)
        if ver.is_approved:
            raise ValidationError("هذه النسخة معتمدة بالفعل ولا يمكن إعادة اعتمادها.")
        ver.attachments.update(is_approved=True)
        ver.is_approved = True
        ver.status_label = "معتمدة"
        ver.save(update_fields=["is_approved", "status_label"])
        ver.document.status = Document.DocStatus.APPROVED
        ver.document.save(update_fields=["status"])

        AuditService.log_audit(
            actor=user,
            action="DOCUMENT_VERSION_APPROVED",
            model_name="DocumentVersion",
            object_id=ver.id,
            after_state={"document": ver.document.internal_number, "version_number": ver.version_number},
        )
        for subj in ver.document.subjects.all():
            AuditService.record_activity(
                subject=subj,
                action_type="DOCUMENT_VERSION_APPROVED",
                actor_user=user,
                description=f"اعتماد النسخة v{ver.version_number} من المستند ({ver.document.internal_number})",
            )
        return ver


verify_attachment_integrity = DocumentService.verify_attachment_integrity

