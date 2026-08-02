import datetime

from django.test import TestCase
from django.utils import timezone

from cis.models.teacher import TeacherCourseCertificate


class RenewalDueDateTest(TestCase):
    def _cert(self, expires=None, renewal=None):
        # Build an unsaved instance — property logic needs no DB rows.
        return TeacherCourseCertificate(
            expires_on=expires,
            renewal_required_by=renewal,
        )

    def test_renewal_due_date_prefers_renewal_required_by(self):
        c = self._cert(
            expires=datetime.date(2030, 1, 1),
            renewal=datetime.date(2029, 6, 1),
        )
        self.assertEqual(c.renewal_due_date, datetime.date(2029, 6, 1))

    def test_renewal_due_date_falls_back_to_expires_on(self):
        c = self._cert(expires=datetime.date(2030, 1, 1), renewal=None)
        self.assertEqual(c.renewal_due_date, datetime.date(2030, 1, 1))

    def test_renewal_due_date_none_when_both_unset(self):
        c = self._cert()
        self.assertIsNone(c.renewal_due_date)

    def test_is_expiring_within_true_inside_window(self):
        due = timezone.localdate() + datetime.timedelta(days=45)
        c = self._cert(expires=due)
        self.assertTrue(c.is_expiring_within(90))

    def test_is_expiring_within_false_when_already_past(self):
        due = timezone.localdate() - datetime.timedelta(days=1)
        c = self._cert(expires=due)
        self.assertFalse(c.is_expiring_within(90))

    def test_is_expiring_within_false_when_no_due_date(self):
        c = self._cert()
        self.assertFalse(c.is_expiring_within(90))
