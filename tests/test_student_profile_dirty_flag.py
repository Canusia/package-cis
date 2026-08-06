from datetime import timedelta
from unittest.mock import MagicMock

from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase
from django.utils import timezone

from cis.forms.student_profile import StudentEditableForm
from cis.models.customuser import CustomUser
from cis.models.student import Student


class StudentProfileDirtyFieldTests(TestCase):
    def test_profile_dirty_at_field_exists_and_is_nullable(self):
        field = Student._meta.get_field('profile_dirty_at')
        self.assertTrue(field.null, 'profile_dirty_at must be nullable')
        self.assertTrue(field.db_index, 'profile_dirty_at must be indexed (used in list filter)')


class StudentProfileDirtyDetectionTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        self.user = CustomUser.objects.create_user(
            username='stu', email='stu@example.com', password='pw',
            first_name='Old', last_name='Name',
        )
        self.student = Student.objects.create(user=self.user, application_status='draft')
        self.factory = RequestFactory()

    def _request_as(self, user):
        req = self.factory.post('/student/profile')
        req.user = user
        return req

    def _bound_form(self, request, data):
        return StudentEditableForm(
            self.student, request, data, is_locked=False,
        )

    def test_self_edit_changes_editable_field_sets_dirty_at(self):
        before = timezone.now() - timedelta(seconds=1)
        form = self._bound_form(self._request_as(self.user), {'first_name': 'New'})
        form.cleaned_data = {'first_name': 'New'}
        form._save_fields_to_models = MagicMock(side_effect=lambda **kw: setattr(self.user, 'first_name', 'New'))
        form._save_notifications = MagicMock()
        form.save(student=self.student)
        self.student.refresh_from_db()
        self.assertIsNotNone(self.student.profile_dirty_at)
        self.assertGreater(self.student.profile_dirty_at, before)

    def test_staff_edit_does_not_set_dirty_at(self):
        staff = CustomUser.objects.create_user(username='ce', email='ce@example.com', password='pw')
        form = self._bound_form(self._request_as(staff), {'first_name': 'New'})
        form.cleaned_data = {'first_name': 'New'}
        form._save_fields_to_models = MagicMock(side_effect=lambda **kw: setattr(self.user, 'first_name', 'New'))
        form._save_notifications = MagicMock()
        form.save(student=self.student)
        self.student.refresh_from_db()
        self.assertIsNone(self.student.profile_dirty_at)

    def test_self_edit_with_no_actual_change_does_not_set_dirty_at(self):
        form = self._bound_form(self._request_as(self.user), {'first_name': 'Old'})
        form.cleaned_data = {'first_name': 'Old'}
        form._save_fields_to_models = MagicMock()  # no mutation
        form._save_notifications = MagicMock()
        form.save(student=self.student)
        self.student.refresh_from_db()
        self.assertIsNone(self.student.profile_dirty_at)

    def test_self_edit_of_meta_field_sets_dirty_at(self):
        """Regression: meta-backed fields (mailing_address etc.) must trigger
        the flag. The save path mutates student.meta in place, so the
        snapshot must deep-copy to detect the change.
        """
        self.student.meta = {'mailing_address': '100 Old St'}
        self.student.save()
        form = self._bound_form(self._request_as(self.user), {})
        form.cleaned_data = {}

        def fake_save(**kw):
            # Simulate what _save_fields_to_models does: in-place dict mutation.
            self.student.meta['mailing_address'] = '200 New St'

        form._save_fields_to_models = MagicMock(side_effect=fake_save)
        form._save_notifications = MagicMock()
        form.save(student=self.student)
        self.student.refresh_from_db()
        self.assertIsNotNone(
            self.student.profile_dirty_at,
            'Meta-backed field change must set profile_dirty_at',
        )


class StudentSerializerDirtyFieldTests(TestCase):
    def test_serializer_exposes_profile_dirty_at(self):
        from cis.serializers.student import StudentSerializer

        Group.objects.get_or_create(name='student')
        user = CustomUser.objects.create_user(username='sertest', email='ser@example.com', password='pw')
        s = Student.objects.create(user=user, profile_dirty_at=timezone.now())
        data = StudentSerializer(s).data
        self.assertIn('profile_dirty_at', data)
        self.assertIsNotNone(data['profile_dirty_at'])


class StudentViewSetDirtyFilterTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        self.dirty = Student.objects.create(
            user=CustomUser.objects.create_user(
                username='dirty_user', email='dirty@x.com', password='p'
            ),
            profile_dirty_at=timezone.now(),
        )
        self.clean = Student.objects.create(
            user=CustomUser.objects.create_user(
                username='clean_user', email='clean@x.com', password='p'
            ),
        )

    def test_record_type_dirty_returns_only_dirty_students(self):
        from cis.views.student import StudentViewSet

        # StudentViewSet.get_queryset (PT-4) scopes by the 'ce' role group, not
        # is_superuser, so put the probe user in the 'ce' group for full access.
        ce_group, _ = Group.objects.get_or_create(name='ce')
        admin = CustomUser.objects.create_superuser(
            username='admin_dirty', email='admin_dirty@x.com', password='p'
        )
        admin.groups.add(ce_group)
        req = RequestFactory().get('/api/v1/student/?record_type=dirty')
        req.user = admin

        vs = StudentViewSet()
        vs.request = req
        ids = set(vs.get_queryset().values_list('id', flat=True))
        self.assertIn(self.dirty.id, ids)
        self.assertNotIn(self.clean.id, ids)
