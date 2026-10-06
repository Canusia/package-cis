"""The shared DataTables search script is shipped and loaded on every page.

DataTables 1.10's ``searchDelay`` is a throttle: the first keystroke in a
server-side table's search box fires a request at once (a search for "j", the
most expensive query a table can run). ``js/datatable_search.js`` replaces
that with a 400ms debounce and exposes ``MyceTableSearch.wireColumnInput``
for per-column boxes (package-cis#62, ported from Canusia/csn PR #37).

These tests do NOT run the script in a browser. They pin that the file is
findable by the staticfiles finders, that header-includes.html loads it
*after* DataTables (it bails out silently if ``$.fn.dataTable`` is missing),
and that the public helper templates and tenant JS call still exists.
"""
from django.contrib.staticfiles import finders
from django.template.loader import get_template
from django.test import SimpleTestCase

SCRIPT = 'js/datatable_search.js'


class DatatableSearchScriptTests(SimpleTestCase):

    def _read_static(self, path):
        found = finders.find(path)
        self.assertIsNotNone(
            found, f'staticfiles finders could not locate {path!r}')
        with open(found, encoding='utf-8') as fh:
            return fh.read()

    def _header_includes(self):
        return get_template('cis/header-includes.html').template.source

    def test_script_exposes_wire_column_input(self):
        source = self._read_static(SCRIPT)
        self.assertIn('window.MyceTableSearch', source)
        self.assertIn('wireColumnInput', source)

    def test_script_replaces_datatables_throttled_handlers(self):
        source = self._read_static(SCRIPT)
        self.assertIn("off('.DT')", source)
        self.assertIn('var DELAY = 400;', source)

    def test_header_includes_loads_the_script(self):
        self.assertIn(
            "{% static 'js/datatable_search.js' %}", self._header_includes(),
            'cis/header-includes.html must load js/datatable_search.js so '
            'every logged-in page gets the debounced search box.')

    def test_script_loads_after_datatables(self):
        source = self._header_includes()
        script_at = source.index('js/datatable_search.js')
        datatables_at = source.rindex('datatables.min.js', 0, script_at)
        self.assertLess(
            datatables_at, script_at,
            'datatable_search.js returns early when $.fn.dataTable is '
            'undefined, so it must come after the DataTables script tags.')
