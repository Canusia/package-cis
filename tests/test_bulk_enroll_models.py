"""Temp-storage models for the high-school-admin bulk-enroll tool."""
from django.test import TestCase

from cis.models.bulk_enroll import BulkEnrollBatch, BulkEnrollRow


class BulkEnrollModelTests(TestCase):
    def test_batch_defaults_and_row_relation(self):
        batch = BulkEnrollBatch.objects.create(source_filename='emails.csv')
        self.assertEqual(batch.status, 'pending')
        self.assertIsNotNone(batch.created_at)

        row = BulkEnrollRow.objects.create(
            batch=batch, row_number=1, email='a@example.com',
            section_label='ENG101 / 1001 (A)', status='valid', selected=True,
        )
        # related_name='rows' wires the reverse accessor used everywhere downstream.
        self.assertEqual(list(batch.rows.all()), [row])
        self.assertEqual(row.errors, {})
        self.assertEqual(row.result, '')

    def test_rows_order_by_row_number(self):
        batch = BulkEnrollBatch.objects.create()
        BulkEnrollRow.objects.create(batch=batch, row_number=2, email='b@x.com')
        BulkEnrollRow.objects.create(batch=batch, row_number=1, email='a@x.com')
        self.assertEqual([r.row_number for r in batch.rows.all()], [1, 2])
