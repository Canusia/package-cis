from django.template.loader import render_to_string
from django.test import SimpleTestCase

from cis.page_messages import PageMessage


class PageMessagesPartialTests(SimpleTestCase):
    def test_renders_alert_text_and_level(self):
        html = render_to_string('cis/page_messages.html', {
            'page_messages': [PageMessage('Needs review.', level='danger')],
        })
        self.assertIn('alert alert-danger', html)
        self.assertIn('Needs review.', html)
        self.assertIn('fa fa-exclamation-triangle', html)

    def test_tile_highlight_script_only_when_tile_id_set(self):
        with_tile = render_to_string('cis/page_messages.html', {
            'page_messages': [PageMessage('x', tile_id='id_tile_students')],
        })
        self.assertIn('id_tile_students', with_tile)
        self.assertIn('border-danger', with_tile)

        without_tile = render_to_string('cis/page_messages.html', {
            'page_messages': [PageMessage('x')],
        })
        self.assertNotIn('<script>', without_tile)

    def test_empty_list_renders_nothing_substantive(self):
        html = render_to_string('cis/page_messages.html', {'page_messages': []})
        self.assertNotIn('alert', html)
