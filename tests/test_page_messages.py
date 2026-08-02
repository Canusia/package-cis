from django.test import SimpleTestCase

from cis import page_messages as pm
from cis.page_messages import PageMessage, page_message, get_page_messages


class PageMessageDataclassTests(SimpleTestCase):
    def test_icon_defaults_from_level(self):
        self.assertEqual(PageMessage('x', level='success').icon, 'fa fa-check-circle')
        self.assertEqual(PageMessage('x', level='danger').icon, 'fa fa-exclamation-triangle')

    def test_explicit_icon_wins(self):
        self.assertEqual(PageMessage('x', icon='fa fa-star').icon, 'fa fa-star')

    def test_unknown_level_falls_back_to_info_icon(self):
        self.assertEqual(PageMessage('x', level='weird').icon, 'fa fa-info-circle')


class RegistryTests(SimpleTestCase):
    def setUp(self):
        # isolate the registry per test
        self._saved = dict(pm._REGISTRY)
        pm._REGISTRY.clear()
        self.addCleanup(lambda: (pm._REGISTRY.clear(), pm._REGISTRY.update(self._saved)))

    def test_provider_returning_message_is_collected(self):
        @page_message('demo', 'dashboard')
        def p(request):
            return PageMessage('hello', level='warning')
        msgs = get_page_messages('demo', 'dashboard', request=None)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].text, 'hello')
        self.assertEqual(msgs[0].level, 'warning')

    def test_provider_returning_none_is_skipped(self):
        @page_message('demo', 'dashboard')
        def p(request):
            return None
        self.assertEqual(get_page_messages('demo', 'dashboard', None), [])

    def test_provider_returning_list_is_flattened(self):
        @page_message('demo', 'dashboard')
        def p(request):
            return [PageMessage('a'), PageMessage('b')]
        self.assertEqual([m.text for m in get_page_messages('demo', 'dashboard', None)], ['a', 'b'])

    def test_failing_provider_is_isolated(self):
        @page_message('demo', 'dashboard')
        def boom(request):
            raise ValueError('nope')
        @page_message('demo', 'dashboard')
        def ok(request):
            return PageMessage('survivor')
        msgs = get_page_messages('demo', 'dashboard', None)
        self.assertEqual([m.text for m in msgs], ['survivor'])

    def test_scope_isolation_by_app_and_page(self):
        @page_message('demo', 'dashboard')
        def d(request):
            return PageMessage('dash')
        @page_message('demo', 'other')
        def o(request):
            return PageMessage('other')
        self.assertEqual([m.text for m in get_page_messages('demo', 'dashboard', None)], ['dash'])
        self.assertEqual([m.text for m in get_page_messages('demo', 'other', None)], ['other'])

    def test_unknown_scope_returns_empty(self):
        self.assertEqual(get_page_messages('nobody', 'nowhere', None), [])
