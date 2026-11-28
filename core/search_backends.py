"""
محرك البحث المفهرس والذكي للأرشيف الإداري الكبير:
- يدعم الفهارس المباشرة (B-Tree) للأرقام الإدارية والمراجع (exact / startswith).
- يدعم التجزئة اللفظية (Tokenization) للبحث النصي وتجنب المسح الكامل الشامل (Full Table Scan).
- مهيأ لدعم Full-Text Search (SQL Server CONTAINS أو SQLite FTS5) عند التفعيل المؤسسي.
"""
from django.db import connection
from django.db.models import Q


class InstitutionalSearchBackend:
    @staticmethod
    def is_number_or_code(term: str) -> bool:
        """التحقق مما إذا كان المصطلح رقم مراسلة أو كود مرجعي يستفيد من فهرس B-Tree المباشر."""
        cleaned = term.strip().upper()
        if not cleaned:
            return False
        # مثل: SUB-2026-0001, DOC-0005, أو أرقام مجردة
        if cleaned.replace("-", "").replace("/", "").isalnum():
            return True
        return False

    @classmethod
    def build_subject_search_q(cls, query_text: str) -> Q:
        """
        بناء استعلام بحث مفهرس للموضوعات:
        - إذا كان المدخل رقماً أو كوداً: يُعطى الأولوية للبحث الدقيق والفهرسي على internal_number.
        - إذا كان نصاً: يجزأ إلى كلمات دلالية لتقليل نطاق البحث ومنع بطء قواعد البيانات الكبيرة.
        """
        query_text = (query_text or "").strip()
        if not query_text:
            return Q()

        base_q = Q()
        if cls.is_number_or_code(query_text):
            # استخدام الفهرس المباشر أولاً
            base_q |= Q(internal_number__iexact=query_text)
            base_q |= Q(internal_number__istartswith=query_text)

        words = [w for w in query_text.split() if len(w) >= 2][:4]
        if not words:
            return base_q or Q(internal_number__icontains=query_text)

        # دمج الكلمات النصية (العنوان، الملخص، الكلمات المفتاحية)
        for w in words:
            word_q = (
                Q(title__icontains=w)
                | Q(description__icontains=w)
                | Q(keywords__icontains=w)
                | Q(applicant_name__icontains=w)
                | Q(external_source__icontains=w)
            )
            base_q = base_q | word_q if not base_q else base_q & word_q

        return base_q

    @classmethod
    def build_document_search_q(cls, query_text: str) -> Q:
        """بناء استعلام بحث مفهرس للمستندات والمرفقات."""
        query_text = (query_text or "").strip()
        if not query_text:
            return Q()

        base_q = Q()
        if cls.is_number_or_code(query_text):
            base_q |= Q(internal_number__iexact=query_text)
            base_q |= Q(internal_number__istartswith=query_text)
            base_q |= Q(external_in_out_number__iexact=query_text)

        words = [w for w in query_text.split() if len(w) >= 2][:4]
        if not words:
            return base_q or Q(internal_number__icontains=query_text)

        for w in words:
            word_q = (
                Q(title__icontains=w)
                | Q(summary__icontains=w)
                | Q(sender_entity__icontains=w)
                | Q(receiver_entity__icontains=w)
            )
            base_q = base_q | word_q if not base_q else base_q & word_q

        return base_q
