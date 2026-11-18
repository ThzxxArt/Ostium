from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("proxy", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="proxyuser",
            name="uploaded_bytes",
            field=models.BigIntegerField(default=0, verbose_name="uploaded (bytes)"),
        ),
        migrations.AddField(
            model_name="proxyuser",
            name="downloaded_bytes",
            field=models.BigIntegerField(default=0, verbose_name="downloaded (bytes)"),
        ),
    ]
