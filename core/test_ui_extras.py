from django.test import SimpleTestCase

from core.templatetags.ui_extras import arstatus


class ArStatusFilterTests(SimpleTestCase):
    def test_known_codes_get_arabic_labels(self):
        out = arstatus("تغيير حالة الموضوع من (IN_PROGRESS) إلى (SUSPENDED)")
        self.assertIn("(قيد التنفيذ)", out)
        self.assertIn("(معلق (للاستيفاء))", out)
        self.assertNotIn("IN_PROGRESS", out)

    def test_unknown_codes_and_plain_text_are_unchanged(self):
        self.assertEqual(arstatus("حالة (SOMETHING_ELSE) كما هي"), "حالة (SOMETHING_ELSE) كما هي")
        self.assertEqual(arstatus("IN_PROGRESS بدون أقواس"), "IN_PROGRESS بدون أقواس")

    def test_empty_values(self):
        self.assertEqual(arstatus(None), "")
        self.assertEqual(arstatus(""), "")
