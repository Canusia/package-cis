from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from cis.utils import get_uploaded_file


def _mock_bucket(payload):
    """Build a boto3 resource mock whose single object returns `payload` bytes."""
    body = MagicMock()
    body.read.return_value = payload

    obj = MagicMock()
    obj.get.return_value = {'Body': body}

    bucket = MagicMock()
    bucket.objects.filter.return_value = [obj]

    s3 = MagicMock()
    s3.Bucket.return_value = bucket

    session = MagicMock()
    session.resource.return_value = s3
    return session


class GetUploadedFileEncodingTests(SimpleTestCase):
    """A spreadsheet exported as Latin-1 must still be readable.

    Excel on Windows commonly writes CSVs in cp1252/latin-1, so a single
    accented name (e.g. "Velazquez" spelled with an accent) puts a byte that is
    not valid UTF-8 into the file. Returning None for the whole file means the
    caller silently imports zero rows.
    """

    def test_latin1_bytes_do_not_blank_the_whole_file(self):
        payload = 'first_name,last_name,email\r\nSusana,Vel\xe1zquez,s@x.org\r\n'.encode('latin-1')

        with patch('boto3.Session', return_value=_mock_bucket(payload)):
            content = get_uploaded_file('bulk_message/media/some.csv')

        self.assertIsNotNone(content, 'non-UTF-8 byte discarded the entire file')
        self.assertIn('first_name,last_name,email', content)
        self.assertIn('s@x.org', content)
        self.assertIn('Vel\xe1zquez', content)

    def test_utf8_bom_is_still_stripped(self):
        payload = '﻿first_name,email\r\nSusana,s@x.org\r\n'.encode('utf-8')

        with patch('boto3.Session', return_value=_mock_bucket(payload)):
            content = get_uploaded_file('bulk_message/media/some.csv')

        self.assertTrue(content.startswith('first_name'))

    def test_empty_object_still_returns_none(self):
        with patch('boto3.Session', return_value=_mock_bucket(b'')):
            self.assertIsNone(get_uploaded_file('bulk_message/media/some.csv'))
