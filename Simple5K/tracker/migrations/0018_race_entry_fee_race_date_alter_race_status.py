# Generated by Django 5.1.3 on 2025-01-30 19:27

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0017_alter_runners_shirt_size'),
    ]

    operations = [
        migrations.AddField(
            model_name='race',
            name='Entry_fee',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='race',
            name='date',
            field=models.DateField(default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='race',
            name='status',
            field=models.CharField(choices=[('signup_closed', 'Sign Up Closed'), ('signup_open', 'Sign Up Open'), ('in_progress', 'In Progress'), ('completed', 'Completed')], max_length=20),
        ),
    ]
