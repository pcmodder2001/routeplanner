from django.test import SimpleTestCase

from planner.bulk_parse import (
    build_location,
    extract_uk_postcode,
    format_revisit_note,
    jin_to_reference,
    normalise_postcode,
    parse_bulk_jobs,
    parse_time_slot,
    parse_work_type,
)
from planner.models import Job

SAMPLE = """
Jin no: YO-MY5699295
Assigned By:
Time slot: PM
Customer Name:SusanRoberts
Customer Contact No: 07850740356
Customer Alt Contact No:
Secondary Customer Alternate Contact:
Secondary Customer Contact No:
Secondary Customer Alt Contact No:
Address:Plumpton Farm,Pecket Well,Hebden Bridge,
Postcode:HX7 8QU Google Maps WAZE
Task Description:SOGEA repair l Fault at customer end
Task Name:SOGEAT2R
Tails Flag: False
Bt Siebel Order Number:4-1233192033946
Network Detail



 Watermark Photo Test
Job Details: YO-MY5699295

Jin no: B6-28745131A
Assigned By:
Time slot: PM
Customer Name:
Customer Contact No:
Customer Alt Contact No:
Secondary Customer Alternate Contact:
Secondary Customer Contact No:
Secondary Customer Alt Contact No:
Address:50, OULTON TERRACE, BRADFORD, United Kingdom, BD7 1QF
Postcode:BD7 1QF Google Maps WAZE
Task Description:SOGEA new line provide | Jumpersrequired | Managed install | Standard
Task Name:SOGEASIM
Tails Flag: False
Bt Siebel Order Number:
SOGEA new line provide | Jumpersrequired | Managed install | Standard
Network Detail


 Watermark Photo Test
"""


class BulkParseTests(SimpleTestCase):
    def test_jin_after_hyphen(self):
        self.assertEqual(jin_to_reference('YO-MY5699295'), 'MY5699295')
        self.assertEqual(jin_to_reference('B6-28745131A'), '28745131A')
        self.assertEqual(jin_to_reference('NOHYPHEN'), 'NOHYPHEN')

    def test_time_slots(self):
        self.assertEqual(parse_time_slot('PM'), Job.AppointmentType.PM)
        self.assertEqual(parse_time_slot('AM'), Job.AppointmentType.AM)
        self.assertEqual(
            parse_time_slot('ALL DAY APPOINTMENT'),
            Job.AppointmentType.ALLDAY,
        )
        self.assertEqual(
            parse_time_slot('ALL DAY APPOIMENT'),
            Job.AppointmentType.ALLDAY,
        )

    def test_location_strips_maps_noise(self):
        loc = build_location(
            'Plumpton Farm,Pecket Well,Hebden Bridge,',
            'HX7 8QU Google Maps WAZE',
        )
        self.assertEqual(
            loc,
            'Plumpton Farm,Pecket Well,Hebden Bridge, HX7 8QU',
        )

    def test_location_no_duplicate_postcode(self):
        loc = build_location(
            '50, OULTON TERRACE, BRADFORD, United Kingdom, BD7 1QF',
            'BD7 1QF Google Maps WAZE',
        )
        self.assertEqual(
            loc,
            '50, OULTON TERRACE, BRADFORD, United Kingdom, BD7 1QF',
        )

    def test_extract_postcode(self):
        self.assertEqual(extract_uk_postcode('HX7 8QU Google Maps'), 'HX7 8QU')
        self.assertEqual(
            extract_uk_postcode('50 Oulton Terrace, BD7 1QF'),
            'BD7 1QF',
        )
        self.assertEqual(normalise_postcode('hx78qu'), 'HX7 8QU')

    def test_parse_sample_pack(self):
        result = parse_bulk_jobs(SAMPLE)
        self.assertEqual(result['count'], 2)
        self.assertEqual(len(result['invalid']), 0)
        a, b = result['jobs']
        self.assertEqual(a['reference'], 'MY5699295')
        self.assertEqual(a['appointment_type'], Job.AppointmentType.PM)
        self.assertIn('HX7 8QU', a['location'])
        self.assertEqual(a['work_type'], Job.WorkType.SOGEA_REPAIR)
        self.assertEqual(a['rate'], '30.00')
        self.assertEqual(b['reference'], '28745131A')
        self.assertEqual(b['appointment_type'], Job.AppointmentType.PM)
        self.assertIn('OULTON TERRACE', b['location'])
        self.assertEqual(b['work_type'], Job.WorkType.MANAGED_INSTALL)
        self.assertEqual(b['rate'], '22.50')

    def test_work_types(self):
        self.assertEqual(
            parse_work_type('SOGEA repair l Fault at customer end')['work_type'],
            Job.WorkType.SOGEA_REPAIR,
        )
        self.assertEqual(
            parse_work_type(
                'SOGEA new line provide | Jumpersrequired | Managed install | Standard'
            )['work_type'],
            Job.WorkType.MANAGED_INSTALL,
        )
        self.assertEqual(
            parse_work_type('OGEA repair at PCP')['work_type'],
            Job.WorkType.OGEA_REPAIR,
        )
        self.assertEqual(
            parse_work_type('Copper repair underground')['work_type'],
            Job.WorkType.COPPER_REPAIR,
        )
        self.assertEqual(
            parse_work_type('SOGEA self install')['work_type'],
            Job.WorkType.SELF_INSTALL,
        )
        self.assertEqual(
            parse_work_type('SOGEA self install')['rate'],
            '11.50',
        )
        self.assertEqual(
            parse_work_type('FTTCFault is at the customer end', 'FTTCT2R')['work_type'],
            Job.WorkType.OGEA_REPAIR,
        )
        self.assertEqual(
            parse_work_type('FTTC fault at PCP', job_type='FTTCT2R')['work_type'],
            Job.WorkType.OGEA_REPAIR,
        )
        self.assertEqual(
            parse_work_type('FTTCFault is at the customer end', 'FTTCT2R')['rate'],
            '30.00',
        )

    def test_revisit_note(self):
        from datetime import date

        note = format_revisit_note(
            [
                {
                    'date': date(2026, 9, 10),
                    'status_label': 'Complete',
                    'reference': 'MY123',
                }
            ],
            today=date(2026, 9, 16),
        )
        self.assertIn('6 days ago', note)
        self.assertIn('Complete', note)
        self.assertIn('MY123', note)
        self.assertEqual(format_revisit_note([]), '')
