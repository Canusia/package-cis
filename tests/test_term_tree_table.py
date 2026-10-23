"""Tree order for Term DataTables ships in cis (#112): the Python helpers that
a tenant's terms-table config uses, the shared term_tree.js, and the two cis
templates that load it ahead of the tenant's partial."""
import os
import re

from django.contrib.staticfiles import finders
from django.template.loader import get_template
from django.test import SimpleTestCase

from cis.services.term_hierarchy import (
    TREE_COLUMN_HEADER, TREE_COLUMN_KEY, tree_table_opts,
)

SCRIPT = 'cis/js/term_tree.js'
TEMPLATES = ('cis/term/terms.html', 'cis/term/tabs/academic_year/_terms.html')


class TreeTableOptsTests(SimpleTestCase):
    def test_tree_column_index(self):
        self.assertEqual(
            tree_table_opts(['term.code', 'term.name', TREE_COLUMN_KEY]),
            {'treeColumn': 2})

    def test_no_tree_column(self):
        self.assertEqual(tree_table_opts(['term.code']), {'treeColumn': None})

    def test_header_sorts_on_the_feed_annotation(self):
        # data-name must be the annotation the terms feed adds (views/term.py).
        self.assertIn('data-data="tree_position"', TREE_COLUMN_HEADER)
        self.assertIn('data-name="tree_position"', TREE_COLUMN_HEADER)


class TermTreeScriptTests(SimpleTestCase):
    def _source(self):
        path = finders.find(SCRIPT)
        self.assertTrue(path and os.path.exists(path), f'{SCRIPT} not found')
        with open(path) as fh:
            return fh.read()

    def test_exposes_api(self):
        src = self._source()
        self.assertIn('window.MyCETermTree', src)
        for name in ('indent', 'render', 'button', 'applyState',
                     'columnDef', 'exportOptions', 'STATE_VERSION'):
            self.assertRegex(src, rf'\b{name}\s*:', name)

    def test_state_version_matches_tenant_copies(self):
        # Tenant copies stamped treeVersion = 1; a different value would reset
        # everyone's saved sort again on upgrade.
        src = self._source()
        self.assertRegex(src, r'var STATE_VERSION = 1;')
        self.assertIn('data.treeVersion', src)

    def test_templates_load_script_before_tenant_partial(self):
        for name in TEMPLATES:
            source = get_template(name).template.source
            script = source.find(f"{{% static '{SCRIPT}' %}}")
            include = re.search(r'{%\s*include\s+\w+\.partial_template', source)
            self.assertNotEqual(script, -1, name)
            self.assertIsNotNone(include, name)
            self.assertLess(script, include.start(), name)
