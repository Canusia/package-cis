"""A student's own name must not execute in the CE admin's page.

get_verification_link and get_password_reset_link build an HTML blob by
interpolating `str(student)` -- which is the student's first and last name --
and return it as the `message` of a JsonResponse the admin's page renders as
an alert.

Those name fields are self-service input on the signup form; nothing in that
flow constrains them to plain text. So the payload is stored by the student
and executes in the *administrator's* session.

Both are bulk actions, so one crafted name renders alongside every other
selected student.
"""
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, RequestFactory

from cis.models.student import Student

User = get_user_model()

PAYLOAD = '<img src=x onerror=alert(1)>'


def _sfx():
    return uuid.uuid4().hex[:8]


class StudentLinkActionEscapingTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        Group.objects.get_or_create(name='student')

        email = f'{_sfx()}@example.com'
        user = User.objects.create_user(
            username=email, email=email, password='x',
            first_name=PAYLOAD, last_name='Smith')
        self.student = Student.objects.create(user=user)

        self.admin = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.admin.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.admin.save()

    def _request(self):
        request = self.factory.post('/ce/students/bulk/',
                                    {'ids[]': [str(self.student.id)]})
        request.user = self.admin
        return request

    def _assert_escaped(self, response):
        body = response.content.decode()
        self.assertNotIn(PAYLOAD, body)
        # The name must still be present, just inert.
        self.assertIn('Smith', body)

    def test_verification_link_escapes_the_student_name(self):
        from cis.views.student import get_verification_link

        self.student.account_verified = False
        self.student.save()

        self._assert_escaped(get_verification_link(self._request()))

    def test_password_reset_link_escapes_the_student_name(self):
        from cis.views.student import get_password_reset_link

        self.student.account_verified = True
        self.student.save()

        self._assert_escaped(get_password_reset_link(self._request()))
