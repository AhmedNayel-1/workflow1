import hashlib
import json
from pathlib import Path
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.db.models import Count
from accounts.models import User
from documents.services import DocumentService
from notifications.services import NotificationService
from .models import ChatConversation, ChatMessage


def _touch_presence(user) -> None:
    if user and user.is_authenticated:
        cache.set(f"chat_online_{user.id}", True, timeout=120)


def _get_online_user_ids(user_ids) -> list[int]:
    online_ids = []
    for uid in user_ids:
        if cache.get(f"chat_online_{uid}"):
            online_ids.append(uid)
    return online_ids


def _serialize_message(msg: ChatMessage) -> dict:
    att = None
    if msg.attachment_name and msg.attachment_stored_path:
        url = reverse("chat:attachment", args=[msg.id])
        att = {
            "name": msg.attachment_name,
            "size": msg.attachment_size,
            "mime": msg.attachment_mime,
            "preview_kind": msg.preview_kind,
            "preview_url": f"{url}?inline=1",
            "download_url": url,
            "raw_url": f"{url}?raw=1",
        }
    return {
        "id": msg.id,
        "conversation_id": msg.conversation_id,
        "sender_id": msg.sender_id,
        "sender_username": msg.sender.username,
        "sender_name": msg.sender.first_name or msg.sender.username,
        "text": msg.text,
        "attachment": att,
        "read_by_ids": list(msg.read_by.values_list("id", flat=True)),
        "created_at": timezone.localtime(msg.created_at).strftime("%Y-%m-%d %H:%M"),
        "time_short": timezone.localtime(msg.created_at).strftime("%H:%M"),
    }


def _serialize_conversation(conv: ChatConversation, current_user, unread_count: int = 0) -> dict:
    members_list = list(conv.members.all())
    if conv.type == ChatConversation.ConversationType.GROUP:
        display_title = conv.name or f"مجموعة #{conv.id}"
        peer_id = None
    else:
        peer = next((m for m in members_list if m.id != current_user.id), current_user)
        display_title = peer.first_name or peer.username
        peer_id = peer.id

    msgs = list(conv.messages.all())
    last_msg = msgs[-1] if msgs else None

    return {
        "id": conv.id,
        "type": conv.type,
        "name": conv.name,
        "display_title": display_title,
        "peer_id": peer_id,
        "member_ids": [m.id for m in members_list],
        "member_names": [m.first_name or m.username for m in members_list],
        "unread_count": unread_count,
        "last_message": _serialize_message(last_msg) if last_msg else None,
        "created_at": timezone.localtime(conv.created_at).strftime("%Y-%m-%d %H:%M"),
    }


@login_required
def chat_state(request):
    """جلب قائمة المحادثات والرسائل وحالة التواجد للمستخدم الحالي بأداء خفيف ومُحسّن."""
    _touch_presence(request.user)

    convs = list(
        ChatConversation.objects.filter(members=request.user)
        .prefetch_related("members", "messages__sender", "messages__read_by")
        .distinct()
    )

    # حساب عدد الرسائل غير المقروءة لكل محادثة باستعلام مجمع واحد بدلاً من N+1
    unread_counts_map = dict(
        ChatMessage.objects.filter(
            conversation__members=request.user
        ).exclude(sender=request.user).exclude(read_by=request.user)
        .values("conversation_id").annotate(cnt=Count("id")).values_list("conversation_id", "cnt")
    )

    serialized_convs = [
        _serialize_conversation(c, request.user, unread_counts_map.get(c.id, 0))
        for c in convs
    ]
    serialized_convs.sort(
        key=lambda c: (c["last_message"]["created_at"] if c["last_message"] else c["created_at"]),
        reverse=True,
    )

    # جمع معرّفات جهات الاتصال النشطة فقط لفحص التواجد
    contact_ids = {request.user.id}
    for c in convs:
        for m in c.members.all():
            contact_ids.add(m.id)
    online_ids = set(_get_online_user_ids(contact_ids))
    online_ids.add(request.user.id)

    selected_conv_id = request.GET.get("conversation_id")
    messages_payload = []
    if selected_conv_id:
        target_conv = next((c for c in convs if str(c.id) == str(selected_conv_id)), None)
        if target_conv:
            messages_payload = [_serialize_message(m) for m in target_conv.messages.all()]
    else:
        for c in convs:
            for m in c.messages.all():
                messages_payload.append(_serialize_message(m))

    total_unread = sum(c["unread_count"] for c in serialized_convs)

    # التخزين المؤقت لقائمة المستخدمين العامة (تتغير نادراً) لتفادي تحميل الجدول بالكامل كل بضع ثوانٍ
    cached_users_dir = cache.get("chat_users_directory_data")
    if not cached_users_dir:
        all_users = list(User.objects.filter(is_active=True).select_related("employee__current_unit").order_by("id"))
        cached_users_dir = []
        for u in all_users:
            unit_name = str(u.employee.current_unit) if getattr(u, "employee", None) and u.employee.current_unit else (u.job_display_title or "النظام")
            cached_users_dir.append({
                "id": u.id,
                "username": u.username,
                "full_name": u.first_name or u.username,
                "job_title": u.job_display_title or "",
                "unit": unit_name,
                "level": NotificationService.infer_user_level(u),
            })
        cache.set("chat_users_directory_data", cached_users_dir, timeout=300)

    chat_users = [
        {**u, "is_online": u["id"] in online_ids}
        for u in cached_users_dir
    ]

    return JsonResponse(
        {
            "current_user_id": request.user.id,
            "current_username": request.user.username,
            "conversations": serialized_convs,
            "messages": messages_payload,
            "online_user_ids": list(online_ids),
            "chat_users": chat_users,
            "total_unread": total_unread,
        }
    )


@login_required
@require_POST
def create_direct(request):
    """إنشاء أو استرجاع محادثة فردية ثنائية مع مستخدم آخر."""
    _touch_presence(request.user)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = request.POST.dict()

    target_user = None
    if payload.get("target_user_id"):
        target_user = User.objects.filter(id=payload.get("target_user_id"), is_active=True).first()
    elif payload.get("target_username"):
        target_user = User.objects.filter(username=payload.get("target_username"), is_active=True).first()

    if not target_user:
        return JsonResponse({"error": "المستخدم المستهدف غير موجود أو غير مفعل."}, status=400)
    if target_user.id == request.user.id:
        return JsonResponse({"error": "لا يمكن إنشاء محادثة فردية مع نفس المستخدم."}, status=400)

    existing = (
        ChatConversation.objects.filter(type=ChatConversation.ConversationType.DIRECT, members=request.user)
        .filter(members=target_user)
        .distinct()
    )
    conv = None
    for candidate in existing:
        if candidate.members.count() == 2:
            conv = candidate
            break

    if conv is None:
        conv = ChatConversation.objects.create(
            type=ChatConversation.ConversationType.DIRECT,
            created_by=request.user,
        )
        conv.members.add(request.user, target_user)

    return JsonResponse({"conversation": _serialize_conversation(conv, request.user)})


@login_required
@require_POST
def create_group(request):
    """إنشاء مجموعة محادثة جديدة."""
    _touch_presence(request.user)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = request.POST.dict()

    name = str(payload.get("name", "")).strip()
    if not name:
        return JsonResponse({"error": "اسم المجموعة مطلوب."}, status=400)

    member_ids = payload.get("member_ids") or []
    users = list(User.objects.filter(id__in=member_ids, is_active=True))
    conv = ChatConversation.objects.create(
        type=ChatConversation.ConversationType.GROUP,
        name=name[:180],
        created_by=request.user,
    )
    conv.members.add(request.user, *users)
    return JsonResponse({"conversation": _serialize_conversation(conv, request.user)})


@login_required
@require_POST
def send_message(request):
    """إرسال رسالة فورية نصية و/أو مرفق ملف محمي في المحادثة."""
    _touch_presence(request.user)
    if request.content_type and "multipart/form-data" in request.content_type:
        conv_id = request.POST.get("conversation_id")
        text = request.POST.get("text", "").strip()
        uploaded = request.FILES.get("attachment")
    else:
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except Exception:
            payload = {}
        conv_id = payload.get("conversation_id")
        text = str(payload.get("text", "")).strip()
        uploaded = None

    conv = get_object_or_404(ChatConversation, id=conv_id)
    if not conv.members.filter(id=request.user.id).exists():
        raise PermissionDenied("غير مصرح لك بالإرسال داخل هذه المحادثة.")

    if not text and uploaded is None:
        return JsonResponse({"error": "يجب إدخال نص الرسالة أو إرفاق ملف."}, status=400)

    att_name = ""
    att_path = ""
    att_size = 0
    att_mime = ""
    att_sha = ""
    if uploaded is not None:
        try:
            rel_path, sha256, size_bytes, mime_type = DocumentService.store_file_in_vault(uploaded, f"chat/conv_{conv.id}")
        except ValidationError as exc:
            msg_err = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            return JsonResponse({"error": msg_err}, status=400)
        att_name = Path(uploaded.name).name[:255]
        att_path = rel_path
        att_size = size_bytes
        att_mime = mime_type
        att_sha = sha256

    msg = ChatMessage.objects.create(
        conversation=conv,
        sender=request.user,
        text=text,
        attachment_name=att_name,
        attachment_stored_path=att_path,
        attachment_size=att_size,
        attachment_mime=att_mime,
        attachment_sha256=att_sha,
    )
    msg.read_by.add(request.user)
    return JsonResponse({"message": _serialize_message(msg)})


@login_required
@require_POST
def mark_read(request):
    """تعليم جميع الرسائل غير المقروءة في محادثة كمقروءة."""
    _touch_presence(request.user)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = request.POST.dict()

    conv = get_object_or_404(ChatConversation, id=payload.get("conversation_id"))
    if not conv.members.filter(id=request.user.id).exists():
        raise PermissionDenied("غير مصرح لك بالوصول لهذه المحادثة.")

    unread_msgs = conv.messages.exclude(sender=request.user).exclude(read_by=request.user)
    for m in unread_msgs:
        m.read_by.add(request.user)

    return JsonResponse({"ok": True})


@login_required
def chat_attachment(request, msg_id: int):
    """معاينة أو تنزيل مرفق رسالة محادثة مع عزل العضوية وفحص سلامة الخزينة."""
    msg = get_object_or_404(ChatMessage.objects.select_related("conversation"), id=msg_id)
    if not msg.conversation.members.filter(id=request.user.id).exists():
        raise PermissionDenied("غير مصرح لك بالاطلاع على مرفقات هذه المحادثة.")

    if not msg.attachment_stored_path:
        raise Http404("لا يوجد مرفق لهذه الرسالة.")

    vault_root = Path(settings.SECURE_STORAGE_ROOT).resolve()
    target = (vault_root / msg.attachment_stored_path).resolve()
    if not target.is_relative_to(vault_root) or not target.exists():
        raise Http404("ملف المرفق غير موجود في الخزينة.")

    sha256 = hashlib.sha256()
    with target.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    if msg.attachment_sha256 and sha256.hexdigest() != msg.attachment_sha256:
        raise PermissionDenied("تم اكتشاف عدم تطابق بصمة المرفق الأمنية.")

    if request.GET.get("raw") == "1":
        with target.open("rb") as f:
            raw_chunk = f.read(32768)
        raw_text = raw_chunk.decode("utf-8", errors="replace")
        resp = HttpResponse(raw_text, content_type="text/plain; charset=utf-8")
        resp["X-Content-Type-Options"] = "nosniff"
        return resp

    inline = request.GET.get("inline") == "1"
    response = FileResponse(target.open("rb"), content_type=msg.attachment_mime or "application/octet-stream")
    disposition = "inline" if inline else "attachment"
    response["Content-Disposition"] = f'{disposition}; filename="{msg.attachment_name}"'
    response["X-Content-Type-Options"] = "nosniff"
    if (msg.attachment_mime or "") == "image/svg+xml":
        response["Content-Security-Policy"] = "sandbox"
    return response
