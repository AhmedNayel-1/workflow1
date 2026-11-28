from django.db import migrations
from django.utils import timezone


def forwards(apps, schema_editor):
    D = apps.get_model("accounts", "Delegation")
    A = apps.get_model("accounts", "UserRoleAssignment")
    ids = set(A.objects.filter(role__code="SECTOR_DIR_ADMIN", is_active=True).values_list("user_id", flat=True))
    ids -= set(A.objects.filter(role__code="SECRETARIAT", is_active=True).values_list("user_id", flat=True))
    D.objects.filter(delegate_id__in=ids, delegation_type="SECRETARIAT", is_active=True).update(
        is_active=False, revoked_at=timezone.now(), revoked_reason="مسؤول القطاع لإدارة المستخدمين فقط")


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_sync_secretariat")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
