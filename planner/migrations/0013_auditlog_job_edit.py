# Generated manually — add job_edit audit action

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('planner', '0012_auditlog'),
    ]

    operations = [
        migrations.AlterField(
            model_name='auditlog',
            name='action',
            field=models.CharField(
                choices=[
                    ('login', 'Login'),
                    ('login_failed', 'Login failed'),
                    ('logout', 'Logout'),
                    ('register', 'Register'),
                    ('add_job', 'Add job'),
                    ('delete_job', 'Delete job'),
                    ('bulk_add', 'Bulk add jobs'),
                    ('clear_route', 'Clear route'),
                    ('plan_route', 'Plan route'),
                    ('reorder', 'Reorder jobs'),
                    ('unlock_order', 'Unlock order'),
                    ('job_complete', 'Job complete'),
                    ('job_mpu', 'Job MPU'),
                    ('job_failed', 'Job failed'),
                    ('job_skipped', 'Job skipped'),
                    ('job_reopened', 'Job reopened'),
                    ('job_edit', 'Job edit'),
                    ('update_appointment', 'Update appointment'),
                    ('update_notes', 'Update notes'),
                    ('settings_update', 'Settings update'),
                    ('view_as', 'View as engineer'),
                    ('stop_view_as', 'Stop view as'),
                    ('van_kit_scan', 'Van kit scan'),
                    ('van_kit_toggle', 'Van kit toggle'),
                    ('van_kit_reset', 'Van kit reset ordered'),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
    ]
