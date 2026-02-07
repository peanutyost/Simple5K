# Generated manually for making runners.gender required

from django.db import migrations, models


def backfill_null_gender(apps, schema_editor):
    """Set existing NULL gender to 'male' so the column can be made NOT NULL."""
    runners = apps.get_model('tracker', 'runners')
    runners.objects.filter(gender__isnull=True).update(gender='male')


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0040_runners_created_at_runners_signup_confirmation_sent_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_null_gender, noop),
        migrations.AlterField(
            model_name='runners',
            name='gender',
            field=models.CharField(choices=[('male', 'Male'), ('female', 'Female')], max_length=50),
        ),
    ]
