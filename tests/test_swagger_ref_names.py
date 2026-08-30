"""Guard against drf_yasg ref_name collisions.

drf_yasg derives a schema definition's ref_name from the serializer's class
name minus the "Serializer" suffix. When two distinct serializers in different
packages share a class name and neither sets Meta.ref_name, generation raises
SwaggerGenerationError and /api/docs/ stops rendering entirely — a hard 500,
not a warning.

This bit `cis` and `instructor_app`, which both define TeacherApplication,
ApplicantSchoolCourse and ApplicantCourseReviewer serializers. The convention
in this codebase is that the `cis` side takes a 'Cis'-prefixed ref_name (see
also CisCourseAppRequirement in cis/serializers/course.py and
CisCourseAdministrator in cis/serializers/faculty.py).
"""
from django.contrib.auth.signals import user_logged_in
from django.test import Client, TestCase

from ..models.customuser import CustomUser


def _login(client, user):
    """force_login without django_login_history's post_login receiver, which
    blows up on a synthetic request."""
    from django_login_history.models import post_login

    user_logged_in.disconnect(post_login)
    try:
        client.force_login(user)
    finally:
        user_logged_in.connect(post_login)


class SwaggerSchemaGenerationTests(TestCase):
    def setUp(self):
        self.superuser = CustomUser.objects.create(
            username='schema_root', email='schema_root@example.com',
            is_superuser=True, is_staff=True)

    def test_schema_renders_for_superuser(self):
        """The whole schema must generate — this is what a ref_name clash breaks."""
        client = Client()
        _login(client, self.superuser)
        response = client.get('/api/docs.json/')
        self.assertEqual(response.status_code, 200)

    def test_schema_is_not_public(self):
        """The schema maps every path, parameter and serializer in the
        deployment; it is not served to anonymous readers."""
        self.assertNotEqual(Client().get('/api/docs.json/').status_code, 200)

    def test_cis_teacher_application_serializers_declare_ref_names(self):
        """The three that collide with instructor_app must stay disambiguated."""
        from ..serializers.teacher_application import (
            ApplicantCourseReviewerSerializer,
            ApplicantSchoolCourseSerializer,
            TeacherApplicationSerializer,
        )

        self.assertEqual(
            TeacherApplicationSerializer.Meta.ref_name, 'CisTeacherApplication')
        self.assertEqual(
            ApplicantSchoolCourseSerializer.Meta.ref_name,
            'CisApplicantSchoolCourse')
        self.assertEqual(
            ApplicantCourseReviewerSerializer.Meta.ref_name,
            'CisApplicantCourseReviewer')
