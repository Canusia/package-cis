import types

from django.test import SimpleTestCase

from cis.reports.datasource_mixin import ReportDataSourceMixin


def _reg(first, last, email, crn, status):
    """A minimal stand-in for a StudentRegistration row (dotted-path access)."""
    return types.SimpleNamespace(
        student=types.SimpleNamespace(
            user=types.SimpleNamespace(first_name=first, last_name=last, email=email)),
        class_section=types.SimpleNamespace(class_number=crn),
        get_status=status,  # plain attr here; a callable is tested separately
    )


class _FakeReport(ReportDataSourceMixin):
    datasource_fields = {
        'FirstName': 'student.user.first_name',
        'LastName': 'student.user.last_name',
        'email': 'student.user.email',
        'CRN': 'class_section.class_number',
        'Status': 'get_status',
    }
    email_column = 'email'
    name_columns = ['FirstName', 'LastName']
    datasource_descriptor = 'fake'

    records = []

    def recipient_queryset(self, data):
        return self.records


class ReportDataSourceMixinTests(SimpleTestCase):
    def test_recipient_columns_lists_every_token(self):
        cols = _FakeReport().recipient_columns()
        self.assertEqual(
            set(cols.values()),
            {'FirstName', 'LastName', 'email', 'CRN', 'Status'})

    def test_get_recipients_carries_all_shortcodes_and_email_list(self):
        f = _FakeReport()
        f.records = [_reg('Pat', 'Lee', 'p@x.com', '111', 'Registered')]
        row = f.get_recipients({})[0]
        self.assertEqual(row['FirstName'], 'Pat')
        self.assertEqual(row['CRN'], '111')
        self.assertEqual(row['Status'], 'Registered')
        self.assertEqual(row['email'], ['p@x.com'])   # email is a list

    def test_dedupes_by_email_and_skips_blank(self):
        f = _FakeReport()
        f.records = [
            _reg('A', 'B', 'dup@x.com', '1', 'S'),
            _reg('C', 'D', 'dup@x.com', '2', 'S'),   # duplicate email -> dropped
            _reg('E', 'F', '', '3', 'S'),            # blank email -> dropped
        ]
        self.assertEqual(len(f.get_recipients({})), 1)

    def test_callable_field_is_invoked(self):
        rec = _reg('A', 'B', 'a@x.com', '1', None)
        rec.get_status = lambda: 'CalledStatus'   # a method, not a property
        f = _FakeReport()
        f.records = [rec]
        self.assertEqual(f.get_recipients({})[0]['Status'], 'CalledStatus')

    def test_sample_row_has_all_tokens(self):
        sample = _FakeReport().sample_row()
        for token in ('FirstName', 'LastName', 'email', 'CRN', 'Status'):
            self.assertIn(token, sample)
