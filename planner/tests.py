from django.test import SimpleTestCase

from planner.bulk_parse import (
    build_location,
    extract_uk_postcode,
    jin_to_reference,
    normalise_postcode,
    parse_bulk_jobs,
    parse_time_slot,
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
        self.assertEqual(b['reference'], '28745131A')
        self.assertEqual(b['appointment_type'], Job.AppointmentType.PM)
        self.assertIn('OULTON TERRACE', b['location'])
