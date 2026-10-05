from django import forms
from django.db.models import Q
from django.forms import ModelForm

from django_ckeditor_5.widgets import CKEditor5Widget as CKEditorWidget

from form_fields import fields as FFields

from cis.models.course import (
    Cohort, Category, College, Department,
    Course, Campus, Location, TechCenter,
    CourseAppRequirement,
    CourseDocumentRequirement,
    CourseAdministrator,
    CourseUpload,
    DocumentType,
    course_document_choices,
    student_grade_choices
)
from ..utils import YES_NO_SELECT_OPTIONS, user_has_instructor_role
from ..models.customuser import CustomUser
from ..models.note import CourseNote

from cis.utils import get_foreign_key_references, get_foreign_key_reference_models

from cis.models.tech_center_staff import TechCenterStaff
from cis.models.teacher import TeacherCourseCertificate


class CourseSIAvailabilityChangeForm(forms.Form):

    available_for_si = forms.ChoiceField(
        choices=YES_NO_SELECT_OPTIONS,
        required=False,
        label='Available for New Instructor Applicants'
    )

    course_ids = forms.MultipleChoiceField(
        required=False,
        label='Records to Update',
        widget=forms.CheckboxSelectMultiple,
        choices=[]
    )

    action = forms.CharField(
        widget=forms.HiddenInput
    )

    field_order = ['course_ids', 'action']

    def __init__(self, course_ids=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['action'].initial = kwargs.get('action', 'change_si_availability')
        self.fields['available_for_si'].required = False
        self.fields['available_for_si'].help_text = 'Leave blank to retain current respective value'

        if course_ids:
            courses = Course.objects.filter(id__in=course_ids)
            self.fields['course_ids'].choices = [(c.id, c.name) for c in courses]
            self.fields['course_ids'].initial = course_ids
        else:
            self.fields['course_ids'].choices = [
                (cid, cid) for cid in kwargs.get('data').getlist('course_ids')
            ]

    def save(self, request=None):
        from cis.models.note import CourseNote

        data = self.cleaned_data
        new_available_for_si = data.get('available_for_si')

        for course_id in data.get('course_ids'):
            try:
                course = Course.objects.get(id=course_id)
                course_note = ''

                if new_available_for_si:
                    course_note += 'Changing SI Availability<br>'
                    course.meta['available_for_si'] = new_available_for_si

                if course_note:
                    CourseNote(
                        course=course,
                        createdby=request.user,
                        note=course_note,
                    ).save()

                course.save()
            except Exception:
                pass


class CohortUploadForm(forms.Form):
    file = forms.FileField(
        widget=forms.FileInput(attrs={'accept': 'text/csv'})
    )


class CourseCSVUploadForm(forms.Form):
    file = forms.FileField(
        widget=forms.FileInput(attrs={'accept': 'text/csv'})
    )


class MigrateForm(forms.Form):
    
    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='migrate_course'
    )

    destination_record = forms.ModelChoiceField(
        required=True,
        queryset=None,
        label='Destination Record'
    )

    move_items = forms.MultipleChoiceField(
        label='Select Items to Move',
        choices=[
            ('registrations', 'Registrations'),
            ('support_docs', 'Support Docs.'),
            ('student_agreements', 'Student Agreements'),
            ('student_recommendation', 'Recommendations'),
            ('parent_consent', 'Parent Consent'),
            ('notes', 'Notes'),
        ],
        widget=forms.CheckboxSelectMultiple
    )

    confirm = forms.BooleanField(
        required=True,
        label='I understand this action cannot be undone.'
    )
    
    # class Media:
    #     js = [
    #         'js/student_migration.js'
    #     ]

    def __init__(self, record, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['destination_record'].queryset = Course.objects.all().exclude(
            id=record.id
        )

        # Names only -- loading every referencing row timed out large records.
        self.fields['move_items'].choices = [
            (name, name) for name in get_foreign_key_reference_models(record)
        ]

    def save(self, request, record):
        data = self.cleaned_data
        references = get_foreign_key_references(record)

        success, message = True, []
        for model_name, obj in references:

            if model_name in data.get('move_items'):
                try:
                    obj.course = data.get('destination_record')
                    obj.save()

                    message.append(
                        f'Successfully moved {model_name} - {obj}'
                    )
                except Exception as e:
                    success = False
                    message.append(
                        f'Failed to move {model_name} - {obj} {e}. Please edit/delete this record manually'
                    )

        return (success, message)

class MigrateCohortForm(forms.Form):
    
    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='migrate_cohort'
    )

    destination_record = forms.ModelChoiceField(
        required=True,
        queryset=None,
        label='Destination Record'
    )

    move_items = forms.MultipleChoiceField(
        label='Select Items to Move',
        choices=[
            ('registrations', 'Registrations'),
            ('support_docs', 'Support Docs.'),
            ('student_agreements', 'Student Agreements'),
            ('student_recommendation', 'Recommendations'),
            ('parent_consent', 'Parent Consent'),
            ('notes', 'Notes'),
        ],
        widget=forms.CheckboxSelectMultiple
    )

    confirm = forms.BooleanField(
        required=True,
        label='I understand this action cannot be undone.'
    )
    
    # class Media:
    #     js = [
    #         'js/student_migration.js'
    #     ]

    def __init__(self, record, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['destination_record'].queryset = Cohort.objects.all().exclude(
            id=record.id
        )

        # Names only -- loading every referencing row timed out large records.
        self.fields['move_items'].choices = [
            (name, name) for name in get_foreign_key_reference_models(record)
        ]

    def save(self, request, record):
        data = self.cleaned_data
        references = get_foreign_key_references(record)

        success, message = True, []
        for model_name, obj in references:

            if model_name in data.get('move_items'):
                try:
                    obj.cohort = data.get('destination_record')
                    obj.save()

                    message.append(
                        f'Successfully moved {model_name} - {obj}'
                    )
                except Exception as e:
                    success = False
                    message.append(
                        f'Failed to move {model_name} - {obj} {e}. Please edit/delete this record manually'
                    )

        return (success, message)
    
class CourseUploadForm(forms.ModelForm):
    class Meta:
        model = CourseUpload
        fields = '__all__'

        labels = {
            'media_type': 'Resource Type'
        }
        
    def __init__(self, course, user, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['course'].queryset = Course.objects.filter(
            id=course.id
        )
        self.fields['course'].initial = course.id

        if user_has_instructor_role(user):
            self.fields['media_type'].choices = [
                ('Shared Resource', 'Shared Resource')
            ]
        
        self.fields['course'].widget = forms.HiddenInput()

class TechCenterStaffForm(forms.Form):
    id = forms.CharField(
        required=True,
        widget=forms.HiddenInput()
    )

    first_name = forms.CharField(label='First Name', max_length=128)
    last_name = forms.CharField(label='Last Name', max_length=128)
    email = forms.EmailField(label='Primary Email')
    username = forms.CharField(label='Username', max_length=128)

    tech_center = forms.MultipleChoiceField(
        choices=(),
        label='Tech. Center(s)'
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['tech_center'].choices = [(obj.id, obj.name) for obj in TechCenter.objects.all()]

    def save(self):
        data = self.cleaned_data

        if data['id'] == '-1':
            try:
                user = CustomUser.objects.get(
                    email__iexact=data['email'].lower()
                )
            except CustomUser.DoesNotExist:
                user = CustomUser()

            user.first_name = data['first_name']
            user.last_name = data['last_name']
            user.email = data['email']
            user.username = data['username']
            user.save()

            record = TechCenterStaff(user=user)
        else:
            record = TechCenterStaff.objects.get(
                pk=data['id']
            )
    
            record.user.first_name = data['first_name']
            record.user.last_name = data['last_name']
            record.user.email = data['email']
            record.user.username = data['username']
            record.user.save()

        if not record.tech_center:
            record.tech_center = {}
        
        record.tech_center = data['tech_center']
        record.save()

        return record

class TechCenterForm(ModelForm):
    serving_area = forms.CharField(
        required=True,
        help_text="Comma separated postal zipcode(s)",
        widget=forms.Textarea()
    )

    class Meta:
        model = TechCenter
        fields = '__all__'

        labels = {
            'serving_area': 'Serving Area(s)'
        }

class LocationForm(ModelForm):
    class Meta:
        model = Location
        fields = '__all__'

class CampusForm(ModelForm):
    """Site (MC-02) and SAML IdPs (MC-15) are always editable so a campus's
    host and IdP can be set up before MULTI_CAMPUS is switched on; with it
    off, nothing reads them."""
    class Meta:
        model = Campus
        fields = '__all__'
        help_texts = {
            'site': 'The host this campus is served on. Used only when MULTI_CAMPUS is on.',
            'saml_idps': 'SAML identity providers whose users belong to this campus. '
                         'Used only when MULTI_CAMPUS is on.',
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Campus.code keys SIS imports and per-campus branding (#61): fixed once
        # the campus exists, except for superusers. A disabled field ignores
        # posted values, so a crafted POST cannot change it either.
        # (_state.adding, not pk: Campus.id has a uuid4 default, so even an
        # unsaved campus has a pk.)
        if not self.instance._state.adding and not getattr(user, 'is_superuser', False):
            self.fields['code'].disabled = True

class CohortForm(ModelForm):
    class Meta:
        model = Cohort
        fields = '__all__'
        exclude = ['temp_id']

class DocumentTypeForm(ModelForm):
    """Add/edit a DocumentType from the CE Document Types page.

    Campus is required here even though the column is nullable: null is a
    legacy state to migrate away from (#45), so nothing new is created
    without one. `code` is the stable key both FKs' readers rely on, so it
    is fixed once the type exists; `label` is the editable wording.
    """
    class Meta:
        model = DocumentType
        fields = ['label', 'code', 'campus', 'status']
        help_texts = {
            'code': ('A short, stable key (letters, numbers, dashes and '
                     'underscores). It cannot be changed later.'),
            'status': 'Retire a type by making it Inactive; types are never deleted.',
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['campus'].required = True
        if user is not None:
            from cis.campus_gate import get_accessible_campuses
            self.fields['campus'].queryset = get_accessible_campuses(user)
        # Not `instance.pk`: the UUID pk is assigned on instantiation, so a
        # brand-new type already has one.
        if not self.instance._state.adding:
            self.fields['code'].disabled = True

    def clean(self):
        cleaned = super().clean()
        code = cleaned.get('code')
        campus = cleaned.get('campus')
        if code and campus:
            others = DocumentType.objects.exclude(pk=self.instance.pk)
            if others.filter(campus=campus, code__iexact=code).exists():
                self.add_error(
                    'code', 'This campus already has a document type with this code.')
            elif others.filter(campus__isnull=True, code__iexact=code).exists():
                # The partial unique constraints can't express this one: a
                # campus-scoped type must not shadow a legacy unassigned type
                # with the same code (#45).
                self.add_error(
                    'code', 'An unassigned document type already uses this code. '
                            'Assign that type to a campus instead of adding a new one.')
        return cleaned

class CategoryForm(ModelForm):
    class Meta:
        model = Category
        fields = '__all__'

class CollegeForm(ModelForm):
    class Meta:
        model = College
        fields = '__all__'

class DepartmentForm(ModelForm):
    class Meta:
        model = Department
        fields = '__all__'


class CourseStatusUpdateForm(forms.Form):
    
    record_id = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )

    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='change_status'
    )
    
    status = forms.ChoiceField(choices=[('', 'Select')]+Course.STATUS_OPTIONS, label='New Status')

    note = forms.CharField(
        label='Comment/Note',
        help_text='This will be added as a private note to the course\'s record.',
        required=True,
        widget=forms.Textarea()
    )

    teachers = FFields.LongLabelField(
        required=False,
        label='Certified Instructors Members',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'border-0 bg-light h-100'
            }
        )
    )
    
    teacher_status = forms.CharField(
        label='New Status of above Instructor',
        required=False,
        help_text='Leave this blank to update individually',
        widget=forms.Select(
            choices=[('', 'Select')]+TeacherCourseCertificate.STATUS_OPTIONS,
            attrs={
                'class': 'col-md-6'
            }
        )
    )

    faculty = FFields.LongLabelField(
        required=False,
        label='Course Admin / Faculty',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'border-0 bg-light h-100'
            }
        )
    )

    faculty_status = forms.CharField(
        label='New Status of above Course Admin / Faculty',
        required=False,
        help_text='Leave this blank to update individually',
        widget=forms.Select(
            choices=[('', 'Select')]+CourseAdministrator.STATUS_OPTIONS,
            attrs={
                'class': 'col-md-6'
            }
        )
    )

    def __init__(self, record, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['record_id'].initial = record.id

        self.fields['status'].help_text = f"Current status is '{record.status}'"
        teacher_certs = TeacherCourseCertificate.objects.filter(
            course=record
        ).order_by('teacher_highschool__teacher__user__last_name')

        teacher_cert_list = []
        for teacher_cert in teacher_certs:
            teacher_cert_list.append(
                f"{teacher_cert.teacher_highschool.teacher} - {teacher_cert.status}"
            )
        self.fields['teachers'].initial = '<br>'.join(teacher_cert_list)

        faculty = CourseAdministrator.objects.filter(
            course=record
        ).order_by('user')
        faculty_list = []
        for fac in faculty:
            faculty_list.append(
                f"{fac.user} / {fac.role} - {fac.status}"
            )
        self.fields['faculty'].initial = '<br>'.join(faculty_list)

    def save(self, request, record, commit=True):
        data = self.cleaned_data

        note_message = f"Updating status from {record.status} => {data['status']}<br>" + data.get('note')

        record.status = data.get('status')
        record.save()

        record.add_note(request.user, note_message)

        if data.get('faculty_status'):
            CourseAdministrator.objects.filter(
                course=record
            ).update(
                status=data.get('faculty_status')
            )
        
        if data.get('teacher_status'):
            TeacherCourseCertificate.objects.filter(
                course=record
            ).update(
                status=data.get('teacher_status')
            )

class CourseForm(ModelForm):

    available_for_si = forms.ChoiceField(
        choices=YES_NO_SELECT_OPTIONS,
        required=False,
        label='Available for New Instructor Applicants'
    )


    available_for_new_schools = forms.ChoiceField(
        label='Available for New School Application',
        required=False,
        choices=YES_NO_SELECT_OPTIONS
    )

    # note = forms.CharField(widget=CKEditorWidget())
    
    class Meta:
        model = Course
        fields = '__all__'
        exclude = ['epp', 'temp_id', 'department', 'category', 'meta']
        labels = {
            'cohort':'Subject'
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['campus'].queryset = Campus.objects.order_by('name')

        instance = kwargs.get('instance', None)
        if instance:

            # del self.fields['status']
        
            if instance.meta:
                self.fields['available_for_si'].initial = instance.meta.get('available_for_si')
                self.fields['available_for_new_schools'].initial = instance.meta.get('available_for_new_schools')
        
class CourseAppRequirementForm(ModelForm):

    # def __init__(self, id, *args, **kwargs):
    #     super(*args, **kwargs)

    class Meta:
        model = CourseAppRequirement
        fields = '__all__'
        exclude = ['course']
        widgets = {
            'description': CKEditorWidget()
        }


_RECURRENCE_HELP = (
    'How often the student must provide this document. An upload counts '
    'toward every course that requires the same document type.'
)


class CourseDocumentRequirementForm(ModelForm):

    class Meta:
        model = CourseDocumentRequirement
        fields = '__all__'
        exclude = ['course']
        widgets = {
            'description': CKEditorWidget()
        }

    def __init__(self, *args, course=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['grade_levels'].help_text = (
            'Leave empty to apply this requirement to all grade levels.'
        )
        self.fields['recurrence'].help_text = _RECURRENCE_HELP
        # Optional on the form so a POST that predates #44 (no recurrence
        # key) keeps the stored value instead of failing validation; see
        # clean_recurrence.
        self.fields['recurrence'].required = False

        # The course's campus decides which vocabulary is on offer. This has
        # to be the queryset, not a template filter: the only other campus
        # check on this model runs through course__campus on the view, so a
        # template filter would hide the option and still accept the POST.
        campus = course.campus if course is not None else getattr(
            getattr(self.instance, 'course', None), 'campus', None)
        offered = Q(campus=campus, status='Active')
        # Always include the instance's own current document_type, even if it
        # has since been retired (status='Inactive'), the documented way to
        # retire a type. Without this, editing an already-linked requirement
        # would render the dropdown with nothing selected, and saving any
        # unrelated change would silently write document_type=None -- this
        # widening only ever adds the id already stored on this exact row,
        # so it cannot be used to select a different (or another campus's)
        # type.
        current_id = getattr(self.instance, 'document_type_id', None)
        if current_id:
            offered |= Q(pk=current_id)
        self.fields['document_type'].queryset = DocumentType.objects.filter(offered)

    def clean_recurrence(self):
        return (self.cleaned_data.get('recurrence')
                or self.instance.recurrence or 'per_term')

    def clean(self):
        cleaned_data = super().clean()
        document = cleaned_data.get('document')
        document_type = cleaned_data.get('document_type')

        # Both fields are independently editable on this form ('__all__'), and
        # nothing else cross-validates them. If they disagree, the row would
        # display document_type's label while every downstream branch (and
        # the unique_together('course', 'document') key) reads `document` --
        # silently enforcing/showing the wrong requirement forever. The two
        # values come from the same vocabulary (init_document_types seeds
        # DocumentType.code from the same course_document_choices() that
        # populates `document`), so equality is the correct invariant.
        if document and document_type and document_type.code != document:
            self.add_error(
                'document_type',
                'Document Type does not match Document. Choose the Document '
                'Type whose code matches the selected Document, or leave '
                'Document Type blank.')
        return cleaned_data


class CourseAdministratorForm(ModelForm):

    id = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )

    class Meta:
        model = CourseAdministrator
        fields = '__all__'

    def save(self, request, commit=False):
        data = self.cleaned_data

        if not self.instance:
            record = CourseAdministrator()
        else:
            record = self.instance

        record.course = data.get('course')
        record.status = data.get('status')
        record.user = data.get('user')
        record.role = data.get('role')

        if data.get('note'):
            course = data.get('course')
            note = CourseNote(
                course=course,
                createdby=request.user,
                note=data.get('note')
            )

            note.save()

        if commit:
            record.save()

        return record

    def __init__(self, id, course=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['id'].initial = id
        self.fields['user'].queryset = CustomUser.objects.filter(
            groups__name__in=['ce', 'faculty']
        ).distinct(
            'id', 'last_name'
        ).order_by(
            'last_name'
        )

        if course:
            self.fields['course'].queryset = Course.objects.filter(
                id=course.id
            )
            self.fields['course'].initial = course
        else:
            self.fields['course'].queryset = Course.objects.filter()

        if kwargs.get('instance'):
            # Add note field
            self.fields['note'] = forms.CharField(
                label='Comment/Note',
                help_text='This will be added as a note to the course\'s record.',
                required=True,
                widget=forms.Textarea()
            )

            self.fields['user'].queryset = CustomUser.objects.filter(
                pk=kwargs.get('instance').user.id
            )

            self.fields['user'].disabled = True
            self.fields['course'].disabled = True
            self.fields['role'].disabled = True


class BulkAppRequirementUpdateForm(forms.Form):
    record_ids = forms.MultipleChoiceField(
        required=False,
        label='Records to Update',
        widget=forms.CheckboxSelectMultiple,
        choices=[]
    )

    new_status = forms.ChoiceField(
        required=True,
        label='New Status',
        choices=CourseAppRequirement.STATUS_OPTIONS
    )

    new_required = forms.ChoiceField(
        required=True,
        label='Required',
        choices=YES_NO_SELECT_OPTIONS
    )

    action = forms.CharField(
        widget=forms.HiddenInput,
        initial='update_app_requirements'
    )

    def __init__(self, record_ids=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if record_ids:
            records = CourseAppRequirement.objects.filter(id__in=record_ids)
            record_choices = [
                (record.id, f"{record.name} / {record.course}") for record in records
            ]
            self.fields['record_ids'].choices = record_choices
            self.fields['record_ids'].initial = record_ids
        else:
            record_choices = []
            for record_id in kwargs.get('data').getlist('record_ids'):
                record_choices.append((record_id, record_id))
            self.fields['record_ids'].choices = record_choices
            self.fields['record_ids'].required = False

    def save(self, request=None):
        data = self.cleaned_data
        records = CourseAppRequirement.objects.filter(id__in=data.get('record_ids'))
        records.update(status=data.get('new_status'), required=data.get('new_required'))
        return records


class BulkCourseDocumentRequirementUpdateForm(forms.Form):
    record_ids = forms.MultipleChoiceField(
        required=False,
        label='Records to Update',
        widget=forms.CheckboxSelectMultiple,
        choices=[]
    )

    new_status = forms.ChoiceField(
        required=True,
        label='New Status',
        choices=CourseDocumentRequirement.STATUS_OPTIONS
    )

    new_required = forms.ChoiceField(
        required=True,
        label='Required',
        choices=YES_NO_SELECT_OPTIONS
    )

    new_recurrence = forms.ChoiceField(
        required=False,
        label='Recurrence',
        choices=[('', 'Keep current')] + list(
            CourseDocumentRequirement.RECURRENCE_OPTIONS),
    )

    action = forms.CharField(
        widget=forms.HiddenInput,
        initial='update_course_doc_requirements'
    )

    def __init__(self, record_ids=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if record_ids:
            records = CourseDocumentRequirement.objects.filter(id__in=record_ids)
            record_choices = [
                (record.id, f"{record.document_label} / {record.course}") for record in records
            ]
            self.fields['record_ids'].choices = record_choices
            self.fields['record_ids'].initial = record_ids
        else:
            record_choices = []
            for record_id in kwargs.get('data').getlist('record_ids'):
                record_choices.append((record_id, record_id))
            self.fields['record_ids'].choices = record_choices
            self.fields['record_ids'].required = False

    def save(self, request=None):
        data = self.cleaned_data
        records = CourseDocumentRequirement.objects.filter(id__in=data.get('record_ids'))
        changes = {
            'status': data.get('new_status'),
            'required': data.get('new_required'),
        }
        if data.get('new_recurrence'):
            changes['recurrence'] = data['new_recurrence']
        records.update(**changes)
        return records


class BulkCourseAvailabilityForm(forms.Form):
    record_ids = forms.MultipleChoiceField(
        required=False,
        label='Courses to Update',
        widget=forms.CheckboxSelectMultiple,
        choices=[]
    )

    available_for_si = forms.ChoiceField(
        required=True,
        label='Available for New Instructor Applicants',
        choices=YES_NO_SELECT_OPTIONS
    )

    available_for_new_schools = forms.ChoiceField(
        required=True,
        label='Available for New School Application',
        choices=YES_NO_SELECT_OPTIONS
    )

    action = forms.CharField(
        widget=forms.HiddenInput,
        initial='update_course_availability'
    )

    def __init__(self, record_ids=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if record_ids:
            records = Course.objects.filter(id__in=record_ids)
            record_choices = [(record.id, record.name) for record in records]
            self.fields['record_ids'].choices = record_choices
            self.fields['record_ids'].initial = record_ids
        elif kwargs.get('data'):
            record_choices = []
            for record_id in kwargs['data'].getlist('record_ids'):
                record_choices.append((record_id, record_id))
            self.fields['record_ids'].choices = record_choices
            self.fields['record_ids'].required = False

    def save(self, request=None):
        data = self.cleaned_data
        courses = Course.objects.filter(id__in=data.get('record_ids'))
        for course in courses:
            if not course.meta:
                course.meta = {}
            course.meta['available_for_si'] = data['available_for_si']
            course.meta['available_for_new_schools'] = data['available_for_new_schools']
            course.save()
        return courses


class BulkCourseCampusForm(forms.Form):
    record_ids = forms.MultipleChoiceField(
        required=False,
        label='Courses to Update',
        widget=forms.CheckboxSelectMultiple,
        choices=[]
    )

    campus = forms.ModelChoiceField(
        required=True,
        label='Campus',
        queryset=Campus.objects.all().order_by('name')
    )

    action = forms.CharField(
        widget=forms.HiddenInput,
        initial='update_course_campus'
    )

    def __init__(self, record_ids=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if record_ids:
            records = Course.objects.filter(id__in=record_ids)
            record_choices = [(record.id, record.name) for record in records]
            self.fields['record_ids'].choices = record_choices
            self.fields['record_ids'].initial = record_ids
        elif kwargs.get('data'):
            record_choices = []
            for record_id in kwargs['data'].getlist('record_ids'):
                record_choices.append((record_id, record_id))
            self.fields['record_ids'].choices = record_choices
            self.fields['record_ids'].required = False

    def save(self, request=None):
        data = self.cleaned_data
        courses = Course.objects.filter(id__in=data.get('record_ids'))
        courses.update(campus=data.get('campus'))
        return courses


class BulkCourseRegistrationEligibilityForm(forms.Form):
    record_ids = forms.MultipleChoiceField(
        required=False,
        label='Courses to Update',
        widget=forms.CheckboxSelectMultiple,
        choices=[]
    )

    registration_eligibility = forms.MultipleChoiceField(
        required=True,
        label='Registration Eligibility',
        help_text=(
            'Replaces the current eligibility on every selected course. '
            'A grade marked "with recommendation" requires a school '
            'recommendation before the application can be approved.'
        ),
        widget=forms.CheckboxSelectMultiple,
        choices=Course.GRADE_LEVEL
    )

    action = forms.CharField(
        widget=forms.HiddenInput,
        initial='update_course_registration_eligibility'
    )

    def __init__(self, record_ids=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if record_ids:
            records = Course.objects.filter(id__in=record_ids)
            record_choices = [(record.id, record.name) for record in records]
            self.fields['record_ids'].choices = record_choices
            self.fields['record_ids'].initial = record_ids
        elif kwargs.get('data'):
            record_choices = []
            for record_id in kwargs['data'].getlist('record_ids'):
                record_choices.append((record_id, record_id))
            self.fields['record_ids'].choices = record_choices
            self.fields['record_ids'].required = False

    def save(self, request=None):
        data = self.cleaned_data
        courses = Course.objects.filter(id__in=data.get('record_ids'))
        # Iterate rather than queryset.update(): registration_eligibility is a
        # MultiSelectField, whose list-to-string conversion happens in the
        # field's pre_save, which .update() bypasses.
        eligibility = data.get('registration_eligibility')
        for course in courses:
            course.registration_eligibility = eligibility
            course.save()
        return courses


class AddAppRequirementForm(forms.Form):
    courses = forms.ModelMultipleChoiceField(
        required=True,
        label='Courses',
        queryset=Course.objects.filter(status='Active').order_by('name'),
        widget=forms.SelectMultiple(attrs={'class': 'form-control'})
    )

    name = forms.CharField(
        required=True,
        max_length=500,
        label='Requirement Name'
    )

    description = forms.CharField(
        required=False,
        label='Description',
        widget=CKEditorWidget()
    )

    required = forms.ChoiceField(
        required=True,
        label='Required',
        choices=YES_NO_SELECT_OPTIONS
    )

    status = forms.ChoiceField(
        required=True,
        label='Status',
        choices=CourseAppRequirement.STATUS_OPTIONS
    )

    action = forms.CharField(
        widget=forms.HiddenInput,
        initial='add_app_requirement'
    )

    def save(self, request=None):
        data = self.cleaned_data
        records = []
        for course in data.get('courses'):
            obj, created = CourseAppRequirement.objects.update_or_create(
                course=course,
                name=data.get('name'),
                defaults={
                    'description': data.get('description', ''),
                    'required': data.get('required'),
                    'status': data.get('status'),
                }
            )
            records.append(obj)
        return records


class AddCourseDocumentRequirementForm(forms.Form):
    courses = forms.ModelMultipleChoiceField(
        required=True,
        label='Courses',
        queryset=Course.objects.filter(status='Active').order_by('name'),
        widget=forms.SelectMultiple(attrs={'class': 'form-control'})
    )

    document = forms.ChoiceField(
        required=False,
        label='Document',
        choices=[]
    )

    document_type = forms.ModelChoiceField(
        required=False,
        label='Document Type',
        queryset=DocumentType.objects.none(),
    )

    grade_levels = forms.MultipleChoiceField(
        required=False,
        label='Grade Levels',
        choices=[]
    )

    description = forms.CharField(
        required=False,
        label='Description',
        widget=CKEditorWidget()
    )

    required = forms.ChoiceField(
        required=True,
        label='Required',
        choices=YES_NO_SELECT_OPTIONS
    )

    status = forms.ChoiceField(
        required=True,
        label='Status',
        choices=CourseDocumentRequirement.STATUS_OPTIONS
    )

    # Optional so a POST that predates #44 still validates; save() defaults
    # a missing value to per_term.
    recurrence = forms.ChoiceField(
        required=False,
        label='Recurrence',
        choices=CourseDocumentRequirement.RECURRENCE_OPTIONS,
        initial='per_term',
        help_text=_RECURRENCE_HELP,
    )

    # Add a type inline instead of leaving the modal for the Document Types
    # page (#45). All three or none; validated by DocumentTypeForm.
    new_type_label = forms.CharField(
        required=False, max_length=255,
        label='Or add a new document type: Label')
    new_type_code = forms.SlugField(
        required=False, max_length=100,
        label='New type: Code',
        help_text='A short, stable key (letters, numbers, dashes and underscores).')
    new_type_campus = forms.ModelChoiceField(
        required=False, queryset=Campus.objects.none(),
        label='New type: Campus',
        help_text='The requirement is added only to selected courses on this campus.')

    action = forms.CharField(
        widget=forms.HiddenInput,
        initial='add_course_doc_requirement'
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self._new_type_form = None
        # Resolve the tenant vocabularies per-request rather than at import time.
        self.fields['document'].choices = [('', '---------')] + list(
            course_document_choices())
        campuses = Campus.objects.all()
        if user is not None:
            from cis.campus_gate import get_accessible_campuses
            campuses = get_accessible_campuses(user)
        self.fields['new_type_campus'].queryset = campuses

        # Scope the offered types to the campuses this user may process --
        # otherwise a ce admin can pick another campus's identically-labelled
        # type (e.g. both campuses have a "Transcript") and every course on
        # the other campus is silently skipped in save() below. `user=None`
        # (e.g. a form built without a request, as some tests do) keeps the
        # unscoped queryset rather than resolving to nothing.
        #
        # A null-campus type must stay selectable by everyone, same as every
        # other campus scope in this codebase (campus_gate.py's
        # scope_queryset_by_campus, can_process_campus): null campus means
        # "visible/editable to every ce user", not "belongs to nobody". A
        # plain `campus__in=...` would silently exclude it, which would also
        # contradict init_document_types' null-campus fallback (I3) by
        # seeding/backfilling types that this dropdown then made impossible
        # to choose.
        types = DocumentType.objects.filter(status='Active').select_related('campus')
        if user is not None:
            from cis.campus_gate import get_accessible_campuses
            types = types.filter(
                Q(campus__in=get_accessible_campuses(user))
                | Q(campus__isnull=True))
        self.fields['document_type'].queryset = types
        # Two campuses can label a type identically ("Transcript"), so the
        # dropdown must show which campus each option belongs to.
        self.fields['document_type'].label_from_instance = (
            lambda obj: f'{obj.label} ({obj.campus.code})' if obj.campus_id
            else f'{obj.label} (unassigned)')
        self.fields['document_type'].help_text = (
            'Only applied to courses on the same campus as the chosen type.'
        )
        self.fields['grade_levels'].choices = student_grade_choices()
        self.fields['grade_levels'].help_text = (
            'Leave empty to apply this requirement to all grade levels.'
        )

    NEW_TYPE_FIELDS = ('new_type_label', 'new_type_code', 'new_type_campus')

    def clean(self):
        cleaned_data = super().clean()
        document = cleaned_data.get('document')
        document_type = cleaned_data.get('document_type')

        # Raw input, not cleaned_data: a campus the user may not pick fails
        # the queryset and would otherwise look like "left blank".
        new_type_given = any(
            str(self.data.get(name) or '').strip() for name in self.NEW_TYPE_FIELDS)
        if new_type_given:
            if document_type is not None:
                self.add_error(
                    'document_type',
                    'Choose an existing document type or add a new one, not both.')
                return cleaned_data
            self._clean_new_type(cleaned_data)
            return cleaned_data

        if not document and document_type is None:
            self.add_error(
                'document',
                'Choose a document, choose a document type, or add a new type.')
            return cleaned_data
        if document_type is not None and not document:
            cleaned_data['document'] = document = document_type.code

        # Same hazard as CourseDocumentRequirementForm.clean(): `document` and
        # `document_type` are independent inputs here too, and nothing else
        # cross-validates them.
        if document and document_type and document_type.code != document:
            self.add_error(
                'document_type',
                'Document Type does not match Document. Choose the Document '
                'Type whose code matches the selected Document, or leave '
                'Document Type blank.')
        return cleaned_data

    def _clean_new_type(self, cleaned_data):
        """Validate the inline type with DocumentTypeForm's rules."""
        for name in self.NEW_TYPE_FIELDS:
            if not str(self.data.get(name) or '').strip() and name not in self.errors:
                self.add_error(name, 'Required when adding a new document type.')
        if any(name in self.errors for name in self.NEW_TYPE_FIELDS):
            return

        type_form = DocumentTypeForm({
            'label': cleaned_data['new_type_label'],
            'code': cleaned_data['new_type_code'],
            'campus': cleaned_data['new_type_campus'].pk,
            'status': 'Active',
        }, user=self.user)
        if not type_form.is_valid():
            for field, name in (('label', 'new_type_label'), ('code', 'new_type_code'),
                                ('campus', 'new_type_campus')):
                for error in type_form.errors.get(field, []):
                    self.add_error(name, error)
            for error in type_form.non_field_errors():
                self.add_error(None, error)
            return

        document = cleaned_data.get('document')
        if document and document != cleaned_data['new_type_code']:
            self.add_error(
                'document',
                'Leave Document blank when adding a new document type.')
            return
        cleaned_data['document'] = cleaned_data['new_type_code']
        self._new_type_form = type_form

    def save(self, request=None):
        # One transaction: a new type is never left behind by a failed add.
        from django.db import transaction
        with transaction.atomic():
            return self._save(request)

    def _save(self, request=None):
        data = self.cleaned_data
        records = []
        self.skipped_courses = []
        document_type = data.get('document_type')
        if self._new_type_form is not None:
            document_type = self._new_type_form.save()
        for course in data.get('courses'):
            if document_type is not None and course.campus_id != document_type.campus_id:
                self.skipped_courses.append(course)
                continue
            defaults = {
                'grade_levels': data.get('grade_levels') or [],
                'description': data.get('description', ''),
                'required': data.get('required'),
                'status': data.get('status'),
                'recurrence': data.get('recurrence') or 'per_term',
            }
            # document_type is optional: only set it when a value was chosen.
            # Including it unconditionally would write None on every update,
            # silently clearing the FK off a requirement that was already
            # linked -- an optional field must never unlink existing data
            # just because this particular submission left it blank.
            if document_type is not None:
                defaults['document_type'] = document_type
            obj, created = CourseDocumentRequirement.objects.update_or_create(
                course=course,
                document=data.get('document'),
                defaults=defaults
            )
            records.append(obj)
        return records
