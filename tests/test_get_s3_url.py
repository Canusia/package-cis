"""
Regression tests for cis.utils.get_s3_url key handling.

get_s3_url() hands a key to boto3's generate_presigned_url, which
percent-encodes it exactly once. So get_s3_url must pass a *fully
decoded* key. The original code called unquote() exactly once, which
left a literal "%20" in a double-encoded input — boto3 then encoded
that to "%2520", producing a broken URL for filenames with spaces.
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from cis.utils import get_s3_url

RAW = 'private/reports/x/future_class_sections-2026-05-22 15:44:48.834723.csv'
ONCE = 'private/reports/x/future_class_sections-2026-05-22%2015%3A44%3A48.834723.csv'
TWICE = 'private/reports/x/future_class_sections-2026-05-22%252015%253A44%253A48.834723.csv'


class GetS3UrlKeyDecodingTests(SimpleTestCase):
    def _key_sent_to_boto3(self, file_name):
        """Return the Key get_s3_url() passes to generate_presigned_url."""
        captured = {}
        fake_client = MagicMock()

        def fake_presigned(operation, Params=None, ExpiresIn=None):
            captured['key'] = Params['Key']
            return 'https://example.test/signed'

        fake_client.generate_presigned_url.side_effect = fake_presigned
        with patch('boto3.client', return_value=fake_client):
            get_s3_url(file_name)
        return captured.get('key')

    def test_raw_key_is_passed_through_undecoded(self):
        self.assertEqual(self._key_sent_to_boto3(RAW), RAW)

    def test_once_encoded_key_is_fully_decoded(self):
        self.assertEqual(self._key_sent_to_boto3(ONCE), RAW)

    def test_twice_encoded_key_is_fully_decoded(self):
        self.assertEqual(self._key_sent_to_boto3(TWICE), RAW)
