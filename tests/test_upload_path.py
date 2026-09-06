"""Upload paths must stay within the media field's max_length.

Django 5 builds a file's extension from every suffix in the name, so
`a.b.pdf` leaves `get_available_name` a one-character root to truncate
against the ~65 character upload prefix — it empties the root and raises
SuspiciousFileOperation instead of storing the upload (#65).
"""
import types
import uuid

from django.core.files.storage import InMemoryStorage
from django.test import TestCase

from cis.utils import (
    hs_transcript_upload_path,
    student_recommendation_upload_path,
    student_supporting_doc_upload_path,
    student_tuition_assistance_upload_path,
)

# Matches the FileField default max_length the media columns use.
MAX_LENGTH = 100


class UploadPath(TestCase):

    def setUp(self):
        self.instance = types.SimpleNamespace(
            id=uuid.UUID('a79f09ed-0071-409e-9d0b-08fe5cf3aeb3')
        )
        self.storage = InMemoryStorage()

    def available_name(self, name):
        """The name Django would store, as FileField.pre_save resolves it."""
        return self.storage.get_available_name(name, max_length=MAX_LENGTH)

    def test_long_filename(self):
        name = student_supporting_doc_upload_path(
            self.instance, 'Burrow_Unofficial_MHS_Transcript_2.pdf')

        self.assertLessEqual(len(self.available_name(name)), MAX_LENGTH)

    def test_filename_with_embedded_dots(self):
        name = student_supporting_doc_upload_path(
            self.instance, 'Q_drjUVKp.Burrow_Unofficial_MHS_Transcript_2.pdf')

        stored = self.available_name(name)

        self.assertLessEqual(len(stored), MAX_LENGTH)
        self.assertTrue(stored.endswith('.pdf'))

    def test_other_upload_paths(self):
        filename = 'Q_drjUVKp.Burrow_Unofficial_MHS_Transcript_2.pdf'

        for helper in (
            student_recommendation_upload_path,
            student_tuition_assistance_upload_path,
            hs_transcript_upload_path,
        ):
            with self.subTest(upload_path=helper.__name__):
                name = helper(self.instance, filename)
                self.assertLessEqual(len(self.available_name(name)), MAX_LENGTH)
