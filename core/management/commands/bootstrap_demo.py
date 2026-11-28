from django.core.management import call_command
from django.core.management.base import BaseCommand

from accounts.models import User


class Command(BaseCommand):
    help = "يُنشئ بيانات العرض التجريبية إن كانت قاعدة البيانات فارغة (آمن للتكرار)."

    def handle(self, *args, **options):
        if User.objects.filter(username="an").exists() and User.objects.filter(username="hr_head").exists():
            self.stdout.write("البيانات التجريبية موجودة، لا شيء للتنفيذ.")
            return
        call_command("seed_demo_data")
