# Split managed install into Jumpers exist (£22.50) and Jumpers required (£42)

from django.db import migrations, models


def forwards_existing_to_jumpers(apps, schema_editor):
    """Jobs stored as managed_install were paid at £42 — keep that band."""
    Job = apps.get_model('planner', 'Job')
    Job.objects.filter(work_type='managed_install').update(work_type='managed_jumpers')


def backwards_jumpers_to_managed(apps, schema_editor):
    Job = apps.get_model('planner', 'Job')
    Job.objects.filter(work_type='managed_jumpers').update(work_type='managed_install')


class Migration(migrations.Migration):

    dependencies = [
        ('planner', '0014_broadband_repair_work_type'),
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
                ],
                default='',
                help_text='Parsed from task description on bulk import',
                max_length=20,
            ),
        ),
        migrations.RunPython(forwards_existing_to_jumpers, backwards_jumpers_to_managed),
    ]
