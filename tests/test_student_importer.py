"""StudentImporter against cis.tests.fake_tenant (package-cis#57)."""
import csv
import io

from django.contrib.auth.models import Group
from django.core import mail
from django.test import TestCase, override_settings

from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.student import Student
from cis.services.importers.student_importer import StudentImporter

FAKE_TENANT = 'cis.tests.fake_tenant'

HEADER = ('first_name,last_name,email,date_of_birth,fake_color,'
          'fake_meta_note,highschool_ceeb')
GOOD = 'Ann,Lee,ann@example.com,05/14/2012,red,hi,480123'


def _reader(*rows, header=HEADER):
    return csv.DictReader(io.StringIO('\n'.join((header,) + rows)))


@override_settings(TENANT_SERVICES_APP=FAKE_TENANT)
class StudentImporterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='student')
        cls.hs = HighSchool.objects.create(name='Central HS', code='480123')

    def test_header_errors_name_tenant_required_columns(self):
        importer = StudentImporter(scope='ce')
        self.assertEqual(importer.header_errors(HEADER.split(',')), [])
        errors = importer.header_errors(
            [c for c in HEADER.split(',') if c != 'fake_color'])
        self.assertEqual(errors, ['Missing required column: fake_color'])
        # an optional tenant column may be left out
        self.assertEqual(importer.header_errors(
            [c for c in HEADER.split(',') if c != 'fake_meta_note']), [])

    def test_parse_classifies_valid_duplicate_error(self):
        CustomUser.objects.create(username='dup@example.com', email='dup@example.com')
        dup = GOOD.replace('ann@example.com', 'dup@example.com')
        # missing required tenant field + unknown CEEB
        bad = GOOD.replace(',red,', ',,').replace('480123', '000000')
        importer = StudentImporter(scope='ce')
        batch = importer.parse_into_batch(
            _reader(GOOD, dup, bad), created_by=None, source_filename='r.csv')
        rows = {r.row_number: r for r in batch.rows.all()}
        self.assertEqual(rows[1].status, 'valid')
        self.assertEqual(rows[2].status, 'duplicate')
        self.assertEqual(rows[3].status, 'error')
        self.assertIn('fake_color', rows[3].errors)
        self.assertIn('highschool', rows[3].errors)

    def test_in_file_duplicate_email_is_marked_duplicate(self):
        importer = StudentImporter(scope='ce')
        batch = importer.parse_into_batch(
            _reader(GOOD, GOOD), created_by=None, source_filename='r.csv')
        statuses = [r.status for r in batch.rows.order_by('row_number')]
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
        # the tenant's own fields reach the record through its save()
        self.assertEqual(student.meta.get('fake_color'), 'red')
        self.assertEqual(student.meta.get('fake_meta_note'), 'hi')
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
        importer = StudentImporter(scope='ce')
        batch = importer.parse_into_batch(
            _reader(GOOD), created_by=None, source_filename='r.csv')
        ids = [str(r.id) for r in batch.rows.filter(status='valid')]
        importer.commit(batch, ids)
        self.assertEqual(len(mail.outbox), 0)
