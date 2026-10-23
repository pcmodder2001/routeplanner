# Reclassify all job work types from BulkPasteLog (newest paste wins per ref)

from django.db import migrations


def reclassify_from_pastes(apps, schema_editor):
    Job = apps.get_model('planner', 'Job')
    BulkPasteLog = apps.get_model('planner', 'BulkPasteLog')

    from planner.bulk_parse import normalise_reference, parse_bulk_jobs

    ref_to_type: dict[str, str] = {}
    for paste in BulkPasteLog.objects.order_by('created_at'):
        parsed = parse_bulk_jobs(paste.raw_text or '')
        for item in parsed.get('jobs') or []:
            ref = normalise_reference(item.get('reference') or '')
            wt = item.get('work_type') or ''
            if ref and wt:
                ref_to_type[ref] = wt

    for job in Job.objects.all():
        ref = normalise_reference(job.reference or '')
        correct = ref_to_type.get(ref)
        if correct and job.work_type != correct:
            job.work_type = correct
            job.save(update_fields=['work_type'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('planner', '0016_reclassify_managed_from_pastes'),
    ]

    operations = [
        migrations.RunPython(reclassify_from_pastes, noop_reverse),
    ]
