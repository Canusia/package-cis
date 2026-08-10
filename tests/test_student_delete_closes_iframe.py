"""Deleting a student from the detail page closes the iframe.

The student detail page renders inside the shared `#details` modal iframe. The
delete action used to return `fn: 'onActionComplete'`, whose handler ends in
`location.reload()` — reloading the detail page of a record that no longer
exists, which surfaces to the user as a page-load error inside the iframe.

It now returns `onRecordDeleted`, which closes the modal and refreshes the
index behind it. `onActionComplete` is shared by several other student actions
where reloading IS correct, so this test pins the distinction rather than the
handler body.
"""
import json
import re

from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase

from cis.models.customuser import CustomUser
from cis.models.student import Student
from cis.views.student import delete_student


class DeleteStudentPayloadTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        # Student.save() assigns the 'student' group, which init_groups
        # normally creates.
        Group.objects.get_or_create(name='student')
        self.student = Student.objects.create(
            user=CustomUser.objects.create_user(
                username='student-del@test.test',
                email='student-del@test.test', password='pw-for-tests'),
        )

    def _delete(self, student_id):
        request = self.factory.post(
            '/ce/students/actions/', {'ids[]': [str(student_id)]})
        return delete_student(request)

    def test_delete_calls_onRecordDeleted_not_onActionComplete(self):
        response = self._delete(self.student.id)
        payload = json.loads(response.content)

        self.assertEqual(payload['outcome'], 'call')
        self.assertEqual(
            payload['fn'], 'onRecordDeleted',
            'onActionComplete reloads the detail page of a deleted record, '
            'which fails inside the iframe',
        )

    def test_the_record_is_actually_deleted(self):
        self._delete(self.student.id)
        self.assertFalse(Student.objects.filter(pk=self.student.pk).exists())

    def test_no_selection_is_an_alert_not_a_delete_call(self):
        request = self.factory.post('/ce/students/actions/', {})
        payload = json.loads(delete_student(request).content)

        self.assertEqual(payload['outcome'], 'alert')
        self.assertEqual(payload['status'], 'error')


class DetailTemplateHandlerTests(TestCase):
    """The template must actually define the handler the view names."""

    TEMPLATE = 'cis/templates/cis/students/detail.html'

    def _source(self):
        from django.template.loader import get_template
        with open(get_template('cis/students/detail.html').origin.name) as fh:
            return fh.read()

    def test_onRecordDeleted_is_defined(self):
        self.assertIn('function onRecordDeleted(', self._source())

    def test_onRecordDeleted_closes_the_parent_modal(self):
        source = self._source()
        body = source.split('function onRecordDeleted(', 1)[1]
        body = body.split('function onActionComplete(', 1)[0]
        self.assertIn('window.parent.closeModal()', body)

    def test_onActionComplete_still_reloads_for_its_other_callers(self):
        source = self._source()
        body = source.split('function onActionComplete(', 1)[1]
        self.assertTrue(
            re.search(r'location\.reload\(\)', body),
            'onActionComplete is shared by other student actions that expect '
            'a reload',
        )
