# Generated by Django 5.1.5 on 2025-02-08 21:17

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0023_alter_runners_shirt_size'),
    ]

    operations = [
        migrations.AlterField(
            model_name='runners',
            name='race_avg_pace',
            field=models.DurationField(blank=True, null=True),
        ),
    ]
