# Generated by Django 5.0.6 on 2024-05-18 17:12

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0004_alter_laps_time_alter_race_end_time_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='runners',
            name='number',
            field=models.IntegerField(unique=True),
        ),
    ]
