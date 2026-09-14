# Generated manually for AuditLog

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('planner', '0011_job_mpu_status'),
    ]

    operations = [
        migrations.CreateModel(
            name='AuditLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(choices=[('login', 'Login'), ('login_failed', 'Login failed'), ('logout', 'Logout'), ('register', 'Register'), ('add_job', 'Add job'), ('delete_job', 'Delete job'), ('bulk_add', 'Bulk add jobs'), ('clear_route', 'Clear route'), ('plan_route', 'Plan route'), ('reorder', 'Reorder jobs'), ('unlock_order', 'Unlock order'), ('job_complete', 'Job complete'), ('job_mpu', 'Job MPU'), ('job_failed', 'Job failed'), ('job_skipped', 'Job skipped'), ('job_reopened', 'Job reopened'), ('update_appointment', 'Update appointment'), ('update_notes', 'Update notes'), ('settings_update', 'Settings update'), ('view_as', 'View as engineer'), ('stop_view_as', 'Stop view as'), ('van_kit_scan', 'Van kit scan'), ('van_kit_toggle', 'Van kit toggle'), ('van_kit_reset', 'Van kit reset ordered')], db_index=True, max_length=32)),
                ('message', models.CharField(blank=True, max_length=500)),
                ('details', models.JSONField(blank=True, default=dict)),
                ('job_id', models.PositiveIntegerField(blank=True, null=True)),
                ('job_reference', models.CharField(blank=True, max_length=100)),
                ('job_location', models.CharField(blank=True, max_length=255)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('user_agent', models.CharField(blank=True, max_length=400)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('actor', models.ForeignKey(blank=True, help_text='Signed-in user who performed the action', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='audit_logs_as_actor', to=settings.AUTH_USER_MODEL)),
                ('subject', models.ForeignKey(blank=True, help_text='Engineer whose data was affected (e.g. view-as target)', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='audit_logs_as_subject', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
