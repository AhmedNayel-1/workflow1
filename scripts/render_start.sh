#!/usr/bin/env bash
# أمر التشغيل على Render: هجرة القاعدة، ثم بيانات العرض إن كانت فارغة، ثم الخادم.
set -e
python manage.py migrate --noinput
python manage.py bootstrap_demo
exec waitress-serve --port="${PORT:-10000}" --threads=8 config.wsgi:application
