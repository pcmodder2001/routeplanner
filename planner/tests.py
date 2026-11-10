from django.test import SimpleTestCase

from datetime import date
from decimal import Decimal

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
from planner.payslip import parse_payslip, reconcile_payslip

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
        self.assertEqual(b['work_type'], Job.WorkType.MANAGED_INSTALL_JUMPERS)
        self.assertEqual(b['rate'], '42.00')

    def test_work_types(self):
        self.assertEqual(
            parse_work_type('SOGEA repair l Fault at customer end')['work_type'],
            Job.WorkType.SOGEA_REPAIR,
        )
        jumpers_required = parse_work_type(
            'SOGEA new line provide | Jumpersrequired | Managed install | Standard',
            'SOGEASIM',
            'SOGEASIM',
        )
        self.assertEqual(
            jumpers_required['work_type'],
            Job.WorkType.MANAGED_INSTALL_JUMPERS,
        )
        self.assertEqual(jumpers_required['rate'], '42.00')
        # Task Name SOGEA SIM / SOGEASIM → £42
        self.assertEqual(
            parse_work_type('', 'SOGEASIM', 'SOGEASIM')['work_type'],
            Job.WorkType.MANAGED_INSTALL_JUMPERS,
        )
        self.assertEqual(
            parse_work_type('', 'SOGEA SIM')['rate'],
            '42.00',
        )
        # Task Name SOGEA Manage Install wins even if description says Jumpersrequired
        manage_name = parse_work_type(
            'SOGEA new line provide | Jumpersrequired | Managed install | Standard',
            'SOGEA Manage Install',
        )
        self.assertEqual(manage_name['work_type'], Job.WorkType.MANAGED_INSTALL)
        self.assertEqual(manage_name['rate'], '22.50')
        jumpers_exist = parse_work_type(
            'SOGEA provide | Jumpers exist | Managedinstall | Standard |LTOK',
            'SOGEA Manage Install',
        )
        self.assertEqual(
            jumpers_exist['work_type'],
            Job.WorkType.MANAGED_INSTALL,
        )
        self.assertEqual(jumpers_exist['rate'], '22.50')
        self.assertEqual(
            parse_work_type('OGEA repair at PCP')['work_type'],
            Job.WorkType.OGEA_REPAIR,
        )
        self.assertEqual(
            parse_work_type('Copper repair underground')['work_type'],
            Job.WorkType.COPPER_REPAIR,
        )
        # "Copper fault" in a SOGEA description must stay SOGEA
        sogea_copper_fault = parse_work_type(
            'SOGEA repair l Copper fault btwn PCP &premises',
            'SOGEAT2R',
            'SOGEAT2R',
        )
        self.assertEqual(
            sogea_copper_fault['work_type'],
            Job.WorkType.SOGEA_REPAIR,
        )
        self.assertEqual(sogea_copper_fault['rate'], '30.00')
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
        broadband = parse_work_type(
            'SOGEA repair l Visit assure',
            task_name='BroadBandRepair',
            job_type='BroadBandRepair',
        )
        self.assertEqual(broadband['work_type'], Job.WorkType.BROADBAND_REPAIR)
        self.assertEqual(broadband['work_type_label'], 'Broadband repair')
        self.assertEqual(broadband['rate'], '40.00')
        self.assertEqual(
            parse_work_type(
                'SOGEA repair l Fault at customer end',
                task_name='SOGEAT2R',
                job_type='SOGEAT2R',
            )['work_type'],
            Job.WorkType.SOGEA_REPAIR,
        )
        moprd = parse_work_type(
            'Overhead damage report task | Proceedwith caution',
            task_name='MOPRD',
            job_type='MOPRD',
        )
        self.assertEqual(moprd['work_type'], Job.WorkType.MOPRD)
        self.assertEqual(moprd['work_type_label'], 'MOPRD')
        self.assertEqual(moprd['rate'], '25.00')
        self.assertEqual(
            parse_work_type('', task_name='MORPD')['work_type'],
            Job.WorkType.MOPRD,
        )
        # Description alone (no MOPRD token) must not classify as MOPRD
        self.assertEqual(
            parse_work_type('Overhead damage report task')['work_type'],
            '',
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


SAMPLE_PAYSLIP = """
30/10/2026
YO-MY6021791
BBR-COM Broadband Repair Com
£ 40.00
13/11/2026
30/10/2026
YO-MY6024582
SOGEAT2R Faults
£ 30.00
13/11/2026
29/10/2026
YO-MY6021104
Copper repair
£ 30.00
13/11/2026
29/10/2026
B6-50447855A
SOGEA MI + Copper provisions
£ 42.00
13/11/2026
28/10/2026
YO-MY6010595
Copper repair
£ 30.00
13/11/2026
28/10/2026
YO-MY6006170
BBR-COM Broadband Repair Com
£ 40.00
13/11/2026
28/10/2026
B6-50424184A
SOGEA MI + Copper provisions
£ 42.00
13/11/2026
27/10/2026
B6-50420968A
SOGEA MI + Copper provisions
£ 42.00
13/11/2026
27/10/2026
B6-29419644A
SOGEA MI
£ 22.50
13/11/2026
27/10/2026
NC-NE6007410
BBR-COM Broadband Repair Com
£ 40.00
13/11/2026
26/10/2026
YO-MY5995873
SOGEAT2R Faults
£ 30.00
13/11/2026
26/10/2026
YO-MY5997076
SOGEAT2R Faults
£ 30.00
13/11/2026
23/10/2026
YO-MY5978204
BBR-COM Broadband Repair Com
£ 40.00
13/11/2026
23/10/2026
B6-29540728A
SOGEA MI
£ 22.50
13/11/2026
21/10/2026
YO-MY5969151
BBR-COM Broadband Repair Com
£ 40.00
13/11/2026
20/10/2026
B6-29439157A
SOGEA SI
£ 11.50
13/11/2026
19/10/2026
YO-MY5962277
SOGEAT2R Faults
£ 30.00
13/11/2026
19/10/2026
B6-29237834A
SOGEA SI
£ 11.50
13/11/2026
19/10/2026
B6-29445851A
SOGEA SI
£ 11.50
13/11/2026
19/10/2026
B6-29364664A
SOGEA MI
£ 22.50
13/11/2026
19/10/2026
YO-MY5936404
BBR-COM Broadband Repair Com
£ 40.00
13/11/2026
30/09/2026
20006
Incomplete Work
£ -13.00
13/11/2026
28/09/2026
20006
Incomplete Work
£ -13.00
13/11/2026
"""


def _job(**kwargs):
    defaults = {
        'location': '1 High Street',
        'job_date': date(2026, 10, 30),
        'status': Job.Status.DONE,
        'work_type': Job.WorkType.BROADBAND_REPAIR,
    }
    defaults.update(kwargs)
    return Job(**defaults)


class PayslipTests(SimpleTestCase):
    def test_parses_sample_payslip(self):
        records, errors = parse_payslip(SAMPLE_PAYSLIP)
        self.assertEqual(errors, [])
        self.assertEqual(len(records), 23)
        self.assertEqual(records[0]['reference'], 'YO-MY6021791')
        self.assertEqual(records[0]['amount'], Decimal('40.00'))
        self.assertEqual(records[0]['job_date'], date(2026, 10, 30))
        self.assertEqual(records[0]['paid_date'], date(2026, 11, 13))
        self.assertEqual(records[-1]['reference'], '20006')
        self.assertEqual(records[-1]['amount'], Decimal('-13.00'))
        total = sum((row['amount'] for row in records), Decimal('0.00'))
        self.assertEqual(total, Decimal('622.00'))

    def test_blank_lines_do_not_break_records(self):
        raw = """
        30/10/2026

        YO-MY6021791
        BBR-COM Broadband Repair Com

        £ 40.00
        13/11/2026
        """
        records, errors = parse_payslip(raw)
        self.assertEqual(errors, [])
        self.assertEqual(len(records), 1)

    def test_matches_prefix_and_pay(self):
        jobs = [
            _job(reference='MY6021791', work_type=Job.WorkType.BROADBAND_REPAIR),
            _job(
                reference='50447855A',
                job_date=date(2026, 10, 29),
                work_type=Job.WorkType.MANAGED_INSTALL_JUMPERS,
            ),
        ]
        raw = """
        30/10/2026
        YO-MY6021791
        BBR-COM Broadband Repair Com
        £ 40.00
        13/11/2026
        29/10/2026
        B6-50447855A
        SOGEA MI + Copper provisions
        £ 42.00
        13/11/2026
        """
        result = reconcile_payslip(raw, jobs)
        self.assertTrue(result['ok'])
        self.assertEqual(result['summary']['matched'], 2)
        self.assertEqual(result['summary']['issue_count'], 0)
        self.assertEqual(result['summary']['payslip_total'], '£82.00')

    def test_full_reference_stored_on_the_job_still_matches(self):
        job = _job(reference='YO-MY6021791')
        raw = """
        30/10/2026
        YO-MY6021791
        BBR-COM Broadband Repair Com
        £ 40.00
        13/11/2026
        """
        result = reconcile_payslip(raw, [job])
        self.assertEqual(result['summary']['matched'], 1)

    def test_pay_conflict_and_missing_job(self):
        job = _job(
            reference='MY6021791',
            work_type=Job.WorkType.SOGEA_REPAIR,
        )
        raw = """
        30/10/2026
        YO-MY6021791
        BBR-COM Broadband Repair Com
        £ 40.00
        13/11/2026
        29/10/2026
        YO-MY9999999
        Copper repair
        £ 30.00
        13/11/2026
        """
        result = reconcile_payslip(raw, [job])
        self.assertEqual(len(result['pay_conflicts']), 1)
        self.assertIn('£40.00', result['pay_conflicts'][0]['detail'])
        self.assertIn('£30.00', result['pay_conflicts'][0]['detail'])
        self.assertEqual(result['not_in_planner'][0]['reference'], 'YO-MY9999999')
        self.assertEqual(result['summary']['issue_count'], 2)

    def test_mpu_rate_and_pending_warning(self):
        jobs = [
            _job(
                reference='MY1',
                status=Job.Status.MPU,
                work_type=Job.WorkType.COPPER_REPAIR,
            ),
            _job(
                reference='MY2',
                job_date=date(2026, 10, 29),
                status=Job.Status.PENDING,
                work_type=Job.WorkType.BROADBAND_REPAIR,
            ),
        ]
        raw = """
        30/10/2026
        YO-MY1
        Copper repair
        £ 30.00
        13/11/2026
        29/10/2026
        YO-MY2
        BBR-COM Broadband Repair Com
        £ 40.00
        13/11/2026
        """
        result = reconcile_payslip(raw, jobs)
        self.assertEqual(len(result['pay_conflicts']), 1)
        self.assertIn('MPU', result['pay_conflicts'][0]['detail'])
        self.assertIn('£15.00', result['pay_conflicts'][0]['detail'])
        self.assertEqual(len(result['warnings']), 1)
        self.assertIn('pending', result['warnings'][0]['detail'])

    def test_date_mismatch_is_a_warning_when_pay_matches(self):
        job = _job(reference='MY6021791', job_date=date(2026, 10, 29))
        raw = """
        30/10/2026
        YO-MY6021791
        BBR-COM Broadband Repair Com
        £ 40.00
        13/11/2026
        """
        result = reconcile_payslip(raw, [job])
        self.assertEqual(result['summary']['matched'], 0)
        self.assertEqual(len(result['warnings']), 1)
        self.assertIn('29/10/2026', result['warnings'][0]['detail'])

    def test_duplicate_line_and_adjustments(self):
        job = _job(reference='MY6021791')
        raw = """
        30/10/2026
        YO-MY6021791
        BBR-COM Broadband Repair Com
        £ 40.00
        13/11/2026
        30/10/2026
        YO-MY6021791
        BBR-COM Broadband Repair Com
        £ 40.00
        13/11/2026
        30/09/2026
        20006
        Incomplete Work
        £ -13.00
        13/11/2026
        """
        result = reconcile_payslip(raw, [job])
        self.assertEqual(result['summary']['matched'], 1)
        self.assertEqual(len(result['duplicates']), 1)
        self.assertEqual(len(result['adjustments']), 1)
        self.assertEqual(result['not_in_planner'], [])
        self.assertEqual(result['summary']['payslip_total'], '£67.00')

    def test_missing_completed_job_inside_the_pay_window(self):
        jobs = [
            _job(reference='MY6021791'),
            _job(
                reference='MY-MISSING',
                job_date=date(2026, 10, 21),
                work_type=Job.WorkType.SELF_INSTALL,
            ),
            _job(
                reference='MY-TOO-EARLY',
                job_date=date(2026, 10, 1),
                work_type=Job.WorkType.SELF_INSTALL,
            ),
            _job(
                reference='MY-PENDING',
                job_date=date(2026, 10, 21),
                status=Job.Status.PENDING,
            ),
            _job(
                reference='MY-FAILED',
                job_date=date(2026, 10, 21),
                status=Job.Status.FAILED,
            ),
        ]
        raw = """
        30/10/2026
        YO-MY6021791
        BBR-COM Broadband Repair Com
        £ 40.00
        13/11/2026
        19/10/2026
        YO-MY5962277
        SOGEAT2R Faults
        £ 30.00
        13/11/2026
        30/09/2026
        20006
        Incomplete Work
        £ -13.00
        13/11/2026
        """
        result = reconcile_payslip(raw, jobs)
        missing_refs = [row['reference'] for row in result['missing_from_payslip']]
        self.assertEqual(missing_refs, ['MY-MISSING'])
        self.assertEqual(result['summary']['window_from'], '19/10/2026')
        self.assertEqual(result['summary']['window_to'], '30/10/2026')
        self.assertEqual(len(result['not_in_planner']), 1)
        self.assertEqual(result['not_in_planner'][0]['reference'], 'YO-MY5962277')
        self.assertEqual(len(result['adjustments']), 1)

    def test_sample_with_no_jobs_flags_payments_and_keeps_deductions(self):
        result = reconcile_payslip(SAMPLE_PAYSLIP, [])
        self.assertEqual(result['summary']['parsed'], 23)
        self.assertEqual(result['summary']['not_in_planner'], 21)
        self.assertEqual(result['summary']['adjustments'], 2)
        self.assertEqual(result['summary']['payslip_total'], '£622.00')
        self.assertEqual(result['summary']['window_from'], '19/10/2026')
        self.assertEqual(result['summary']['window_to'], '30/10/2026')
        self.assertEqual(result['missing_from_payslip'], [])

    def test_empty_paste(self):
        result = reconcile_payslip('   \n', [])
        self.assertFalse(result['ok'])
        self.assertIn('No payment lines', result['error'])
