# Generated by Django 5.1.5 on 2025-02-10 17:01

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0027_banner'),
    ]

    operations = [
        migrations.AlterField(
            model_name='banner',
            name='background_color',
            field=models.CharField(default='#ffffff', max_length=30),
        ),
        migrations.AlterField(
            model_name='banner',
            name='subtitle',
            field=models.CharField(blank=True, max_length=1024),
        ),
    ]
