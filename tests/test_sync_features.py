"""
حزمة اختبارات الميزات المزامنة مع واجهة React/Gmail (test_sync_features.py):
1. إدارة القوائم المرجعية للمذكرات والجهات في الإعدادات + الحجب 403 عن غير المصرح لهم + إنشاء مذكرة بنوع ديناميكي ومستلم مخصص.
2. بقاء التبويبات الأربعة في البريد الوارد عند فتح تبويب المهام والقرارات + لوحة القراءة الجانبية (preview-json) والعزل الأمني + مسار الخطوات الـ 5.
3. معاينة وتخزين المرفقات متعددة الصيغ (CSV / JSON / SVG sandbox / ?raw=1) ورفض الملفات التنفيذية (.exe).
4. نظام التنبيهات الذكية حسب المستوى الهيكلي (L1–L6) وحجب بيانات السري للغاية.
5. نظام المحادثة الفورية والمجموعات والملفات المرفقة وعزل العضوية (403 لغير الأعضاء).
"""
import json
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from accounts.models import User
from chat.models import ChatConversation, ChatMessage
from core.models import ConfidentialityLevel, DocumentType, MemoRecipientRef, MemoTypeRef, PriorityLevel, TransactionType
from documents.models import Attachment
from notifications.models import Notification
from notifications.services import NotificationService
from organization.models import OrgUnit, Sector
from subjects.models import Memo, Subject
from subjects.services import SubjectService


class SyncFeaturesTestSuite(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo_data")

    def test_settings_reference_lists_crud_and_memo_dynamic_submission(self):
        client = Client()
        superuser = User.objects.get(username="an")
        hr_head = User.objects.get(username="hr_head")
        transfers_emp = User.objects.get(username="transfers_emp")

        settings_url = reverse("core:settings")

        # 1) منع الموظف المختص (transfers_emp) من تعديل الإعدادات (403)
        client.force_login(transfers_emp)
        self.assertEqual(client.get(settings_url).status_code, 403)
        self.assertEqual(
            client.post(
                settings_url,
                {"list_type": "memo_types", "op": "add", "name": "محاولة غير مصرحة"},
            ).status_code,
            403,
        )

        # 2) السماح لرئيس القطاع (hr_head) و Superuser (an) بإضافة وتعديل وحذف القوائم المرجعية
        client.force_login(hr_head)
        self.assertEqual(client.get(f"{settings_url}?tab=memo_types").status_code, 200)

        resp_add_mt = client.post(
            settings_url,
            {
                "list_type": "memo_types",
                "op": "add",
                "code": "URGENT_BRIEF",
                "name": "مذكرة إحاطة عاجلة",
            },
        )
        self.assertEqual(resp_add_mt.status_code, 302)
        mt = MemoTypeRef.objects.get(code="URGENT_BRIEF")
        self.assertEqual(mt.name, "مذكرة إحاطة عاجلة")

        client.force_login(superuser)
        resp_edit_mt = client.post(
            settings_url,
            {
                "list_type": "memo_types",
                "op": "edit",
                "item_id": mt.id,
                "code": "URGENT_BRIEF",
                "name": "مذكرة إحاطة عاجلة محدثة",
            },
        )
        self.assertEqual(resp_edit_mt.status_code, 302)
        mt.refresh_from_db()
        self.assertEqual(mt.name, "مذكرة إحاطة عاجلة محدثة")

        resp_add_tgt = client.post(
            settings_url,
            {
                "list_type": "memo_directed_targets",
                "op": "add",
                "code": "FIN_DIR",
                "name": "السيد / مدير عام الشئون المالية",
            },
        )
        self.assertEqual(resp_add_tgt.status_code, 302)
        tgt = MemoRecipientRef.objects.get(code="FIN_DIR")

        # 3) إنشاء مذكرة رسمية باستخدام نوع ديناميكي + مستلم مخصص (__CUSTOM__)
        client.force_login(transfers_emp)
        subject = Subject.objects.filter(current_owner=transfers_emp).first()
        self.assertIsNotNone(subject)
        detail_url = reverse("subjects:subject_detail", args=[subject.id])
        resp_memo = client.post(
            detail_url,
            {
                "action": "add_memo",
                "memo_type": mt.code,
                "directed_to_select": "__CUSTOM__",
                "directed_to_custom": "لجنة الفحص الفني المشتركة",
                "memo_title": "مذكرة اختبار ديناميكية",
                "memo_body": "تم إعداد المذكرة باستخدام قائمة الإعدادات المرجعية.",
            },
        )
        self.assertEqual(resp_memo.status_code, 302)
        created_memo = Memo.objects.filter(subject=subject, title="مذكرة اختبار ديناميكية").first()
        self.assertIsNotNone(created_memo)
        self.assertEqual(created_memo.memo_type, mt.code)
        self.assertEqual(created_memo.directed_to, "لجنة الفحص الفني المشتركة")
        self.assertEqual(created_memo.get_memo_type_display(), "مذكرة إحاطة عاجلة محدثة")

        # 4) حذف العنصر غير المرتبط
        client.force_login(superuser)
        resp_del = client.post(
            settings_url,
            {"list_type": "memo_directed_targets", "op": "delete", "item_id": tgt.id},
        )
        self.assertEqual(resp_del.status_code, 302)
        self.assertFalse(MemoRecipientRef.objects.filter(id=tgt.id).exists())

    def test_inbox_tasks_tab_split_reading_panel_isolation_and_5_step_stepper(self):
        client = Client()
        superuser = User.objects.get(username="an")
        hr_head = User.objects.get(username="hr_head")
        prod_gm = User.objects.filter(employee__current_unit__sector__code="PROD").first()

        # 1) تبويب المهام والقرارات يحتفظ بالتبويبات الأربعة داخل البريد الوارد
        client.force_login(hr_head)
        resp_tasks = client.get(f"{reverse('core:dashboard')}?folder=inbox&tab=tasks")
        self.assertEqual(resp_tasks.status_code, 200)
        html_tasks = resp_tasks.content.decode("utf-8")
        self.assertIn("الرسائل الأساسية (عهدتي)", html_tasks)
        self.assertIn("للاطلاع والمتابعة", html_tasks)
        self.assertIn("متأخرة وعاجلة", html_tasks)
        self.assertIn("المهام والقرارات", html_tasks)

        # 2) بقاء مسار الخطوات الـ 5 عند فتح الموضوع
        s_public = Subject.objects.filter(sector__code="HR", confidentiality__overrides_hierarchy=False).first()
        resp_detail = client.get(reverse("subjects:subject_detail", args=[s_public.id]))
        self.assertEqual(resp_detail.status_code, 200)
        html_detail = resp_detail.content.decode("utf-8")
        for label in (
            "التسجيل والمرفقات",
            "الحالة الحالية",
            "الإغلاق والأرشفة",
        ):
            self.assertIn(label, html_detail)

        # 3) لوحة القراءة الجانبية (preview-json) تعمل للمصرح له وتحجب 403 عن غير المصرح له
        preview_url = reverse("subjects:subject_preview_json", args=[s_public.id])
        resp_ok = client.get(preview_url)
        self.assertEqual(resp_ok.status_code, 200)
        payload = resp_ok.json()
        self.assertEqual(payload["id"], s_public.id)
        self.assertEqual(payload["internal_number"], s_public.internal_number)

        # إنشاء موضوع سري للغاية ومقارنته بمستخدم آخر معزول
        conf_top = ConfidentialityLevel.objects.get(code="TOP_SECRET")
        tx = TransactionType.objects.first()
        prio = PriorityLevel.objects.first()
        sec_hr = Sector.objects.get(code="HR")
        unit_hr = OrgUnit.objects.filter(sector=sec_hr).first()
        s_secret = SubjectService.create_subject(
            title="موضوع سري للغاية للاختبار",
            description="بيانات حساسة للغاية",
            transaction_type=tx,
            sector=sec_hr,
            org_unit=unit_hr,
            confidentiality=conf_top,
            priority=prio,
            created_by=superuser,
            current_owner=superuser,
        )
        secret_preview_url = reverse("subjects:subject_preview_json", args=[s_secret.id])

        if prod_gm:
            client.force_login(prod_gm)
            self.assertEqual(client.get(secret_preview_url).status_code, 403)
        client.force_login(hr_head)
        self.assertEqual(client.get(secret_preview_url).status_code, 403)

    def test_universal_attachments_preview_csv_json_svg_and_exe_rejection(self):
        client = Client()
        superuser = User.objects.get(username="an")
        s = Subject.objects.first()
        doc_type = DocumentType.objects.first()
        detail_url = reverse("subjects:subject_detail", args=[s.id])
        client.force_login(superuser)

        # 1) رفع CSV + JSON + SVG
        for fname, content, ctype, expected_kind in [
            ("report.csv", b"col1,col2\n10,20\n", "text/csv", "csv"),
            ("data.json", b'{"status":"ok","count":3}', "application/json", "json"),
            ("diagram.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>', "image/svg+xml", "image"),
        ]:
            f = SimpleUploadedFile(fname, content, content_type=ctype)
            resp = client.post(
                detail_url,
                {
                    "action": "upload_attachment",
                    "doc_type_id": doc_type.id,
                    "doc_title": f"مستند {fname}",
                    "attachment_file": f,
                },
            )
            self.assertEqual(resp.status_code, 302)
            att = Attachment.objects.filter(original_filename=fname).order_by("-id").first()
            self.assertIsNotNone(att)
            self.assertEqual(att.preview_kind, expected_kind)

            dl_url = reverse("documents:attachment_download", args=[att.id])
            r_inline = client.get(f"{dl_url}?inline=1&mode=stream")
            self.assertEqual(r_inline.status_code, 200)
            if fname.endswith(".svg"):
                self.assertEqual(r_inline.headers.get("Content-Security-Policy"), "sandbox")
            r_raw = client.get(f"{dl_url}?raw=1")
            self.assertEqual(r_raw.status_code, 200)
            self.assertIn("text/plain", r_raw.headers.get("Content-Type", ""))

        # 2) رفض الملف التنفيذي (.exe)
        bad_exe = SimpleUploadedFile("malware.exe", b"MZ\x90\x00", content_type="application/octet-stream")
        resp_bad = client.post(
            detail_url,
            {
                "action": "upload_attachment",
                "doc_type_id": doc_type.id,
                "doc_title": "ملف مرفوض",
                "attachment_file": bad_exe,
            },
        )
        self.assertEqual(resp_bad.status_code, 302)
        self.assertFalse(Attachment.objects.filter(original_filename="malware.exe").exists())

    def test_smart_notifications_levels_and_top_secret_masking(self):
        client = Client()
        superuser = User.objects.get(username="an")
        hr_head = User.objects.get(username="hr_head")
        transfers_emp = User.objects.get(username="transfers_emp")

        self.assertEqual(NotificationService.infer_user_level(hr_head), "L2")
        self.assertEqual(NotificationService.infer_user_level(transfers_emp), "L5")

        conf_top = ConfidentialityLevel.objects.get(code="TOP_SECRET")
        tx = TransactionType.objects.first()
        prio = PriorityLevel.objects.first()
        sec_hr = Sector.objects.get(code="HR")
        unit_hr = OrgUnit.objects.filter(sector=sec_hr).first()
        s_top = SubjectService.create_subject(
            title="بيان سري للغاية حساس جداً لا يظهر عنوانه",
            description="تفاصيل سرية",
            transaction_type=tx,
            sector=sec_hr,
            org_unit=unit_hr,
            confidentiality=conf_top,
            priority=prio,
            created_by=superuser,
            current_owner=hr_head,
        )
        notif = NotificationService.notify(
            recipient=hr_head,
            subject=s_top,
            category=Notification.Category.INCOMING_REFERRAL,
            title=s_top.title,
            message="رسالة داخلية يجب حجبها",
        )
        self.assertEqual(notif.target_level, "L2")
        self.assertNotIn("بيان سري للغاية حساس", notif.title)
        self.assertNotIn("رسالة داخلية يجب حجبها", notif.message)

        client.force_login(hr_head)
        resp_state = client.get(reverse("notifications:drawer_state"))
        self.assertEqual(resp_state.status_code, 200)
        data = resp_state.json()
        self.assertEqual(data["user_level"], "L2")
        found = [n for n in data["notifications"] if n["id"] == notif.id]
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]["is_top_secret"])

        # تعليم كمقروء عبر AJAX
        resp_mark = client.post(
            reverse("notifications:mark_read_api"),
            data=json.dumps({"notification_id": notif.id}),
            content_type="application/json",
        )
        self.assertEqual(resp_mark.status_code, 200)
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

    def test_realtime_chat_direct_group_attachments_and_isolation(self):
        client = Client()
        hr_head = User.objects.get(username="hr_head")
        transfers_emp = User.objects.get(username="transfers_emp")
        housing_emp = User.objects.get(username="housing_emp")

        # 1) hr_head يفتح محادثة مباشرة مع transfers_emp
        client.force_login(hr_head)
        resp_dm = client.post(
            reverse("chat:direct"),
            data=json.dumps({"target_user_id": transfers_emp.id}),
            content_type="application/json",
        )
        self.assertEqual(resp_dm.status_code, 200)
        dm_id = resp_dm.json()["conversation"]["id"]

        # 2) إرسال رسالة بمرفق نصي داخل المحادثة
        txt_file = SimpleUploadedFile("notes.txt", b"Hello from HR Head", content_type="text/plain")
        resp_msg = client.post(
            reverse("chat:messages"),
            {"conversation_id": dm_id, "text": "يرجى مراجعة المذكرة المرفقة", "attachment": txt_file},
        )
        self.assertEqual(resp_msg.status_code, 200)
        msg_payload = resp_msg.json()["message"]
        msg_id = msg_payload["id"]
        self.assertIsNotNone(msg_payload["attachment"])

        # رفض التنفيذي في المحادثة
        exe_file = SimpleUploadedFile("bad.exe", b"MZ", content_type="application/octet-stream")
        resp_exe = client.post(
            reverse("chat:messages"),
            {"conversation_id": dm_id, "text": "ملف خطر", "attachment": exe_file},
        )
        self.assertEqual(resp_exe.status_code, 400)

        # 3) تحميل ومعاينة مرفق الشات مسموح للطرف الثاني (transfers_emp)
        client.force_login(transfers_emp)
        att_url = reverse("chat:attachment", args=[msg_id])
        self.assertEqual(client.get(f"{att_url}?inline=1").status_code, 200)
        self.assertEqual(client.get(f"{att_url}?raw=1").status_code, 200)

        # 4) عزل العضوية (403) لغير الأعضاء (housing_emp)
        client.force_login(housing_emp)
        self.assertEqual(client.get(att_url).status_code, 403)
        self.assertEqual(
            client.post(
                reverse("chat:messages"),
                data=json.dumps({"conversation_id": dm_id, "text": "تطفل"}),
                content_type="application/json",
            ).status_code,
            403,
        )
        self.assertEqual(
            client.post(
                reverse("chat:read"),
                data=json.dumps({"conversation_id": dm_id}),
                content_type="application/json",
            ).status_code,
            403,
        )

        # 5) إنشاء مجموعة محادثة
        client.force_login(hr_head)
        resp_grp = client.post(
            reverse("chat:groups"),
            data=json.dumps({"name": "فريق التحول الرقمي", "member_ids": [transfers_emp.id]}),
            content_type="application/json",
        )
        self.assertEqual(resp_grp.status_code, 200)
        grp_id = resp_grp.json()["conversation"]["id"]
        self.assertTrue(ChatConversation.objects.filter(id=grp_id, type=ChatConversation.ConversationType.GROUP).exists())
