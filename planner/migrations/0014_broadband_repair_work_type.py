# Generated manually — add broadband repair work type (£40)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('planner', '0013_auditlog_job_edit'),
    ]

    operations = [
        migrations.AlterField(
            model_name='job',
            name='work_type',
            field=models.CharField(
                blank=True,
                choices=[
                    ('managed_install', 'Managed install'),
                    ('self_install', 'Self install'),
                    ('sogea_repair', 'SOGEA repair'),
                    ('ogea_repair', 'OGEA repair'),
                    ('copper_repair', 'Copper repair'),
                    ('broadband_repair', 'Broadband repair'),
                ],
                default='',
                help_text='Parsed from task description on bulk import',
                max_length=20,
            ),
        ),
    ]
