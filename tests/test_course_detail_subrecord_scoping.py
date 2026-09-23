"""The course detail page must not adopt another course's sub-records.

`detail()` is campus-gated on the Course itself, but it used to fetch the
requirement named by `?course_doc_id=` / `?course_app_id=` by bare primary key,
with no check that the record belongs to the course being viewed. The POST
handler then does `record.course = <the viewed course>` and saves.

So a ce user with legitimate access to their own course could name any
requirement on any course, on any campus, and move it onto theirs -- removing
it from the original. That is cross-campus data modification, not disclosure.

The bulk actions on these same models already re-validate ids through
processable_ids(); this was the single-record path that did not.
"""
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models.course import (
    Campus,
    Cohort,
    Course,
    CourseAppRequirement,
    CourseDocumentRequirement,
)

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class _NoLoginHistoryMixin:
    """force_login's bare request crashes django_login_history's receiver."""

    @classmethod
    def setUpClass(cls):
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)


class CourseDetailSubRecordScopingTests(_NoLoginHistoryMixin, TestCase):

    def setUp(self):
        self.campus_mine = Campus.objects.create(
            name=f'Mine{_sfx()}', code=f'M{_sfx()}')
        self.campus_theirs = Campus.objects.create(
            name=f'Theirs{_sfx()}', code=f'T{_sfx()}')

        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        self.my_course = Course.objects.create(
            catalog_number=f'M{_sfx()}', title='Mine', name=f'C-{_sfx()}',
            cohort=cohort, campus=self.campus_mine, status='Active')
        self.their_course = Course.objects.create(
            catalog_number=f'T{_sfx()}', title='Theirs', name=f'C-{_sfx()}',
            cohort=cohort, campus=self.campus_theirs, status='Active')

        self.their_doc_req = CourseDocumentRequirement.objects.create(
            course=self.their_course, document='transcript')
        self.their_app_req = CourseAppRequirement.objects.create(
            course=self.their_course, name='Resume')

        self.user = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        self.user.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.user.campus = {'process_campus': [str(self.campus_mine.id)]}
        self.user.save()

        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.user)

    def _url(self):
        return reverse('cis:course', args=[self.my_course.id])

    # --- GET: another course's record must not load into my form ---

    def test_get_refuses_a_doc_req_from_another_course(self):
        resp = self.client.get(
            self._url(), {'course_doc_id': str(self.their_doc_req.id)})

        self.assertEqual(resp.status_code, 404)

    def test_get_refuses_an_app_req_from_another_course(self):
        resp = self.client.get(
            self._url(), {'course_app_id': str(self.their_app_req.id)})

        self.assertEqual(resp.status_code, 404)

    # --- POST: the actual data-modification attack ---

    def test_post_cannot_steal_a_doc_req_from_another_course(self):
        self.client.post(
            self._url() + f'?course_doc_id={self.their_doc_req.id}',
            {'action': 'save_course_doc_req', 'document': 'transcript',
             'status': 'Active', 'required': '1'})

        self.their_doc_req.refresh_from_db()
        self.assertEqual(self.their_doc_req.course_id, self.their_course.id)

    def test_post_cannot_steal_an_app_req_from_another_course(self):
        self.client.post(
            self._url() + f'?course_app_id={self.their_app_req.id}',
            {'action': 'save_course_app_req', 'name': 'Resume',
             'status': 'Active', 'required': '1'})

        self.their_app_req.refresh_from_db()
        self.assertEqual(self.their_app_req.course_id, self.their_course.id)

    # --- the legitimate path must keep working ---

    def test_my_own_doc_req_still_loads(self):
        mine = CourseDocumentRequirement.objects.create(
            course=self.my_course, document='transcript')

        resp = self.client.get(self._url(), {'course_doc_id': str(mine.id)})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.context['course_doc_req_form'].instance.pk, mine.pk)

    def test_my_own_app_req_still_loads(self):
        mine = CourseAppRequirement.objects.create(
            course=self.my_course, name='Transcript')

        resp = self.client.get(self._url(), {'course_app_id': str(mine.id)})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.context['course_app_req_form'].instance.pk, mine.pk)
