# Generated migration for Company model and Sector.company relation

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organization", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Company",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=30, unique=True, verbose_name="كود الشركة")),
                ("name", models.CharField(max_length=200, verbose_name="اسم الشركة")),
                ("short_name", models.CharField(blank=True, max_length=100, verbose_name="الاسم المختصر")),
                ("is_holding", models.BooleanField(default=False, verbose_name="الشركة القابضة الأم")),
                ("is_active", models.BooleanField(default=True, verbose_name="مفعلة")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء")),
                (
                    "parent_company",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="subsidiaries",
                        to="organization.company",
                        verbose_name="الشركة القابضة",
                    ),
                ),
            ],
            options={
                "verbose_name": "شركة",
                "verbose_name_plural": "الشركات",
                "ordering": ["-is_holding", "id"],
            },
        ),
        migrations.AddField(
            model_name="sector",
            name="company",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="sectors",
                to="organization.company",
                verbose_name="الشركة التابعة لها",
            ),
        ),
    ]
