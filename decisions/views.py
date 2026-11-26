import uuid
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from accounts.models import User
from accounts.services import PermissionService
from core.models import DocumentType
from documents.models import Document, SubjectDocumentLink
from documents.services import DocumentService
from organization.models import OrgUnit
from subjects.models import Subject
from subjects.services import SubjectService
from .models import Decision, DecisionExecutionItem
from .services import DecisionService


@login_required
def decision_list(request):
    """قائمة القرارات الإدارية المصفاة بصلاحية الاطلاع على الموضوعات."""
    decisions = Decision.objects.select_related("subject__confidentiality", "created_by", "approved_by").all()
    visible_decisions = [
        d for d in decisions if PermissionService.can_view_subject(request.user, d.subject)
    ]
    return render(request, "decisions/decision_list.html", {"decisions": visible_decisions})


@login_required
def decision_create(request, subject_id: int):
    """إعداد مشروع قرار إداري مرتبط بموضوع."""
    subject = get_object_or_404(Subject, id=subject_id)
    if not PermissionService.can_view_subject(request.user, subject):
        raise PermissionDenied("غير مصرح لك بالوصول للموضوع.")
    if not PermissionService.user_has_permission(
        request.user,
        "DECISION_CREATE",
        sector=subject.sector,
        confidentiality_rank=subject.confidentiality.rank,
        subject=subject,
    ):
        raise PermissionDenied("ليس لديك صلاحية إعداد القرارات.")
    if not PermissionService.can_act_on_subject(request.user, subject):
        raise PermissionDenied("لا يمكنك إعداد قرار على موضوع للاطلاع فقط في مستواك الحالي.")

    if request.method == "POST":
        decision = DecisionService.create_decision_draft(
            subject=subject,
            decision_type=request.POST.get("decision_type", Decision.DecisionType.GENERAL),
            title=request.POST.get("title", "").strip(),
            body=request.POST.get("body", "").strip(),
            issuing_authority=request.POST.get("issuing_authority", "").strip(),
            approving_authority=request.POST.get("approving_authority", "").strip(),
            created_by=request.user,
            idempotency_key=request.POST.get("idempotency_key") or None,
        )
        messages.success(request, f"تم إعداد مشروع القرار رقم {decision.decision_number}.")
        return redirect("decisions:decision_detail", decision_id=decision.id)

    return render(
        request,
        "decisions/decision_form.html",
        {
            "subject": subject,
            "decision_types": Decision.DecisionType.choices,
            "idempotency_key": str(uuid.uuid4()),
        },
    )


@login_required
def decision_detail(request, decision_id: int):
    """إدارة دورة حياة القرار (مراجعة، اعتماد، إصدار، توزيع، متابعة تنفيذ)."""
    decision = get_object_or_404(
        Decision.objects.select_related("subject__confidentiality", "created_by", "approved_by").prefetch_related(
            "distributions__target_unit",
            "execution_items__assigned_unit",
            "execution_items__assigned_user",
            "execution_items__proof_document__versions__attachments",
        ),
        id=decision_id,
    )
    if not PermissionService.can_view_subject(request.user, decision.subject):
        raise PermissionDenied("غير مصرح لك بالاطلاع على هذا القرار.")

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "approve_issue":
                DecisionService.approve_and_issue(decision=decision, user=request.user, issue_immediately=True)
                messages.success(request, "تم اعتماد القرار وإصداره بنجاح.")

            elif action == "distribute_assign":
                unit_ids = request.POST.getlist("distribution_unit_ids")
                dist_units = list(OrgUnit.objects.filter(id__in=unit_ids))
                exec_user_id = request.POST.get("exec_user_id")
                exec_unit_id = request.POST.get("exec_unit_id")
                exec_action = request.POST.get("exec_required_action", "").strip()
                assignments = []
                if exec_user_id and exec_unit_id and exec_action:
                    assignments.append(
                        {
                            "user": get_object_or_404(User, id=exec_user_id),
                            "unit": get_object_or_404(OrgUnit, id=exec_unit_id),
                            "required_action": exec_action,
                            "due_date": request.POST.get("exec_due_date") or None,
                        }
                    )
                DecisionService.distribute_and_assign_execution(
                    decision=decision,
                    user=request.user,
                    distribution_units=dist_units,
                    execution_assignments=assignments,
                )
                messages.success(request, "تم توزيع القرار وتسجيل التكليف التنفيذي.")

            elif action == "complete_execution":
                exec_item = get_object_or_404(
                    DecisionExecutionItem, id=request.POST.get("exec_item_id"), decision=decision
                )
                is_exec_authorized = getattr(request.user, "is_superuser", False) or exec_item.assigned_user_id == request.user.id
                if not is_exec_authorized:
                    delegation = PermissionService.get_acting_delegation(
                        request.user, "DECISION_CREATE", subject=decision.subject
                    )
                    is_exec_authorized = bool(delegation and delegation.delegator_id == exec_item.assigned_user_id)
                if not is_exec_authorized:
                    raise PermissionDenied("تسجيل إتمام تنفيذ القرار مقتصر على الموظف المكلف بالتنفيذ فقط.")

                proof_doc_id = request.POST.get("proof_document_id") or None
                proof_doc = Document.objects.filter(id=proof_doc_id).first() if proof_doc_id else None
                if proof_doc is not None and not PermissionService.can_view_document(request.user, proof_doc):
                    raise PermissionDenied("غير مصرح لك بإرفاق هذا المستند كإثبات تنفيذ.")

                proof_file = request.FILES.get("proof_file")
                if proof_file is not None:
                    DocumentService.validate_uploaded_file(proof_file)
                    chosen_dt = (
                        DocumentType.objects.filter(code="DECISION_DOC", is_active=True).first()
                        or DocumentType.objects.filter(is_active=True).first()
                    )
                    if chosen_dt:
                        proof_doc = DocumentService.register_document(
                            title=f"إثبات تنفيذ القرار {decision.decision_number}",
                            doc_type=chosen_dt,
                            confidentiality=decision.subject.confidentiality,
                            created_by=request.user,
                            summary=request.POST.get("execution_result", "").strip() or decision.title,
                            subject=decision.subject,
                            is_primary_subject=False,
                            relation_type=SubjectDocumentLink.RelationType.OUTPUT,
                            uploaded_file=proof_file,
                        )

                DecisionService.complete_execution_item(
                    exec_item=exec_item,
                    user=request.user,
                    execution_result=request.POST.get("execution_result", "").strip(),
                    proof_document=proof_doc,
                )
                messages.success(request, "تم تسجيل إثبات تنفيذ القرار بنجاح.")

        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
        return redirect("decisions:decision_detail", decision_id=decision.id)

    can_approve = PermissionService.user_has_permission(
        request.user,
        "DECISION_APPROVE",
        sector=decision.subject.sector,
        confidentiality_rank=decision.subject.confidentiality.rank,
        subject=decision.subject,
    )
    can_close_subject = PermissionService.can_act_on_subject(request.user, decision.subject) and PermissionService.user_has_permission(
        request.user,
        "SUBJECT_CLOSE",
        sector=decision.subject.sector,
        confidentiality_rank=decision.subject.confidentiality.rank,
        subject=decision.subject,
    )
    if request.user.is_superuser or PermissionService.is_org_wide_manager(request.user):
        scoped_units = OrgUnit.objects.filter(is_active=True)
        scoped_users = User.objects.filter(is_active=True)
    else:
        scoped_units = OrgUnit.objects.filter(is_active=True, sector=decision.subject.sector)
        scoped_users = User.objects.filter(is_active=True, employee__current_unit__sector=decision.subject.sector)

    return render(
        request,
        "decisions/decision_detail.html",
        {
            "decision": decision,
            "can_approve": can_approve,
            "can_distribute": decision.status in (Decision.Status.APPROVED, Decision.Status.ISSUED, Decision.Status.DISTRIBUTING, Decision.Status.EXECUTING) and PermissionService.can_distribute_decision(request.user, decision),
            "can_close_subject": can_close_subject,
            "closure_blockers": SubjectService.validate_closure_requirements(decision.subject),
            "org_units": scoped_units,
            "users": scoped_users,
            "subject_docs": [d for d in decision.subject.documents.all() if PermissionService.can_view_document(request.user, d)],
        },
    )


@login_required
def decision_print(request, decision_id: int):
    """قالب طباعة رسمي للقرار الإداري RTL."""
    decision = get_object_or_404(Decision.objects.select_related("subject", "approved_by"), id=decision_id)
    if not PermissionService.can_view_subject(request.user, decision.subject):
        raise PermissionDenied("غير مصرح لك بطباعة هذا القرار.")
    return render(request, "decisions/decision_print.html", {"decision": decision})
