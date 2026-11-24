"""
أمر تشغيلي مجدول أو عند الطلب للتدقيق الرقمي الشامل على كافة ملفات الخزينة المعزولة .vault
باستخدام بصمات التجزئة SHA-256 دون التأثير على استجابة شاشات التصفح والمعاينة.
"""
from django.core.management.base import BaseCommand
from documents.models import Attachment
from documents.services import DocumentService


class Command(BaseCommand):
    help = "التدقيق الرقمي الشامل على سلامة ملفات الخزينة المعزولة عبر SHA-256"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="الحد الأقصى للمرفقات المراد فحصها (0 تعني فحص كل المرفقات)",
        )
        parser.add_argument(
            "--only-confidential",
            action="store_true",
            help="حصر الفحص على الملفات السرية للغاية",
        )

    def handle(self, *args, **options):
        qs = Attachment.objects.select_related("document_version__document__confidentiality").order_by("-id")
        if options["only_confidential"]:
            qs = qs.filter(document_version__document__confidentiality__rank__gte=3)
        limit = options.get("limit") or 0
        if limit > 0:
            qs = qs[:limit]

        total = qs.count() if limit == 0 else min(limit, qs.count())
        self.stdout.write(self.style.NOTICE(f"بدء التدقيق الرقمي الشامل على {total} مرفق في الخزينة..."))

        valid_count = 0
        tampered_count = 0
        missing_count = 0

        for att in qs:
            res = DocumentService.verify_attachment_integrity(att, force_rehash=True)
            if res["ok"]:
                valid_count += 1
            elif res["status"] == "MISSING":
                missing_count += 1
                self.stdout.write(self.style.ERROR(f"[مفقود] مرفق #{att.id}: {att.original_filename}"))
            else:
                tampered_count += 1
                self.stdout.write(self.style.ERROR(f"[تالف/معدّل] مرفق #{att.id}: {att.original_filename} - {res['label']}"))

        self.stdout.write(self.style.SUCCESS(
            f"اكتمل الفحص: {valid_count} سليم، {tampered_count} تالف، {missing_count} مفقود من أصل {total}."
        ))
