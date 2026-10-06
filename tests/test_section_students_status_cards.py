"""CE section Students tab: clicking a status card filters the registrations
table on its Status column (found by header) with an exact match. It used a
fixed index 3, which is Needs Mirroring in the current column list, so every
card emptied the table."""
from django.template.loader import get_template
from django.test import SimpleTestCase


class StatusCardFilterTests(SimpleTestCase):
    def setUp(self):
        self.source = get_template('cis/sections/tabs/_students.html').template.source

    def test_status_column_is_found_by_its_header(self):
        self.assertIn('thead th[data-name="status"]', self.source)
        self.assertNotIn('table.column(3)', self.source)

    def test_search_is_an_exact_match(self):
        self.assertIn("search('^' + status + '$', true, false)", self.source)
