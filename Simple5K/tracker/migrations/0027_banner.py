# Generated by Django 5.1.5 on 2025-02-10 16:25

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0026_race_notes'),
    ]

    operations = [
        migrations.CreateModel(
            name='Banner',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('subtitle', models.CharField(blank=True, max_length=400)),
                ('background_color', models.CharField(default='#ffffff', max_length=10)),
                ('image', models.ImageField(blank=True, upload_to='banners/')),
            ],
        ),
    ]
