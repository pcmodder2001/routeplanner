# Add MOPRD work type (£25) — overhead damage report

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('planner', '0017_reclassify_all_work_types_from_pastes'),
    ]

    operations = [
        migrations.AlterField(
            model_name='job',
            name='work_type',
            field=models.CharField(
                blank=True,
                choices=[
                    ('managed_install', 'Managed install'),
                    ('managed_jumpers', 'Managed install (jumpers)'),
                    ('self_install', 'Self install'),
                    ('sogea_repair', 'SOGEA repair'),
                    ('ogea_repair', 'OGEA repair'),
                    ('copper_repair', 'Copper repair'),
                    ('broadband_repair', 'Broadband repair'),
                    ('moprd', 'MOPRD'),
                ],
                default='',
                help_text='Parsed from task description on bulk import',
                max_length=20,
            ),
        ),
    ]
