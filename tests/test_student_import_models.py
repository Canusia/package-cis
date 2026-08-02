from django.test import TestCase
from cis.models import StudentImportBatch, StudentImportRow


class StudentImportModelTests(TestCase):
    def test_batch_and_rows_round_trip(self):
        batch = StudentImportBatch.objects.create(
            source_filename='roster.csv', scope='ce')
        self.assertEqual(batch.status, 'pending')

        row = StudentImportRow.objects.create(
            batch=batch,
            row_number=1,
            raw_data={'email': 'a@b.com', 'first_name': 'Ann'},
            status='valid',
            errors={},
            selected=True,
        )
        self.assertEqual(batch.rows.count(), 1)
        self.assertEqual(row.raw_data['first_name'], 'Ann')
        self.assertTrue(row.selected)
        self.assertEqual(row.status, 'valid')
