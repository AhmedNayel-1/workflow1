from django.db import migrations


def forwards(apps, schema_editor):
    from accounts.delegation_sync import sync_secretariat_delegations
    sync_secretariat_delegations(apps.get_model("accounts", "Delegation"), apps.get_model("accounts", "UserRoleAssignment"))


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial"), ("organization", "0001_initial")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
