"""onBulkActionComplete must be defined somewhere globally loaded, not on a
page-specific script.

Several cis bulk actions (views/student.py, views/course.py, views/term.py,
views/section.py, actions/term.py) respond with
``{'outcome': 'call', 'fn': 'onBulkActionComplete'}``. The client-side
ActionRegistry (action_registry.js) looks the name up as ``window[fn]`` and
throws ``"onBulkActionComplete" is not defined on window`` if it isn't found.

action_registry.js is the one script loaded on every logged-in CE page (see
cis/templates/cis/logged-base.html); courses.js is only loaded on course
pages. onBulkActionComplete used to be defined only in courses.js, so any
bulk action on a non-course page (e.g. deleting a student from
/ce/students/) threw at runtime.

This test proves the definition exists in the globally-loaded served file.
It does NOT exercise the browser: it does not click a delete button, does
not run action_registry.js, and cannot catch a mismatch introduced only at
the DOM/runtime level (e.g. a typo in how `window[response.fn]` is looked
up, or a script tag removed from the template). It only pins that the
callback source lives where the registry can find it, and that courses.js
no longer shadows/duplicates it.
"""
from django.contrib.staticfiles import finders
from django.test import TestCase


class OnBulkActionCompleteIsGloballyDefinedTests(TestCase):
    def _read_static(self, path):
        found = finders.find(path)
        self.assertIsNotNone(
            found, f'staticfiles finders could not locate {path!r}')
        with open(found) as fh:
            return fh.read()

    def test_action_registry_js_defines_onBulkActionComplete(self):
        source = self._read_static('js/action_registry.js')
        self.assertIn(
            'function onBulkActionComplete(', source,
            'action_registry.js (loaded globally from logged-base.html) '
            'must define onBulkActionComplete so that '
            "{'outcome': 'call', 'fn': 'onBulkActionComplete'} responses "
            'from non-course pages (e.g. deleting a student) do not throw '
            '"is not defined on window".')

    def test_action_registry_js_exposes_it_on_window(self):
        source = self._read_static('js/action_registry.js')
        self.assertIn(
            'window.onBulkActionComplete', source,
            'ActionRegistry._handleResponse looks up window[response.fn], '
            'so the callback must be assigned onto window explicitly.')

    def test_courses_js_no_longer_defines_its_own_copy(self):
        source = self._read_static('js/courses.js')
        self.assertNotIn(
            'function onBulkActionComplete(', source,
            'onBulkActionComplete moved to the globally-loaded '
            'action_registry.js; a local copy in courses.js would only be '
            'reachable on course pages, reintroducing the bug on every '
            'other page (e.g. /ce/students/).')
