from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="alert",
            name="resolved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
