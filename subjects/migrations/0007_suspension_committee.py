from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("committees", "0002_initial"),
        ("subjects", "0006_outgoing_sent_confirmation"),
    ]

    operations = [
        migrations.AddField(
            model_name="subjectsuspension",
            name="committee",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="incoming_suspensions", to="committees.committee", verbose_name="اللجنة (اختياري)"),
        ),
    ]
