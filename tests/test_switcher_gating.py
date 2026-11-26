"""بوابة مبدّل الحسابات التطويري: معطّل خارج DEBUG (نسخة معاد بناؤها)."""
import os
import subprocess
import sys
from pathlib import Path

from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import User

ROOT = Path(__file__).resolve().parent.parent


class SwitcherView(TestCase):
    @classmethod
    def setUpTestData(cls):
        with cls.captureOnCommitCallbacks(execute=True):
            call_command("seed_demo_data")

    def _post(self, username="hr_sec"):
        c = Client()
        c.force_login(User.objects.get(username=username))
        return c, c.post(reverse("accounts:switch_user"), {"username": "an"})

    @override_settings(DEBUG=True, ENABLE_DEV_ACCOUNT_SWITCHER=False)
    def test_debug_alone_does_not_enable_switch(self):
        c, r = self._post()
        self.assertEqual(r.status_code, 403)
        self.assertEqual(int(c.session["_auth_user_id"]), User.objects.get(username="hr_sec").id)

    @override_settings(DEBUG=False, ENABLE_DEV_ACCOUNT_SWITCHER=False)
    def test_production_disabled(self):
        _, r = self._post()
        self.assertEqual(r.status_code, 403)

    @override_settings(DEBUG=False, ENABLE_DEV_ACCOUNT_SWITCHER=False)
    def test_no_switcher_markup_in_production(self):
        c = Client()
        c.force_login(User.objects.get(username="hr_sec"))
        html = c.get("/").content.decode()
        self.assertNotIn("switch-user", html)

    @override_settings(DEBUG=True, ENABLE_DEV_ACCOUNT_SWITCHER=True)
    def test_dev_mode_works(self):
        c, r = self._post()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(int(c.session["_auth_user_id"]), User.objects.get(username="an").id)


class SettingsDefaults(TestCase):
    def _flags(self, **env):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_DEBUG", "ENABLE_DEV"))}
        e.update({"DJANGO_SECRET_KEY": "k" * 50}, **env, SQLITE_PATH=":memory:")
        code = ("import os;from dotenv import load_dotenv;import dotenv;"
                "dotenv.load_dotenv=lambda *a,**k:False;"
                "import config.settings as s;print(s.DEBUG,s.ENABLE_DEV_ACCOUNT_SWITCHER)")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=e, capture_output=True, text=True)
        return out.stdout.split()[-2:] if out.stdout else out.stderr[-300:]

    def test_unset_env_is_secure(self):
        self.assertEqual(self._flags(), ["False", "False"])

    def test_explicit_flag_without_debug_stays_off(self):
        self.assertEqual(self._flags(DJANGO_DEBUG="False", ENABLE_DEV_ACCOUNT_SWITCHER="True"), ["False", "False"])

    def test_debug_true_enables_for_dev(self):
        self.assertEqual(self._flags(DJANGO_DEBUG="True"), ["True", "True"])


class SwitcherMarkup(TestCase):
    @classmethod
    def setUpTestData(cls):
        with cls.captureOnCommitCallbacks(execute=True):
            call_command("seed_demo_data")

    @override_settings(DEBUG=True, ENABLE_DEV_ACCOUNT_SWITCHER=True)
    def test_markup_present_in_dev_so_negative_test_is_meaningful(self):
        c = Client()
        c.force_login(User.objects.get(username="hr_sec"))
        self.assertIn("switch-user", c.get("/").content.decode())


class SecretKeyFailClosed(TestCase):
    """خارج DEBUG لا يُقبل مفتاح سري افتراضي، ويعمل التطوير بدونه."""

    def _run(self, **env):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "ENABLE_DEV"))}
        e.update(env, SQLITE_PATH=":memory:")
        code = ("import dotenv;dotenv.load_dotenv=lambda *a,**k:False;"
                "import config.settings as s;print('OK', s.SECRET_KEY != '')")
        return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=e, capture_output=True, text=True)

    def test_production_without_key_refuses_to_start(self):
        r = self._run(DJANGO_DEBUG="False")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ImproperlyConfigured", r.stderr)

    def test_production_with_placeholder_key_refuses(self):
        r = self._run(DJANGO_DEBUG="False", DJANGO_SECRET_KEY="replace-with-a-unique-random-key")
        self.assertNotEqual(r.returncode, 0)

    def test_production_with_real_key_starts(self):
        r = self._run(DJANGO_DEBUG="False", DJANGO_SECRET_KEY="x" * 50)
        self.assertEqual(r.returncode, 0, r.stderr[-300:])

    def test_dev_mode_starts_without_key(self):
        r = self._run(DJANGO_DEBUG="True")
        self.assertEqual(r.returncode, 0, r.stderr[-300:])
