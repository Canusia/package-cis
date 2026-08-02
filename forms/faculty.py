from django import forms
from django.forms import ModelForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from cis.models.customuser import CustomUser

from cis.models.course import Department, Course, CourseAdministrator
from ..models.note import CourseNote
from cis.models.faculty import (
    FacultyCoordinator
)

from form_fields import fields as FFields


class FacultyCSVUploadForm(forms.Form):
    file = forms.FileField(widget=forms.FileInput(attrs={'accept': 'text/csv'}))


class FacultyCourseChangeStatusForm(forms.Form):
    faculty_course_administrator_ids = forms.MultipleChoiceField(
        required=False,
        label='Records to Update',
        widget=forms.CheckboxSelectMultiple,
        choices=[]
    )
    
    new_status = forms.ChoiceField(
        required=True,
        label='New Status',
        choices=CourseAdministrator.STATUS_OPTIONS
    )

    action = forms.CharField(
        widget=forms.HiddenInput
    )

    note = forms.CharField(
        label='Comment/Note',
        help_text='This will be added as a note to the course\'s record.',
        required=True,
        widget=forms.Textarea()
    )

    def __init__(self, faculty_course_administrator_ids=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['action'].initial = kwargs.get('action', 'change_course_administrator_status')

        if faculty_course_administrator_ids:
            course_administrators = CourseAdministrator.objects.filter(
                id__in=faculty_course_administrator_ids
            )

            course_admin_choices = []
            for course_admin in course_administrators:
                course_admin_choices.append(
                    (
                        course_admin.id,
                        f"{course_admin.user} => {course_admin.course.name} / {course_admin.status}"
                    )
                )
                
            self.fields['faculty_course_administrator_ids'].choices = course_admin_choices
            self.fields['faculty_course_administrator_ids'].initial = faculty_course_administrator_ids
        else:
            course_admin_choices = []
            for regis_id in kwargs.get('data').getlist('faculty_course_administrator_ids'):
                course_admin_choices.append(
                    (regis_id, regis_id)
                )

            self.fields['faculty_course_administrator_ids'].choices = course_admin_choices
            self.fields['faculty_course_administrator_ids'].required = False

    def save(self, request=None):
        data = self.cleaned_data

        new_status = data.get('new_status')
        for faculty_course_administrator_id in data.get('faculty_course_administrator_ids'):
            try:
                course_admin = CourseAdministrator.objects.get(
                    id=faculty_course_administrator_id
                )

                course_admin.status = new_status
                course_admin.save()

                note = CourseNote(
                    course=course,
                    createdby=request.user,
                    note=data.get('note')
                )

                note.save()

            except Exception as e:
                ...


class FacultyCourseAdministratorForm(forms.ModelForm):

    id = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )

    course = forms.ModelChoiceField(
        queryset=None
    )

    class Meta:
        model = CourseAdministrator
        fields = [
            'user',
            'role',
            'status'
        ]

        widgets = {
            'user': forms.HiddenInput
        }

    def save(self, request, record, commit=False):
        data = self.cleaned_data

        if not record:
            courses = data.get('course')
            for course in courses:
                record = CourseAdministrator()

                record.course = course
                record.status = data.get('status')
                record.user = data.get('user')
                record.role = data.get('role')

                try:
                    record.save()
                except:
                    ...
            return record
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

    def __init__(self, id, faculty=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['id'].initial = id
        self.fields['user'].queryset = CustomUser.objects.filter(
            groups__name__in=['ce', 'faculty']
        ).distinct(
            'id', 'last_name'
        ).order_by(
            'last_name'
        )

        if faculty:
            self.fields['user'].queryset = CustomUser.objects.filter(
                id=faculty.user.id
            )
            self.fields['user'].initial = faculty.user
        else:
            self.fields['user'].queryset = CustomUser.objects.filter(
                groups__name__in=['faculty']
            )

        if kwargs.get('instance'):
            # Add note field
            self.fields['note'] = forms.CharField(
                label='Comment/Note',
                help_text='This will be added as a note to the course\'s record.',
                required=True,
                widget=forms.Textarea()
            )

            self.fields['course'].queryset = Course.objects.filter(
                id=kwargs.get('instance').course.id
            )
            self.fields['course'].initial = kwargs.get('instance').course.id

            self.fields['user'].queryset = CustomUser.objects.filter(
                pk=kwargs.get('instance').user.id
            )

            self.fields['user'].disabled = True
            self.fields['course'].disabled = True
            self.fields['role'].disabled = True
        else:
            self.fields['course'] = forms.ModelMultipleChoiceField(
                queryset=Course.objects.filter(status__iexact='active'),
                label='Course(s)'
            )

class FacultyCooridnatorStatusUpdateForm(forms.Form):
    
    record_id = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )

    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )
    
    status = forms.ChoiceField(choices=FacultyCoordinator.STATUS_OPTIONS, label='New Status')

    note = forms.CharField(
        label='Comment/Note',
        help_text='This will be added as a private note to the faculty\'s record.',
        required=True,
        widget=forms.Textarea()
    )

    courses = FFields.LongLabelField(
        required=False,
        label='Course(s)',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'border-0 bg-light h-100'
            }
        )
    )
    
    course_status = forms.CharField(
        label='New Status of above Course(s)',
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
        self.fields['action'].initial = 'change_status'

        self.fields['status'].help_text = f"Current status is '{record.status}'"
        course_admins = CourseAdministrator.objects.filter(
            user=record.user
        ).order_by(
            'course__name'
        )

        courses_list = ""
        for course_admin in course_admins:
            courses_list += f"{course_admin.course.name} / {course_admin.role} => {course_admin.status}<br>"

        self.fields['courses'].initial = courses_list


    def save(self, request, record, commit=True):
        data = self.cleaned_data

        note_message = f"Updating status from {record.status} => {data['status']}<br>" + data.get('note')

        record.status = data.get('status')
        record.save()

        record.add_note(request.user, note_message)
        
        if data.get('course_status'):
            CourseAdministrator.objects.filter(
                user=record.user
            ).update(
                status=data.get('course_status')
            )
        
class FacultyCoordinatorForm(forms.Form):
    """
    Faculty profile form
    """
    first_name = forms.CharField(label='First Name', max_length=128)
    last_name = forms.CharField(label='Last Name', max_length=128)
    title = forms.CharField(label='Salutation', max_length=100, required=False)

    email = forms.EmailField(label='College Email')
    username = forms.CharField(
        label='User Name', max_length=128, required=False,
        widget=forms.HiddenInput
    )
    psid = forms.CharField(label='EMPLID', max_length=128)
    
    department = forms.ModelChoiceField(
        required=False,
        queryset=Department.objects.all().order_by('name'),
        widget=forms.HiddenInput
    )

    job_title = forms.CharField(label='Job Title', max_length=100, required=False)
    primary_phone = forms.CharField(label='Primary Phone', max_length=50, required=False)

    address1 = forms.CharField(label='Address1', max_length=50, required=False)
    city = forms.CharField(label='City', max_length=50, required=False)
    state = forms.CharField(label='State', max_length=50, required=False)
    postal_code = forms.CharField(label='Zip Code', max_length=50, required=False)

    fac_assistant = forms.ChoiceField(
        label='Is Faculty Assistant?',
        required=False,
        choices=FacultyCoordinator.ASST_OPTIONS,
        widget=forms.HiddenInput
    )

    def __init__(self, record=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if record:
            self.fields['first_name'].initial = record.user.first_name
            self.fields['last_name'].initial = record.user.last_name
            self.fields['email'].initial = record.user.email
            self.fields['username'].initial = record.user.username
            self.fields['psid'].initial = record.user.psid
            self.fields['primary_phone'].initial = record.user.primary_phone
            self.fields['address1'].initial = record.user.address1
            self.fields['city'].initial = record.user.city
            self.fields['state'].initial = record.user.state
            self.fields['postal_code'].initial = record.user.postal_code

            self.fields['title'].initial = record.title
            self.fields['job_title'].initial = record.job_title
        else:
            self.fields['courses'] = forms.ModelMultipleChoiceField(
                queryset=Course.objects.filter(status__iexact='active')
            )

            self.fields['course_admin_role'] = forms.ChoiceField(
                choices=CourseAdministrator.ROLE_OPTIONS,
                label='Role for above course(s)'
            )

    def save(self, record=None, commit=True):
        data = self.cleaned_data

        user = CustomUser.objects.get(pk=record.user.id)

        user.first_name = data.get('first_name')
        user.last_name = data.get('last_name')
        user.email = data.get('email').lower()
        user.username = data.get('email').lower()
        user.primary_phone = data.get('primary_phone')
        user.psid = data.get('psid')

        user.address1 = data.get('address1')
        user.city = data.get('city')
        user.state = data.get('state')
        user.postal_code = data.get('postal_code')

        user.save()
        
        record.title = data.get('title')
        record.job_title = data.get('job_title')

        record.status = 'Active'
        record.department = data.get('department')
        if commit:
            record.save()

        return record

    # def clean_username(self):
    #     data = self.cleaned_data['username']

    #     if data != self.cleaned_data['email'].split("@")[0]:
    #         self._errors['username'] = self.error_class(['Username is not matching primary email'])
    #     return data
