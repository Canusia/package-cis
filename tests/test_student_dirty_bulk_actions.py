from django.contrib.auth.models import Group
from django.test import TestCase, RequestFactory
from django.utils import timezone

from cis.models.customuser import CustomUser
from cis.models.student import Student


class BulkMarkNotDirtyTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        self.admin = CustomUser.objects.create_superuser(username='ce', email='ce@x.com', password='p')
        self.s1 = Student.objects.create(
            user=CustomUser.objects.create_user(username='a', email='a@x.com', password='p'),
            profile_dirty_at=timezone.now(),
        )
        self.s2 = Student.objects.create(
            user=CustomUser.objects.create_user(username='b', email='b@x.com', password='p'),
            profile_dirty_at=timezone.now(),
        )

    def test_mark_not_dirty_clears_all_selected(self):
        from cis.views.student import bulk_mark_not_dirty
        req = RequestFactory().post('/x', {'ids[]': [str(self.s1.id), str(self.s2.id)]})
        req.user = self.admin
        resp = bulk_mark_not_dirty(req)
        self.assertEqual(resp.status_code, 200)
        self.s1.refresh_from_db(); self.s2.refresh_from_db()
        self.assertIsNone(self.s1.profile_dirty_at)
        self.assertIsNone(self.s2.profile_dirty_at)

    def test_mark_not_dirty_with_no_ids_returns_error(self):
        from cis.views.student import bulk_mark_not_dirty
        req = RequestFactory().post('/x')
        req.user = self.admin
        resp = bulk_mark_not_dirty(req)
        self.assertEqual(resp.status_code, 200)
        import json
        body = json.loads(resp.content)
        self.assertEqual(body.get('status'), 'error')


class BulkSetStatusPendingTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        self.admin = CustomUser.objects.create_superuser(username='ce2', email='ce2@x.com', password='p')
        self.s1 = Student.objects.create(
            user=CustomUser.objects.create_user(username='c', email='c@x.com', password='p'),
            application_status='draft',
        )

    def test_bulk_set_status_pending(self):
        from cis.views.student import bulk_set_status_pending
        req = RequestFactory().post('/x', {'ids[]': [str(self.s1.id)]})
        req.user = self.admin
        resp = bulk_set_status_pending(req)
        self.assertEqual(resp.status_code, 200)
        self.s1.refresh_from_db()
        self.assertEqual(self.s1.application_status, 'pending')
