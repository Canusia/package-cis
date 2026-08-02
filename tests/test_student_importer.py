# webapp/cis/tests/test_student_importer.py
import csv, io
from django.contrib.auth.models import Group
from django.test import TestCase

from cis.models.highschool import HighSchool
from cis.models.customuser import CustomUser
from cis.models.student import Student
from cis.services.importers.student_importer import StudentImporter

HEADER = ('first_name,last_name,email,permanent_address_country,permanent_address,'
          'city,state,zip_code,preferred_phone,home_phone,cell_phone,legal_sex,'
          'date_of_birth,start_date,graduation_date,highschool_ceeb,same_as_permanent')
GOOD = ('Ann,Lee,ann@example.com,US,1 Main St,Spokane,WA,99201,Mobile,'
        '5095551234,5095559999,f,05/14/2012,09/01/2026,06/01/2028,480123,true')


def _reader(*rows):
    return csv.DictReader(io.StringIO('\n'.join((HEADER,) + rows)))


class StudentImporterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='student')
        cls.hs = HighSchool.objects.create(name='Central HS', code='480123')

    def test_parse_classifies_valid_duplicate_error(self):
        CustomUser.objects.create(username='dup@example.com', email='dup@example.com')
        dup = GOOD.replace('ann@example.com', 'dup@example.com')
        bad = GOOD.replace(',f,', ',,').replace('480123', '000000')  # missing legal_sex + bad ceeb
        importer = StudentImporter(scope='ce')
        batch = importer.parse_into_batch(
            _reader(GOOD, dup, bad), created_by=None, source_filename='r.csv')
        by_status = {r.row_number: r.status for r in batch.rows.all()}
        self.assertEqual(by_status[1], 'valid')
        self.assertEqual(by_status[2], 'duplicate')
        self.assertEqual(by_status[3], 'error')

    def test_in_file_duplicate_email_is_marked_duplicate(self):
        importer = StudentImporter(scope='ce')
        batch = importer.parse_into_batch(
            _reader(GOOD, GOOD), created_by=None, source_filename='r.csv')
        statuses = [r.status for r in batch.rows.all()]
        self.assertEqual(statuses, ['valid', 'duplicate'])

    def test_commit_creates_student_in_pending_verified_state(self):
        importer = StudentImporter(scope='ce')
        batch = importer.parse_into_batch(
            _reader(GOOD), created_by=None, source_filename='r.csv')
        valid_ids = [str(r.id) for r in batch.rows.filter(status='valid')]
        summary = importer.commit(batch, valid_ids)

        self.assertEqual(summary['created'], 1)
        student = Student.objects.get(user__email='ann@example.com')
        self.assertTrue(student.account_verified)
        self.assertIsNotNone(student.account_verified_on)
        self.assertIsNone(student.verification_id)
        self.assertEqual(student.application_status, 'pending')
        self.assertEqual(student.highschool, self.hs)
        self.assertTrue(student.user.has_usable_password())
        self.assertTrue(student.user.groups.filter(name='student').exists())
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'committed')

    def test_commit_skips_unselected_and_non_valid_rows(self):
        importer = StudentImporter(scope='ce')
        batch = importer.parse_into_batch(
            _reader(GOOD), created_by=None, source_filename='r.csv')
        summary = importer.commit(batch, selected_row_ids=[])
        self.assertEqual(summary['created'], 0)
        self.assertFalse(Student.objects.filter(user__email='ann@example.com').exists())

    def test_commit_does_not_send_verification_email(self):
        from django.core import mail
        importer = StudentImporter(scope='ce')
        batch = importer.parse_into_batch(
            _reader(GOOD), created_by=None, source_filename='r.csv')
        ids = [str(r.id) for r in batch.rows.filter(status='valid')]
        importer.commit(batch, ids)
        self.assertEqual(len(mail.outbox), 0)
