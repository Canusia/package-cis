"""The three high-school permission predicates must agree on position status.

`get_highschools()` filters `status='Active'` exactly, while
`can_manage_student_recommendation()` and `get_recommendation_highschools()`
filtered `status__iexact='active'`. A position row stored lowercase therefore
landed in the recommendation-scoped set but not the general set, and the two are
a matched pair: the dashboard message and the pending-recommendation table are
built from the recommendation set, while the student detail page those rows link
to scopes with `highschool__in=get_user_highschools(request)`. The admin was told
work was waiting and got a 404 on the way to it.

`HSAdministratorPosition.status` is choices-constrained to Active/Inactive and
`toggle_status()` writes 'Active', so a lowercase row can only arrive through an
import or a direct write — which is exactly the case these assert.
"""
from django.contrib.auth.models import Group
from django.test import TestCase

from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSAdministrator, HSAdministratorPosition, HSPosition,
)


class PositionStatusCasingTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='highschool_admin')
        self.hs = HighSchool.objects.create(name='Lincoln High', status='Active')
        user = CustomUser.objects.create(username='hsa@x.com', email='hsa@x.com')
        self.admin = HSAdministrator.objects.create(user=user)
        self.position = HSPosition.objects.create(name='Counselor')

    def _position(self, status):
        return HSAdministratorPosition.objects.create(
            hsadmin=self.admin, highschool=self.hs, position=self.position,
            status=status, meta={'manage_student_recommendation': 'Yes'},
        )

    def test_active_position_grants_both(self):
        self._position('Active')

        self.assertIn(self.hs, self.admin.get_highschools())
        self.assertIn(self.hs, self.admin.get_recommendation_highschools())
        self.assertTrue(
            self.admin.can_manage_student_recommendation(self.hs.id))

    def test_lowercase_status_is_excluded_from_all_three(self):
        """The regression: recommendation access without portal access."""
        self._position('active')

        self.assertNotIn(self.hs, self.admin.get_highschools())
        self.assertNotIn(self.hs, self.admin.get_recommendation_highschools())
        self.assertFalse(
            self.admin.can_manage_student_recommendation(self.hs.id))

    def test_inactive_position_grants_nothing(self):
        self._position('Inactive')

        self.assertNotIn(self.hs, self.admin.get_highschools())
        self.assertNotIn(self.hs, self.admin.get_recommendation_highschools())
        self.assertFalse(
            self.admin.can_manage_student_recommendation(self.hs.id))

    def test_recommendation_scope_never_exceeds_the_general_scope(self):
        """The invariant behind all of the above, stated once: an admin can
        never be shown recommendation work at a school they cannot open."""
        for status in ('Active', 'active', 'ACTIVE', 'Inactive', 'inactive'):
            with self.subTest(status=status):
                HSAdministratorPosition.objects.all().delete()
                self._position(status)

                general = set(self.admin.get_highschools())
                recommendation = set(self.admin.get_recommendation_highschools())

                self.assertTrue(recommendation.issubset(general))
                for hs in recommendation:
                    self.assertTrue(
                        self.admin.can_manage_student_recommendation(hs.id))
