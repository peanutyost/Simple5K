# Generated by Django 5.0.6 on 2024-05-18 00:58

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0001_initial'),
    ]

    operations = [
        migrations.RenameField(
            model_name='race',
            old_name='laps',
            new_name='laps_count',
        ),
        migrations.AddField(
            model_name='laps',
            name='attach_to_race',
            field=models.ForeignKey(default=1, on_delete=django.db.models.deletion.CASCADE, to='tracker.race'),
            preserve_default=False,
        ),
    ]
