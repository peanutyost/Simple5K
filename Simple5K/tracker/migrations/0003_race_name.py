# Generated by Django 5.0.6 on 2024-05-18 01:46

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0002_rename_laps_race_laps_count_laps_attach_to_race'),
    ]

    operations = [
        migrations.AddField(
            model_name='race',
            name='name',
            field=models.CharField(default='no_name', max_length=255),
            preserve_default=False,
        ),
    ]