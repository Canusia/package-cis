from django.test import TestCase
from cis.serializers.credentials import (
    CredentialExpirySerializer, CredentialSummarySerializer,
)


class CredentialSerializerShapeTest(TestCase):
    def test_expiry_serializer_has_due_and_action_fields(self):
        fields = CredentialExpirySerializer().get_fields()
        for name in ('renewal_due_date', 'expires_on', 'instructor_name',
                     'highschool_name', 'course_name', 'status'):
            self.assertIn(name, fields)

    def test_summary_serializer_has_group_and_count(self):
        fields = CredentialSummarySerializer().get_fields()
        self.assertIn('count', fields)
