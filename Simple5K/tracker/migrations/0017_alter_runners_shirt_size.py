# Generated by Django 5.1.3 on 2025-01-29 00:41

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0016_race_status_runners_age_runners_email_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='runners',
            name='shirt_size',
            field=models.CharField(choices=[('Extra Small', 'Extra Small'), ('Small', 'Small'), ('Medium', 'Medium'), ('Large', 'Large'), ('Extra Large', 'Extra Large'), ('XXL', 'XXL')], default='Extra Small', max_length=64),
            preserve_default=False,
        ),
    ]
