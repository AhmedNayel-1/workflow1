"""
أمر إدارة لتوليد موضوعات وإحالات اختبارية لأغراض اختبارات التحمل (Load Testing).
الاستخدام: python manage.py seed_load_test --subjects 100
"""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from accounts.models import User
from core.models import ConfidentialityLevel, PriorityLevel, TransactionType
from organization.models import Sector, OrgUnit
from subjects.services import SubjectService
from workflow.models import Referral
from workflow.services import WorkflowEngineService


class Command(BaseCommand):
    help = "توليد موضوعات وإحالات وهمية لاختبارات التحمل والأداء"

    def add_arguments(self, parser):
        parser.add_argument(
            "--subjects",
            type=int,
            default=50,
            help="عدد الموضوعات المراد توليدها (الافتراضي: 50)",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        count = options["subjects"]
        self.stdout.write(f"جاري توليد {count} موضوعاً وإحالة لاختبارات التحمل...")

        superuser = User.objects.filter(is_superuser=True).first()
        if not superuser:
            superuser = User.objects.first()

        sector = Sector.objects.first()
        org_unit = OrgUnit.objects.first()
        tx_type = TransactionType.objects.first()
        conf = ConfidentialityLevel.objects.first()
        prio = PriorityLevel.objects.first()

        if not (superuser and sector and org_unit and tx_type and conf and prio):
            self.stdout.write(self.style.ERROR("البيانات الأساسية غير متوفرة. يرجى تشغيل python manage.py seed_demo_data أولاً."))
            return

        today = timezone.localdate()
        created_count = 0

        for i in range(1, count + 1):
            subj = SubjectService.create_subject(
                title=f"موضوع اختبار تحمّل رقم {i} - نظام السكرتارية والدورة المستندية",
                description=f"هذا الموضوع تم توليده تلقائياً لاختبار الأداء والضغط برقم {i}.",
                transaction_type=tx_type,
                sector=sector,
                org_unit=org_unit,
                confidentiality=conf,
                priority=prio,
                created_by=superuser,
                current_owner=superuser,
                applicant_name=f"مواطن اختبار رقم {i}",
                external_source=f"جهة خارجية {i}",
                keywords=f"اختبار, تحمّل, رقم_{i}",
                due_date=today + timedelta(days=(i % 14)),
            )

            if i % 2 == 0:
                try:
                    WorkflowEngineService.create_referral(
                        subject=subj,
                        referred_by=superuser,
                        routing_mode=Referral.RoutingMode.DIRECT,
                        purpose=Referral.Purpose.FOR_STUDY,
                        notes=f"إحالة اختبارية للموضوع رقم {i}",
                        target_users=[superuser],
                        enforce_hierarchy=False,
                    )
                except Exception:
                    pass

            created_count += 1
            if i % 10 == 0:
                self.stdout.write(f"تم إنشاء {i} موضوعاً...")

        self.stdout.write(self.style.SUCCESS(f"تم بنجاح توليد {created_count} موضوعاً مع إحالاتها لاختبارات التحمل!"))
