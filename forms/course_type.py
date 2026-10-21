"""Forms for course types and a high school's approved course types."""
import re

from django import forms
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from cis.campus_context import is_multi_campus
from cis.highschool_scope import manageable_campuses
from cis.models.course_type import CourseType, HighSchoolCourseType

_CODE_RE = re.compile(r'^[a-z0-9_]+$')
_CODE_HELP = 'Lower-case letters, digits and underscores, e.g. face_to_face.'


def _clean_code(value):
    code = (value or '').strip()
    if not _CODE_RE.match(code):
        raise ValidationError(f'Invalid code. {_CODE_HELP}')
    return code


class CourseTypeForm(forms.ModelForm):
    """Add / edit a course type on the /ce/course-types/ page.

    The code is fixed once created: the SIS importer classifies sections into
    it, so a renamed code would silently stop matching. Relabel with `name`.
    """

    class Meta:
        model = CourseType
        fields = ['code', 'name', 'description', 'approvable', 'sort_order', 'status']
        labels = {'approvable': 'Can be approved for a high school'}
        help_texts = {
            'code': f'What the SIS importer stores. {_CODE_HELP} Cannot be changed later.',
            'approvable': ('Untick for classify-only types (e.g. developmental) that '
                           'no school is approved to offer.'),
        }
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance._state.adding:
            self.fields['code'].disabled = True

    def clean_code(self):
        if not self.instance._state.adding:
            return self.instance.code
        return _clean_code(self.cleaned_data.get('code'))


class HighSchoolCourseTypeAddForm(forms.Form):
    """Approve one or more course types for a high school.

    Offers Active, approvable types the school has no all-campus approval
    for. In multi-campus mode a campus is chosen from the user's manageable
    campuses; "All campuses" is offered to superusers only. When the
    course_type_gate setting allows it, a new course type can be created and
    approved in the same save.
    """
    course_types = forms.ModelMultipleChoiceField(
        queryset=CourseType.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple, label='Course types')

    def __init__(self, *args, user=None, highschool=None, allow_create=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.highschool = highschool
        self.multi_campus = is_multi_campus()
        covered = highschool.course_type_links.filter(
            campus__isnull=True).values_list('course_type_id', flat=True)
        self.fields['course_types'].queryset = CourseType.objects.filter(
            status='Active', approvable=True).exclude(pk__in=list(covered))

        if self.multi_campus:
            self.fields['campus'] = forms.ModelChoiceField(
                queryset=manageable_campuses(user).order_by('name'),
                required=not user.is_superuser,
                empty_label='All campuses' if user.is_superuser else 'Select a campus',
                help_text='The campus whose sections this approval covers.')

        if allow_create:
            self.fields['new_code'] = forms.CharField(
                required=False, max_length=50, label='New course type code',
                help_text=_CODE_HELP)
            self.fields['new_name'] = forms.CharField(
                required=False, max_length=200, label='New course type name')

    def clean_new_code(self):
        code = (self.cleaned_data.get('new_code') or '').strip()
        if not code:
            return ''
        code = _clean_code(code)
        if CourseType.objects.filter(code=code).exists():
            raise ValidationError('A course type with this code already exists; tick it instead.')
        return code

    def clean(self):
        cleaned = super().clean()
        new_code = cleaned.get('new_code') or ''
        new_name = (cleaned.get('new_name') or '').strip()
        if bool(new_code) != bool(new_name) and 'new_code' not in self.errors:
            raise ValidationError('A new course type needs both a code and a name.')
        if not cleaned.get('course_types') and not new_code and not self.errors:
            raise ValidationError('Select at least one course type.')

        campus = cleaned.get('campus') if self.multi_campus else None
        for course_type in cleaned.get('course_types') or []:
            link = HighSchoolCourseType(
                highschool=self.highschool, course_type=course_type, campus=campus)
            if HighSchoolCourseType.objects.filter(
                    highschool=self.highschool, course_type=course_type,
                    campus=campus).exists():
                self.add_error('course_types', f'{course_type} is already approved there.')
                continue
            try:
                link.clean()
            except ValidationError as error:
                self.add_error('course_types', f'{course_type}: {error.messages[0]}')
        return cleaned

    def save_or_error(self):
        """Create the approvals (and a new type, if named) atomically.

        Returns the list of links, or None with an error added to the form.
        """
        campus = self.cleaned_data.get('campus') if self.multi_campus else None
        types = list(self.cleaned_data.get('course_types') or [])
        try:
            with transaction.atomic():
                if self.cleaned_data.get('new_code'):
                    types.append(CourseType.objects.create(
                        code=self.cleaned_data['new_code'],
                        name=self.cleaned_data['new_name'].strip()))
                return [HighSchoolCourseType.objects.create(
                    highschool=self.highschool, course_type=course_type, campus=campus)
                    for course_type in types]
        except IntegrityError:
            self.add_error(None, 'One of these course types was just approved, '
                                 'or that code was just created. Reload and try again.')
            return None


class HighSchoolCourseTypeEditForm(forms.ModelForm):
    """Edit an approval's status, and its campus in multi-campus mode."""

    class Meta:
        model = HighSchoolCourseType
        fields = ['campus', 'status']

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if not is_multi_campus():
            del self.fields['campus']
            return
        self.fields['campus'] = forms.ModelChoiceField(
            queryset=manageable_campuses(user).order_by('name'),
            required=not user.is_superuser,
            empty_label='All campuses' if user.is_superuser else 'Select a campus')

    # Overlap (HighSchoolCourseType.clean) and the unique constraints are
    # checked by ModelForm._post_clean -> instance.full_clean().

    def save_or_error(self):
        try:
            with transaction.atomic():
                return self.save()
        except IntegrityError:
            self.add_error(None, 'This course type is already approved for that campus.')
            return None
