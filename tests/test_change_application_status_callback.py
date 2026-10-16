"""change_application_status must answer with a callback that exists on every
page it is offered on (package-cis#78).

The action is registered with scope=['detail', 'bulk'], so it runs from both
cis/students/detail.html (ActionRegistry.doAction) and /ce/students
(ActionRegistry.doBulkAction). Both post the same {action, ids[]} payload, so
the view cannot tell them apart. It used to return fn='onActionComplete', which
only the detail page defines; on the list page action_registry.js threw
'"onActionComplete" is not defined on window' after the status had saved.

onBulkActionComplete is defined globally by action_registry.js (pinned by
test_onbulkactioncomplete_registry), so it is safe on both pages.

The second test pins the general rule for every student action registered for
both scopes, so a future dual-scope action cannot reintroduce the bug.
"""
import inspect
import json
import re

from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase

from cis.models.customuser import CustomUser
from cis.models.student import Student


class ChangeApplicationStatusCallbackTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        self.admin = CustomUser.objects.create_superuser(
            username='ce78', email='ce78@x.com', password='p')
        self.s1 = Student.objects.create(
            user=CustomUser.objects.create_user(
                username='s78a', email='s78a@x.com', password='p'),
            application_status='draft',
        )
        self.s2 = Student.objects.create(
            user=CustomUser.objects.create_user(
                username='s78b', email='s78b@x.com', password='p'),
            application_status='draft',
        )

    def _post(self, ids):
        from cis.views.student import change_application_status
        req = RequestFactory().post('/x', {
            'action': 'change_application_status',
            'action_confirmed': '1',
            'ids[]': [str(i) for i in ids],
            'application_status': 'pending',
        })
        req.user = self.admin
        return change_application_status(req)

    def test_bulk_confirm_returns_global_callback(self):
        resp = self._post([self.s1.id, self.s2.id])
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.content)
        self.assertEqual(body['outcome'], 'call')
        self.assertEqual(
            body['fn'], 'onBulkActionComplete',
            'onActionComplete exists only on the student detail page; the '
            '/ce/students list page would throw "not defined on window".')
        self.assertIn('2 student(s)', body['args']['message'])
        self.s1.refresh_from_db()
        self.s2.refresh_from_db()
        self.assertEqual(self.s1.application_status, 'pending')
        self.assertEqual(self.s2.application_status, 'pending')

    def test_single_record_confirm_returns_global_callback(self):
        # Detail page (or a one-row list selection): same payload shape.
        resp = self._post([self.s1.id])
        body = json.loads(resp.content)
        self.assertEqual(body['fn'], 'onBulkActionComplete')


class DualScopeStudentActionsUseGlobalCallbackTests(TestCase):
    def test_no_detail_and_bulk_action_returns_page_only_callback(self):
        import cis.views.student

        # Read each dual-scope action's source, so the check does not depend
        # on the action registry's internals.
        offenders = []
        src = inspect.getsource(cis.views.student)
        pattern = re.compile(
            r"@student_actions\.action\((?P<args>.*?)\)\s*\n"
            r"(?:@.*\n)*def (?P<name>\w+)\(.*?\n(?P<body>.*?)(?=\n@|\ndef |\nclass |\Z)",
            re.S)
        for m in pattern.finditer(src):
            scope = re.search(r"scope\s*=\s*\[([^\]]*)\]", m.group('args'))
            scopes = re.findall(r"'(\w+)'", scope.group(1)) if scope else []
            if 'detail' in scopes and 'bulk' in scopes:
                if re.search(r"'fn'\s*:\s*'onActionComplete'", m.group('body')):
                    offenders.append(m.group('name'))
        self.assertEqual(
            offenders, [],
            'Actions offered on both the detail and list pages must not '
            'answer with onActionComplete (detail-page only).')
