"""getfilename must not open the underlying file.

Accessing FieldFile.file opens the stored file and raises FileNotFoundError
when it is missing (e.g. a deleted upload), which 500'd the faculty
application-review page. getfilename should read .name (the stored path) only.
"""
from django.test import SimpleTestCase

from cis.templatetags.templatehelpers import getfilename


class _MissingFieldFile:
    """Mimics a Django FieldFile whose backing file is gone."""
    name = 'private/tapp/2026/05/abc/pd_letter_3.pdf'

    @property
    def file(self):
        raise FileNotFoundError(self.name)


class GetFilenameTest(SimpleTestCase):
    def test_returns_basename_without_opening_file(self):
        self.assertEqual(getfilename(_MissingFieldFile()), 'pd_letter_3.pdf')

    def test_handles_plain_string(self):
        self.assertEqual(getfilename('a/b/c.pdf'), 'c.pdf')
