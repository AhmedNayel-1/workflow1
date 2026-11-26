"""
إعدادات Django لمنظومة السكرتارية والمراسلات والأرشفة والدورة المستندية.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

_DEV_SECRET_KEY = "dev-only-insecure-key-replace-in-env-file-before-production"
_PLACEHOLDER_KEYS = {"", _DEV_SECRET_KEY, "replace-with-a-unique-random-key"}
DEBUG = os.environ.get("DJANGO_DEBUG", "False").lower() in ("1", "true", "yes")
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "").strip()
if SECRET_KEY in _PLACEHOLDER_KEYS:
    # خارج وضع التطوير لا يُسمح بمفتاح افتراضي معروف (إغلاق آمن). الاختبارات الآلية مستثناة.
    if not DEBUG and "test" not in sys.argv:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY غير مضبوط أو قيمته افتراضية. اضبط مفتاحاً سرياً فريداً في .env "
            "(أو شغّل وضع التطوير بـ DJANGO_DEBUG=True)."
        )
    SECRET_KEY = _DEV_SECRET_KEY
# المبدّل لا يعمل أبداً خارج DEBUG، حتى لو ضُبط المتغير صراحة (تحقق متعدد الطبقات).
ENABLE_DEV_ACCOUNT_SWITCHER = DEBUG and os.environ.get("ENABLE_DEV_ACCOUNT_SWITCHER", "True").lower() in ("1", "true", "yes")

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # تطبيقات المنظومة (Modular Monolith)
    "core",
    "organization",
    "accounts",
    "subjects",
    "documents",
    "workflow",
    "committees",
    "decisions",
    "audit",
    "notifications",
    "reports",
    "chat",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.system_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# إعداد قاعدة البيانات (SQLite للتطوير المحلي / SQL Server للإنتاج)
DB_ENGINE = os.environ.get("DB_ENGINE", "sqlite").lower()

if DB_ENGINE == "mssql":
    DATABASES = {
        "default": {
            "ENGINE": "mssql",
            "NAME": os.environ.get("DB_NAME", "CorrespondenceDB"),
            "USER": os.environ.get("DB_USER", ""),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "1433"),
            "OPTIONS": {
                "driver": os.environ.get("DB_ODBC_DRIVER", "ODBC Driver 17 for SQL Server"),
                "extra_params": "TrustServerCertificate=yes;",
            },
        }
    }
else:
    sqlite_path = os.environ.get("SQLITE_PATH", "db.sqlite3")
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / sqlite_path,
            "OPTIONS": {
                "timeout": 20,
            },
        }
    }

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ar"
TIME_ZONE = "Africa/Cairo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# خزينة الملفات المعزولة عن مجلدات التطبيق والويب لمنع الوصول المباشر
_vault_env = os.environ.get("SECURE_STORAGE_ROOT", "storage_vault")
SECURE_STORAGE_ROOT = (
    Path(_vault_env) if Path(_vault_env).is_absolute() else (BASE_DIR / _vault_env)
)
SECURE_STORAGE_ROOT.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_SIZE_MB = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "25"))
ALLOWED_UPLOAD_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
    ".svg",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".rtf",
    ".txt",
    ".csv",
    ".tsv",
    ".json",
    ".md",
    ".log",
    ".xml",
    ".yml",
    ".yaml",
    ".mp3",
    ".wav",
    ".ogg",
    ".m4a",
    ".mp4",
    ".webm",
    ".mov",
    ".zip",
    ".rar",
    ".7z",
    ".dwg",
    ".dxf",
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# إعدادات الأمان والجلسات
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = 60 * 60 * 8  # 8 ساعات عمل
X_FRAME_OPTIONS = "SAMEORIGIN"
SECURE_CONTENT_TYPE_NOSNIFF = True

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
