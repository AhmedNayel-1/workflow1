from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "المستخدمون والصلاحيات والإنابة"

    def ready(self):
        from django.db.models.signals import post_save

        from .delegation_sync import sync_secretariat_delegations
        from .models import Delegation, UserRoleAssignment

        def _on_assignment(sender, instance, **kw):
            if instance.org_unit_id:
                sync_secretariat_delegations(Delegation, UserRoleAssignment, unit_ids=[instance.org_unit_id])

        post_save.connect(_on_assignment, sender=UserRoleAssignment, dispatch_uid="sync_secretariat_delegations")
