from django import forms
from django.forms import ModelForm

from django_ckeditor_5.widgets import CKEditor5Widget as CKEditorWidget

from form_fields import fields as FFields

from cis.models.course import (
    Cohort, Category, College, Department,
    Course, Campus, Location, TechCenter,
    CourseAppRequirement,
    CourseAdministrator,
    CourseUpload
)
from ..utils import YES_NO_SELECT_OPTIONS, user_has_instructor_role
from ..models.customuser import CustomUser
from ..models.note import CourseNote

from cis.utils import get_foreign_key_references

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

        references = get_foreign_key_references(record)
        move_item_choices = []

        for model_name, obj in references:
            choice = (f"{model_name}", f"{model_name}")
            if choice not in move_item_choices:
                move_item_choices.append(choice)

        self.fields['move_items'].choices = move_item_choices

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

        references = get_foreign_key_references(record)
        move_item_choices = []

        for model_name, obj in references:
            choice = (f"{model_name}", f"{model_name}")
            if choice not in move_item_choices:
                move_item_choices.append(choice)

        self.fields['move_items'].choices = move_item_choices

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
    class Meta:
        model = Campus
        fields = '__all__'

class CohortForm(ModelForm):
    class Meta:
        model = Cohort
        fields = '__all__'
        exclude = ['temp_id']

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

