"""A declared `initial` must survive a blank value on the instance.

`_populate_initial_from_instance` assigned unconditionally, so an empty
attribute on the student (or its user) overwrote the field's declared
`initial` with ''. `BoundField.value()` reads `form.initial.get(name,
field.initial)` — once the key is present, the declaration loses.

Harmless on a visible optional field, fatal on a hidden required one: SCCC's
`permanent_address_country` is declared `initial='US'`, `HiddenInput`,
required, and every new signup has a blank `user.country`. The rendered input
came through empty and the form failed with "This field is required" naming a
control the student cannot see — no new student could complete signup. See
ewu#44.
"""
from django import forms
from django.contrib.auth.models import Group
from django.test import TestCase

from cis.forms.utils import MetaFormMixin, with_meta
from cis.models import CustomUser
from cis.models.student import Student


class DeclaredInitialForm(MetaFormMixin, forms.Form):
    """Mirrors the shape that broke: hidden, required, declared default."""

    permanent_address_country = with_meta(
        forms.CharField(
            initial='US',
            widget=forms.HiddenInput(),
            required=True,
        ),
        target='user',
        path='country',
    )
    nickname = with_meta(
        forms.CharField(required=False, initial='Sam'),
        target='meta',
        path='nickname',
    )

    def __init__(self, student=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if not getattr(field, 'storage_path', None):
                field.storage_path = name
        if student is not None:
            self._populate_initial_from_instance(student)


class DeclaredInitialPreservedTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        self.user = CustomUser.objects.create_user(
            username='s', email='s@example.com', password='x')
        self.student = Student.objects.create(user=self.user)

    def test_blank_user_attribute_does_not_clobber_declared_initial(self):
        self.user.country = ''
        self.user.save()

        form = DeclaredInitialForm(student=self.student)

        self.assertEqual(form['permanent_address_country'].value(), 'US')

    def test_missing_meta_key_does_not_clobber_declared_initial(self):
        # A populated dict that simply lacks the key — an empty `meta` is
        # already short-circuited by the `and student.meta` guard, so it never
        # exercised the assignment.
        self.student.meta = {'some_other_field': 'x'}
        self.student.save()

        form = DeclaredInitialForm(student=self.student)

        self.assertEqual(form['nickname'].value(), 'Sam')

    def test_hidden_required_field_with_declared_initial_validates(self):
        """The signup blocker itself: the field renders empty, so the POST
        carries an empty value and a required field rejects it."""
        self.user.country = ''
        self.user.save()

        form = DeclaredInitialForm(student=self.student)
        rendered_default = form['permanent_address_country'].value()

        bound = DeclaredInitialForm(
            student=self.student,
            data={'permanent_address_country': rendered_default or ''})

        self.assertTrue(bound.is_valid(), bound.errors)

    def test_populated_instance_value_still_wins_over_declared_initial(self):
        """The fix must not turn the declaration into an override — a student
        who really is in Canada keeps CA."""
        self.user.country = 'CA'
        self.user.save()

        form = DeclaredInitialForm(student=self.student)

        self.assertEqual(form['permanent_address_country'].value(), 'CA')

    def test_blank_instance_value_still_wins_when_nothing_is_declared(self):
        """No declared initial means the instance is the only source, blank
        included — otherwise a cleared field would resurrect stale data."""

        class NoDeclaredInitialForm(DeclaredInitialForm):
            permanent_address_country = with_meta(
                forms.CharField(required=False),
                target='user',
                path='country',
            )

        self.user.country = ''
        self.user.save()

        form = NoDeclaredInitialForm(student=self.student)

        self.assertEqual(form['permanent_address_country'].value(), '')
