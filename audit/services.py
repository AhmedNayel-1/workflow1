from .models import ActivityLog, AuditLog


class AuditService:
    @staticmethod
    def record_activity(
        *,
        subject,
        action_type: str,
        actor_user,
        description: str,
        acting_on_behalf_of=None,
        delegation=None,
        metadata: dict | None = None,
        correction_of=None,
        correction_reason: str = "",
    ) -> ActivityLog:
        return ActivityLog.objects.create(
            subject=subject,
            action_type=action_type,
            actor_user=actor_user,
            acting_on_behalf_of=acting_on_behalf_of,
            delegation=delegation,
            description=description,
            metadata_json=metadata or {},
            correction_of=correction_of,
            correction_reason=correction_reason,
        )

    @staticmethod
    def log_audit(
        *,
        actor,
        action: str,
        model_name: str,
        object_id="",
        before_state: dict | None = None,
        after_state: dict | None = None,
        ip_address: str | None = None,
        outcome: str = "SUCCESS",
        reason: str = "",
    ) -> AuditLog:
        return AuditLog.objects.create(
            actor_user=actor if getattr(actor, "is_authenticated", False) else None,
            action=action,
            model_name=model_name,
            object_id=str(object_id or ""),
            before_state=before_state or {},
            after_state=after_state or {},
            ip_address=ip_address,
            outcome=outcome,
            reason=reason,
        )
