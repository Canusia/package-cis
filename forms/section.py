from django import forms
from django.forms.formsets import BaseFormSet

from django.db import models
from django.db.models import Q

from django.forms import ValidationError
from django.utils.translation import gettext_lazy as _

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.models.section import (
    SectionNumber,
    ClassSection, ClassSectionSyllabi,
    StudentRegistration,
    StudentDropRequest
)
from cis.utils import REGISTRATION_TYPES, YES_NO_SELECT_OPTIONS, YES_NO_OPTIONS

from cis.models.highschool import HighSchool
from cis.models.term import Term
from cis.models.student import Student


SYLLABUS_REVIEW_METRICS = [
    ('1', 'The syllabus clearly indicates that it is for an OCC course'),
    ('2', 'Instructor, term (semester or full year), and course name and number'),
    ('3', 'Instructor contact information'),
    ('4', 'Course description with prerequisites, must exactly match OCC\'s course description'),
    ('5', 'Learning outcomes, which must exactly match the learning outcomes from the official course description'),
    ('6', 'Methods of evaluation (grading breakdown)'),
    ('7', 'Topic outline'),
    ('8', 'Department approved texts and supplementary readings, which must match the oficial course outline unless otherwise indicated in the official outline and approved by the related department'),
    ('9', 'Academic Integrity statment'),
    ('10', 'Statement on diversity and inclusion')
]


class StudentClassChangeForm(forms.Form):
    registration_ids = forms.MultipleChoiceField(
        required=False,
        label='Records to Update',
        widget=forms.CheckboxSelectMultiple,
        choices=[]
    )
    
    new_crn_term = forms.ModelChoiceField(
        queryset=None,
        label='New CRN Term'
    )

    new_crn = forms.CharField(
        required=True,
        help_text='CRN of class section to move selected student(s) to',
        label='CRN'
    )

    mirror_to_sis = forms.ChoiceField(
        required=False,
        choices=YES_NO_OPTIONS,
        label='Mirror this to SIS',
        widget=forms.HiddenInput
    )

    action = forms.CharField(
        widget=forms.HiddenInput
    )

    def __init__(self, registration_ids=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['new_crn_term'].queryset = Term.objects.all().order_by("-code")
        
        self.fields['action'].initial = kwargs.get('action', 'change_class_section')
        if registration_ids:
            registrations = StudentRegistration.objects.filter(
                id__in=registration_ids
            )

            registration_choices = []
            for registration in registrations:
                registration_choices.append(
                    (
                        registration.id,
                        f"{registration.student} - {registration.class_section} ({registration.status})"
                    )
                )
            self.fields['registration_ids'].choices = registration_choices
            self.fields['registration_ids'].initial = registration_ids
        else:
            registration_choices = []
            for regis_id in kwargs.get('data').getlist('registration_ids'):
                registration_choices.append(
                    (regis_id, regis_id)
                )

            self.fields['registration_ids'].choices = registration_choices
            self.fields['registration_ids'].required = False

    def clean(self):
        cleaned_data = super().clean()

        try:
            ClassSection.objects.get(
                term=cleaned_data.get('new_crn_term').id,
                class_number=cleaned_data.get('new_crn')
            )
        except:
            raise ValidationError('Unable to find class section', code='invalid')
        return cleaned_data

    def save(self, request=None, allowed_ids=None):
        """`allowed_ids` MUST be the caller's campus-authorized id set (from
        processable_ids); only the intersection is moved. The form's
        `registration_ids` choices are built from the submitted POST data, so
        authorization cannot be enforced here — the view re-scopes and passes
        the result. `None` means "no restriction" (trusted callers only)."""
        data = self.cleaned_data

        new_class_section = ClassSection.objects.get(
            term=data.get('new_crn_term').id,
            class_number=data.get('new_crn')
        )

        registration_ids = data.get('registration_ids')
        if allowed_ids is not None:
            allowed = {str(a) for a in allowed_ids}
            registration_ids = [i for i in registration_ids if str(i) in allowed]
        for regis_id in registration_ids:
            try:
                registration = StudentRegistration.objects.get(
                    id=regis_id
                )

                registration.student.add_note(
                    None if not request else request.user, 
                    f'Moving from {registration.class_section} to {new_class_section}'
                )

                registration.class_section = new_class_section
                if data.get('mirror_to_sis') == '1':
                    registration.needs_mirroring = True
                else:
                    registration.needs_mirroring = False


                registration.save()
            except Exception as e:
                ...

class BulkRosterStatusChangeForm(forms.Form):
    record_ids = forms.MultipleChoiceField(
        required=False,
        label='Records to Update',
        widget=forms.CheckboxSelectMultiple,
        choices=[]
    )
    
    new_roster_status = forms.ChoiceField(
        required=True,
        label='New Roster Status',
        choices=ClassSection.ROSTER_STATUS
    )
    
    email_instructors = forms.ChoiceField(
        required=False,
        label='Do you want to send an email to the instructor(s)',
        choices=YES_NO_SELECT_OPTIONS,
        help_text=''
    )

    action = forms.CharField(
        widget=forms.HiddenInput,
        initial='change_roster_status'
    )

    def __init__(self, record_ids=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if record_ids:
            records = ClassSection.objects.filter(
                id__in=record_ids
            )

            record_choices = []
            for record in records:
                record_choices.append(
                    (
                        record.id,
                        f"{record} / {record.teacher} ({record.roster_status})"
                    )
                )
                
            self.fields['record_ids'].choices = record_choices
            self.fields['record_ids'].initial = record_ids
        else:
            record_choices = []
            for record_id in kwargs.get('data').getlist('record_ids'):
                record_choices.append(
                    (record_id, record_id)
                )

            self.fields['record_ids'].choices = record_choices
            self.fields['record_ids'].required = False

    def save(self, request=None):
        data = self.cleaned_data
        
        records = ClassSection.objects.filter(
            id__in=data.get('record_ids')
        )

        # skip initiating signal
        records.update(
            roster_status=data.get('new_roster_status')
        )

        for record in records:
            note_message = f'Updated roster status to {record.roster_status}'
            if data.get('email_instructors') == '1':
                record.notify_teacher_on_roster_verification()
                note_message += ' and sent email'

            record.add_note(request.user, note_message)

        return records

class BulkRegistrationTermChangeForm(forms.Form):
    record_ids = forms.MultipleChoiceField(
        required=False,
        label='Records to Update',
        widget=forms.CheckboxSelectMultiple,
        choices=[]
    )

    new_registration_term = forms.ModelChoiceField(
        required=True,
        label='New Registration Term',
        queryset=Term.objects.all().order_by('-code')
    )

    action = forms.CharField(
        widget=forms.HiddenInput,
        initial='change_registration_term'
    )

    def __init__(self, record_ids=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if record_ids:
            records = ClassSection.objects.filter(
                id__in=record_ids
            )

            record_choices = []
            for record in records:
                record_choices.append(
                    (
                        record.id,
                        f"{record} / {record.teacher} ({record.registration_term})"
                    )
                )
                
            self.fields['record_ids'].choices = record_choices
            self.fields['record_ids'].initial = record_ids
        else:
            record_choices = []
            for record_id in kwargs.get('data').getlist('record_ids'):
                record_choices.append(
                    (record_id, record_id)
                )

            self.fields['record_ids'].choices = record_choices
            self.fields['record_ids'].required = False

    def save(self, request=None):
        data = self.cleaned_data
        
        records = ClassSection.objects.filter(
            id__in=data.get('record_ids')
        )

        # skip initiating signal
        records.update(
            registration_term=data.get('new_registration_term')
        )

        for record in records:
            note_message = f'Updated registration term to {record.registration_term}'
            record.add_note(request.user, note_message)

        return records

class SyllabiNeedsUpdateForm(forms.Form):
    action = forms.CharField(
        widget=forms.HiddenInput
    )

    class_section_id = forms.CharField(
        widget=forms.HiddenInput
    )

    review = forms.MultipleChoiceField(
        choices = SYLLABUS_REVIEW_METRICS,
        widget=forms.CheckboxSelectMultiple(),
        label='In order to document the equivalency of courses, all syllabi must include the following items. Please check all the items that meet the requirement.'
    )
    note = forms.CharField(
        widget=forms.Textarea,
        required=True,
        help_text='Please describe required updates. This will be sent to the instructor as an email.'
    )

    def __init__(self, class_section_id, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['action'].initial = 'mark_syllabi_as_needs_update'
        self.fields['class_section_id'].initial = class_section_id

    def save(self, request, commit=True):
        data = self.cleaned_data

        class_section = ClassSection.objects.get(pk=data.get('class_section_id'))
        class_section.mark_syllabi_as_needs_update(
            data.get('note'),
            request.user
        )

        return class_section
        
class StudentRegistrationChangeStatusForm(forms.Form):
    registration_ids = forms.MultipleChoiceField(
        required=False,
        label='Records to Update',
        widget=forms.CheckboxSelectMultiple,
        choices=[]
    )
    
    new_status = forms.ChoiceField(
        required=True,
        label='Change Registration Status To',
        choices=StudentRegistration.STATUS_OPTIONS
    )

    needs_mirroring = forms.BooleanField(
        label='Needs Mirroring',
        required=False
    )

    action = forms.CharField(
        widget=forms.HiddenInput
    )

    def __init__(self, registration_ids=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['action'].initial = kwargs.get('action', 'change_status')
        if registration_ids:
            registrations = StudentRegistration.objects.filter(
                id__in=registration_ids
            )

            registration_choices = []
            for registration in registrations:
                registration_choices.append(
                    (
                        registration.id,
                        f"{registration.student} - {registration.class_section} ({registration.sexy_status})"
                    )
                )
            self.fields['registration_ids'].choices = registration_choices
            self.fields['registration_ids'].initial = registration_ids
        else:
            registration_choices = []
            for regis_id in kwargs.get('data').getlist('registration_ids'):
                registration_choices.append(
                    (regis_id, regis_id)
                )

            self.fields['registration_ids'].choices = registration_choices
            self.fields['registration_ids'].required = False

    def save(self, request=None, allowed_ids=None):
        """`allowed_ids` MUST be the caller's campus-authorized id set (from
        processable_ids); only the intersection is updated. The form's
        `registration_ids` choices are built from the submitted POST data, so
        authorization cannot be enforced here — the view re-scopes and passes
        the result. `None` means "no restriction" (trusted callers only)."""
        data = self.cleaned_data

        new_status = data.get('new_status')
        registration_ids = data.get('registration_ids')
        if allowed_ids is not None:
            allowed = {str(a) for a in allowed_ids}
            registration_ids = [i for i in registration_ids if str(i) in allowed]
        for regis_id in registration_ids:
            try:
                registration = StudentRegistration.objects.get(
                    id=regis_id
                )

                registration.status = new_status
                registration.needs_mirroring = data.get('needs_mirroring', False)

                registration.save()
            except Exception as e:
                ...


class SetNeedsMirroringForm(forms.Form):
    """Bulk-set the `needs_mirroring` flag on the selected registrations."""

    registration_ids = forms.MultipleChoiceField(
        required=False,
        label='Records to Update',
        widget=forms.CheckboxSelectMultiple,
        choices=[]
    )

    needs_mirroring = forms.ChoiceField(
        required=True,
        label='Set Needs Mirroring To',
        choices=[('1', 'Yes'), ('0', 'No')]
    )

    action = forms.CharField(
        widget=forms.HiddenInput
    )

    def __init__(self, registration_ids=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['action'].initial = 'set_needs_mirroring'
        if registration_ids:
            registrations = StudentRegistration.objects.filter(
                id__in=registration_ids
            )
            self.fields['registration_ids'].choices = [
                (r.id, f"{r.student} - {r.class_section} ({r.sexy_status})")
                for r in registrations
            ]
            self.fields['registration_ids'].initial = registration_ids
        else:
            data = kwargs.get('data')
            if data is not None:
                self.fields['registration_ids'].choices = [
                    (rid, rid) for rid in data.getlist('registration_ids')
                ]

    def save(self, allowed_ids=None):
        """Set needs_mirroring on the selected registrations.

        `allowed_ids` MUST be the caller's campus-authorized id set (from
        processable_ids); only the intersection is updated. The form's
        dynamically-populated `registration_ids` choices accept any submitted
        id, so authorization cannot be enforced here — the view re-scopes and
        passes the result. `None` means "no restriction" (trusted callers /
        unit tests only).
        """
        data = self.cleaned_data
        value = data.get('needs_mirroring') == '1'
        ids = data.get('registration_ids')
        if allowed_ids is not None:
            allowed = {str(a) for a in allowed_ids}
            ids = [i for i in ids if str(i) in allowed]
        StudentRegistration.objects.filter(
            id__in=ids
        ).update(needs_mirroring=value)
        return value



class AddNewHighSchoolClassOfferingForm(forms.Form):
    """
    Lookup available class sections and add to highschool
    """
    highschool = forms.CharField(
        widget=forms.HiddenInput,
        required=True
    )
    term = forms.ModelChoiceField(queryset=None)

    class_section = forms.ModelMultipleChoiceField(
        queryset=None,
        help_text='Use Ctrl or Cmd key to select multiple',
        label='Class Section')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['term'].queryset = Term.objects.all()

        self.helper = FormHelper()
        self.helper.form_class = 'frm_ajax'
        self.helper.form_id = 'frm_add_course_offering'
        self.helper.form_method = 'POST'

        self.helper.add_input(Submit('submit', 'Add to High School Offering'))

        initial_args = kwargs.get('initial')
        if initial_args:
            
            class_sections = ClassSection.objects.filter(
                term=initial_args.get('term')
            ).order_by('course')
            self.fields['class_section'].queryset = class_sections

        form_data = kwargs.get('data', None)
        if form_data:

            class_sections = ClassSection.objects.filter(
                term=form_data.get('term')
            )
            self.fields['class_section'].queryset = class_sections

class HighSchoolClassOfferingForm(forms.Form):
    """
    This form is used in Class Section -> Class Details to add section to 
    High schools
    """
    highschool = forms.ModelMultipleChoiceField(
        queryset=None,
        label='High School(s)',
        help_text='Select high schools offering this section. Hold the Ctrl or Cmd key to select multiple'
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['highschool'].queryset = HighSchool.objects.all()

class ClassSectionUploadForm(forms.Form):
    file = forms.FileField(
        widget=forms.FileInput(attrs={'accept': 'text/csv'})
    )

class SectionNumberForm(forms.ModelForm):
    class Meta:
        model = SectionNumber
        fields = '__all__'

class ClassSectionForm(forms.ModelForm):

    id = forms.CharField(
        widget=forms.HiddenInput
    )

    sis_id = forms.CharField(
        required=False,
        label='SIS ID',
        help_text=''
    )

    class Meta:
        model = ClassSection
        fields = '__all__'
        exclude = [
            'start_date',
            'end_date',
            'notifications',
            # 'class_number',
            # 'section_number',
            # 'teacher',
            # 'term',
            # 'co_reqs',
            'highschool_course_title',
            # 'highschool_course_name',
            'part_of_term',
            'start_time', 
            'end_time',
            'days',
            'room',
            'instruction_mode',
            'prereq',
            'max_enrollment',
            'min_enrollment',
            'enrollment',
            'available_seats',
            'room_alias',
            'syllabi', 'campus', 
            'max_enrollment',
            'location',
            # 'course',
            'meta',
            # 'free_period',
            # 'period_time',
            # 'roster_status',
            'credit_hours',
            'roster_status_changed_on',
            'grade_status_changed_on',
            # 'teacher'
            'syllabi_status_changed_on'
            ]

        labels = {
            'highschool': 'High School',
            'co_reqs': 'Co-Req(s)',
        }

        widgets = {
            'co_reqs': forms.CheckboxSelectMultiple
        }
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if kwargs.get('instance'):
            instance = kwargs.get('instance')

            if not instance.is_a_co_req:
                self.fields['co_reqs'].queryset = ClassSection.objects.filter(
                    teacher=instance.teacher,
                    highschool=instance.highschool,
                    term__code__gte=instance.term.code
                ).exclude(
                    Q(id=instance.id) | Q(id__in=ClassSection.objects.filter(
                        co_reqs__id=instance.id
                    ).values_list('id', flat=True)
                ))

                self.fields['sis_id'].initial = instance.meta.get('section_id', '')
            else:
                self.fields['co_reqs'].queryset = ClassSection.objects.none()


    def clean_co_reqs(self):
        co_reqs = self.cleaned_data.get('co_reqs')

        for coreq in co_reqs:
            if coreq.co_reqs.all().count() > 0:
                raise ValidationError(f'{coreq} already has a co-req defined')
            
        return co_reqs
    
    
    def save(self, commit=True):
        record = super().save(commit=True)

        data = self.cleaned_data
        record.co_reqs.clear()

        if data.get('sis_id'):
            meta = record.meta

            if not meta:
                meta = {}
            meta['section_id'] = data.get('sis_id')
            record.meta = meta
            record.save()

        if data.get('co_reqs'):
            record.co_reqs.add(*data.get('co_reqs'))
        
        return record
        


class SectionSyllabiForm(forms.ModelForm):
    class_sections = forms.ModelMultipleChoiceField(
        queryset=None,
        label='Class Section(s)',
        widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = ClassSectionSyllabi
        fields = ['description', 'media']

        labels = {
            'description': _("Description"),
            'media': _('Syllabus'),
            'class_sections': 'Class Section(s)'
        }

    def __init__(self, term, teacher, course, *args, **kwargs):
        super(SectionSyllabiForm, self).__init__(*args, **kwargs)

        class_sections = ClassSection.objects.filter(
            term=term, teacher=teacher, course=course
        )
        self.fields['class_sections'].queryset = class_sections

        if not kwargs.get('initial'):
            self.fields['class_sections'].initial = class_sections
    

class ProcessStudentDropRequest(forms.Form):
    """
    Form to edit an existing registration
    """
    id = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )
    
    request_status = forms.ChoiceField(
        choices=StudentDropRequest.STATUS_OPTIONS,
        label='Request Status'
    )
    registration_status = forms.ChoiceField(
        choices=StudentRegistration.STATUS_OPTIONS,
        label='Class Registration Status'
    )
    
    def __init__(self, drop_request, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['request_status'].initial = drop_request.status
        self.fields['id'].initial = drop_request.id
        
        self.fields['registration_status'].initial = drop_request.registration.status

    def save(self, drop_request):
        student_registration = drop_request.registration

        drop_request.status = self.cleaned_data['request_status']
        drop_request.save()

        student_registration.status = self.cleaned_data['registration_status']
        student_registration.save()

        return drop_request

class AddNewStudentRegistrationForm(forms.Form):
    """
    Lookup available class sections and add to student
    """
    student = forms.CharField(
        widget=forms.HiddenInput,
        required=True
    )
    term = forms.ModelChoiceField(queryset=Term.objects.all())
    highschool = forms.ModelChoiceField(queryset=HighSchool.objects.all())

    class_section = forms.ModelChoiceField(queryset=None)
    status = forms.ChoiceField(choices=StudentRegistration.STATUS_OPTIONS)

    def __init__(self, *args, **kwargs):

        super(AddNewStudentRegistrationForm, self).__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.form_class = 'frm_ajax'
        self.helper.form_id = 'frm_add_registration'
        self.helper.form_method = 'POST'

        self.helper.add_input(Submit('submit', 'Add to Student'))

        initial_args = kwargs.get('initial')
        if initial_args:
            class_sections = ClassSection.objects.filter(
                term=initial_args.get('term'), highschool=initial_args.get('highschool')
            )
            self.fields['class_section'].queryset = class_sections

        form_data = kwargs.get('data', None)
        if form_data:
            class_sections = ClassSection.objects.filter(
                term=form_data.get('term'), highschool=form_data.get('highschool')
            )
            self.fields['class_section'].queryset = class_sections

    def clean_class_section(self):
        student = Student.objects.get(pk=self.cleaned_data['student'])
        class_section = self.cleaned_data['class_section']

        if StudentRegistration.objects.filter(
                student=student,
                class_section=class_section
        ).exists():
            raise ValidationError(_("Student is already registered for this class"))
        return class_section


def __getattr__(name):
    """Back-compat shim: EditStudentRegistration moved to the tenant app
    (myce_tenant_configs.services.registration_form) and is resolved via
    get_tenant_service. Importers — including the pip-installed drop_wd package
    that subclasses it — keep doing `from cis.forms.section import
    EditStudentRegistration` unchanged. PEP 562 module __getattr__ runs only for
    names not already defined in this module, so existing forms are unaffected.
    """
    if name == 'EditStudentRegistration':
        from cis.services.tenant_services import get_tenant_service
        return get_tenant_service('registration_form').EditStudentRegistration
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
