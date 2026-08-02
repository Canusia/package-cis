import datetime

from django import forms
from django.forms import ModelForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from form_fields import fields as FFields

from cis.models.highschool import HighSchool
from cis.models.course import Course
from cis.models.teacher import (
    Teacher, TeacherHighSchool, TeacherCourseCertificate,
    TeacherUpload
)
from cis.utils import YES_NO_SELECT_OPTIONS, get_foreign_key_references
from cis.models.customuser import CustomUser

from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.template import Context, Template
from mailer import send_mail, send_html_mail
from django.conf import settings

import logging
logger = logging.getLogger(__name__)

from cis.models.note import TeacherNote
from cis.validators import validate_html_short_code
from django.core.validators import validate_email

from django_ckeditor_5.widgets import CKEditor5Widget as CKEditorWidget

class MigrateForm(forms.Form):
    
    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='migrate_teacher'
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

        self.fields['destination_record'].queryset = Teacher.objects.all().exclude(
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
                    obj.teacher = data.get('destination_record')
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
    
class BulkPasswordChangeForm(forms.Form):
    record_ids = forms.MultipleChoiceField(
        required=False,
        label='Records to Update',
        widget=forms.CheckboxSelectMultiple,
        choices=[]
    )
    
    new_password = forms.CharField(
        required=False
    )
    
    force_password_change = forms.ChoiceField(
        required=False,
        label='Do you want to require the user to change password upon login?',
        choices=YES_NO_SELECT_OPTIONS,
        help_text='Recommended if setting a default password'
    )

    send_email = forms.ChoiceField(
        required=False,
        label='Do you want to email them?',
        choices=YES_NO_SELECT_OPTIONS,
        help_text=''
    )

    email_subject = forms.CharField(
        required=False,
        label='Email Subject'
    )

    email_message = forms.CharField(
        required=False,
        label='Email Message',
        validators=[validate_html_short_code],
        widget=forms.Textarea,
        help_text='Customize with {{first_name}}, {{last_name}}, {{new_password}}'
    )

    action = forms.CharField(
        widget=forms.HiddenInput,
        initial='change_password'
    )

    class Media:
        js = [
            'js/bulk_password_change.js'
        ]

    def __init__(self, record_ids=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        from cis.settings.password_reset import password_reset as pwd_reset
        config = pwd_reset.from_db()

        self.fields['email_message'].initial = config.get('bulk_password_reset_email', 'Change me in Settings -> Misc -> Password Reset')
        self.fields['email_subject'].initial = config.get('bulk_password_reset_subject', 'Change me in Settings -> Misc -> Password Reset')

        if record_ids:
            records = Teacher.objects.filter(
                id__in=record_ids
            )

            record_choices = []
            selected_choices = []
            for record in records:
                record_choices.append(
                    (
                        record.id,
                        f"{record.user.last_name}, {record.user.first_name}"
                    )
                )
                
                selected_choices.append(record.id)

            self.fields['record_ids'].choices = record_choices
            self.fields['record_ids'].initial = selected_choices
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
        
        records = Teacher.objects.filter(
            id__in=data.get('record_ids')
        )

        if data.get('new_password'):
            for record in records:
                record.user.set_password(data.get('new_password'))

                record.add_note(request.user, f"Password changed via bulk action - {'User will be required to change password at next login' if data.get('force_password_change') == '1' else 'User will NOT be required to change password at next login'}. {'User will be emailed about this change.' if data.get('send_email') == '1' else 'User will NOT be emailed about this change.'}")

                record.user.save()

        if data.get('new_password'):
            for record in records:
                record.user.set_password(data.get('new_password'))
                record.user.save()

                if data.get('send_email') == '1':
                    try:
                        message = Template(data.get('email_message', 'not configured'))
                        subject = data.get('email_subject')

                        context = Context({
                            'first_name': record.user.first_name,
                            'last_name': record.user.last_name,
                            'new_password': data.get('new_password')
                        })

                        message = message.render(context)
                        
                        to = [record.user.email]
                        if record.user.secondary_email:
                            try:
                                validate_email(record.user.secondary_email)
                                to.append(record.user.secondary_email)
                            except:
                                ...
                            
                        send_mail(
                            subject,
                            message,
                            settings.DEFAULT_FROM_EMAIL,
                            to
                        )
                    except Exception as e:
                        logger.error(f"Failed to send bulk password change email to {record.user.email} - {e}")

        if data.get('force_password_change') == '1':
            CustomUser.objects.filter(
                id__in=records.values_list('user', flat=True)
            ).update(
                require_password_reset=True
            )

        return records
    
class TeacherStatusUpdateForm(forms.Form):
    
    record_id = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )

    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )
    
    status = forms.ChoiceField(choices=Teacher.STATUS_OPTIONS, label='New Status')

    note = forms.CharField(
        label='Comment/Note',
        help_text='This will be added as a private note to the instructor\'s record.',
        required=True,
        widget=forms.Textarea()
    )

    highschools = FFields.LongLabelField(
        required=False,
        label='High School(s)',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'border-0 bg-light h-100'
            }
        )
    )
    
    highschool_status = forms.CharField(
        label='New Status of above High School(s)',
        required=False,
        help_text='Leave this blank to update individually',
        widget=forms.Select(
            choices=[('', 'Select')]+TeacherHighSchool.STATUS_OPTIONS,
            attrs={
                'class': 'col-md-6'
            }
        )
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
            choices=[('', 'Select')]+TeacherCourseCertificate.STATUS_OPTIONS,
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
        
        course_certs = TeacherCourseCertificate.objects.filter(
            teacher_highschool__teacher=record
        ).order_by(
            'course__name'
        )

        courses_list = ""
        for course_cert in course_certs:
            courses_list += f"{course_cert.course.name} / {course_cert.teacher_highschool.highschool.name} => {course_cert.status}<br>"

        self.fields['courses'].initial = courses_list
        
        hs_certs = TeacherHighSchool.objects.filter(
            teacher=record
        ).order_by(
            'highschool__name'
        )

        courses_list = ""
        for hs_cert in hs_certs:
            courses_list += f"{hs_cert.highschool.name}  => {hs_cert.status}<br>"

        self.fields['highschools'].initial = courses_list


    def save(self, request, record, commit=True):
        data = self.cleaned_data

        note_message = f"Updating status from {record.status} => {data['status']}<br>" + data.get('note')

        record.status = data.get('status')
        record.save()

        record.add_note(request.user, note_message)
        
        if data.get('course_status'):
            TeacherCourseCertificate.objects.filter(
                teacher_highschool__teacher=record
            ).update(
                status=data.get('course_status')
            )

        if data.get('highschool_status'):
            TeacherHighSchool.objects.filter(
                teacher=record
            ).update(
                status=data.get('highschool_status')
            )
        
class EdBgForm(forms.Form):

    ed_bg = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )
    
    action = forms.CharField(
        required=False,
        initial='edit_ed_bg',
        widget=forms.HiddenInput()
    )

    credits_earned = forms.CharField(
        required=False,
        label='Number of credit hours earned beyond highest degree',
        help_text='',
        widget=forms.TextInput(
            attrs={
                'class': 'col-2'
            }
        )
    )

    masters_level_credits = forms.CharField(
        required=False,
        label="If Master’s degree is not specific to the discipline, please indicate the total number of Master’s-level credits in the discipline that is currently completed:",
        help_text="For example, to teach a history course, a Master’s in History would be discipline specific, but a Master’s in Education would not. And so, if your M.Ed. includes any History department-designated course credits, you would note those credits here. Similarly, to teach an accounting course, a Master’s in Accounting would be discipline specific, but a Master’s in Economics or Statistics would not.",
        widget=forms.TextInput(
            attrs={
                'class': 'col-2'
            }
        )
    )

    grad_courses = forms.CharField(
        required=False,
        label='List graduate course work that particularly pertains to the college course that you are interested in teaching',
        widget=forms.Textarea
    )

    undergrad_program = forms.CharField(
        required=False,
        label='Describeundergraduate program as it pertains to the college course interested in teaching',
        widget=forms.Textarea
    )

    certified_states = forms.CharField(
        required=False,
        label='State(s) permanently certified to teach?',
        help_text='',
        widget=forms.TextInput(
            attrs={
                'class': 'col-8'
            }
        )
    )

    certified_subjects = forms.CharField(
        required=False,
        label='Subject(s) permanently certified to teach?',
        help_text='',
        widget=forms.TextInput(
            attrs={
                'class': 'col-10'
            }
        )
    )
    highschool_years = forms.CharField(
        required=False,
        label='Total years of teaching High School',
        help_text='',
        widget=forms.TextInput(
            attrs={
                'class': 'col-2'
            }
        )
    )

    college_years = forms.CharField(
        required=False,
        label='Total years of teaching College',
        help_text='',
        widget=forms.TextInput(
            attrs={
                'class': 'col-2'
            }
        )
    )

    courses_taught = forms.CharField(
        required=False,
        label='Specific subjects taught or currently teaching that relate to the college course interested in teaching',
        widget=forms.Textarea
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)

        ed_bg = user.education_background
        if not ed_bg or isinstance(ed_bg, str):
            ed_bg = {}

        self.fields['credits_earned'].initial = ed_bg.get('credits_earned')
        self.fields['masters_level_credits'].initial = ed_bg.get('masters_level_credits')
        self.fields['grad_courses'].initial = ed_bg.get('grad_courses')
        self.fields['undergrad_program'].initial = ed_bg.get('undergrad_program')
        self.fields['certified_states'].initial = ed_bg.get('certified_states')
        self.fields['certified_subjects'].initial = ed_bg.get('certified_subjects')
        self.fields['highschool_years'].initial = ed_bg.get('highschool_years')
        self.fields['college_years'].initial = ed_bg.get('college_years')
        self.fields['courses_taught'].initial = ed_bg.get('courses_taught')

    def clean(self):
        self.cleaned_data = super().clean()

        institution = list(
            map(lambda x:str(x).strip(), self.data.getlist('ed_bg[institution]')))

        degree = list(
            map(lambda x:str(x).strip(), self.data.getlist('ed_bg[degree]')))

        major = list(
            map(lambda x:str(x).strip(), self.data.getlist('ed_bg[major]')))

        self.cleaned_data['ed_bg'] = {
            'institution':institution,
            'degree': degree,
            'major': major,
            'credits_earned': self.data.get('credits_earned'),
            'masters_level_credits': self.data.get('masters_level_credits'),
            'grad_courses': self.data.get('grad_courses'),
            'undergrad_program': self.data.get('undergrad_program'),
            'certified_states': self.data.get('certified_states'),
            'certified_subjects': self.data.get('certified_subjects'),
            'highschool_years': self.data.get('highschool_years'),
            'college_years': self.data.get('college_years'),
            'courses_taught': self.data.get('courses_taught'),
        }

        return self.cleaned_data

    def save(self, user):
        user.education_background = self.cleaned_data['ed_bg']
        user.save()

class TeacherCourseForm(forms.Form):

    highschool = forms.ModelChoiceField(queryset=None)
    course = forms.ModelChoiceField(queryset=None)

    status = forms.ChoiceField(choices=TeacherCourseCertificate.STATUS_OPTIONS)
    highschool_course_name = forms.CharField(
        required=False,
        label='High School Course Name'
    )
    

    since = forms.DateField(
        required=False
    )

    expires_on = forms.DateField(
        required=False,
        label='Expires On'
    )
    renewal_required_by = forms.DateField(
        required=False,
        label='Renewal Required By'
    )
    last_renewed_on = forms.DateField(
        required=False,
        label='Last Renewed On'
    )

    teacher = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )
    id = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )
    ajax = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )

    def __init__(self, id, teacher, ajax, *args, **kwargs):
        super().__init__(*args, **kwargs)

        teacher_hs = TeacherHighSchool.objects.filter(teacher=teacher)
        self.fields['highschool'].queryset = teacher_hs
        self.fields['course'].queryset = Course.objects.filter(
            status__iexact='active'
        ).order_by('name')

        self.fields['id'].initial = id
        self.fields['ajax'].initial = ajax
        self.fields['teacher'].initial = teacher.id

        if id != '-1':
            record = TeacherCourseCertificate.objects.get(
                pk=id
            )
            
            self.fields['course'].queryset = Course.objects.filter(
                id=record.course.id
            )
            self.fields['course'].initial = record.course

            self.fields['highschool'].queryset = TeacherHighSchool.objects.filter(
                id=record.teacher_highschool.id
            )
            self.fields['highschool'].initial = record.teacher_highschool.id
            self.fields['highschool_course_name'].initial = record.highschool_course_name

            self.fields['status'].initial = record.status
            if record.since:
                self.fields['since'].initial = record.since.strftime('%m/%d/%Y')
            if record.expires_on:
                self.fields['expires_on'].initial = record.expires_on.strftime('%m/%d/%Y')
            if record.renewal_required_by:
                self.fields['renewal_required_by'].initial = record.renewal_required_by.strftime('%m/%d/%Y')
            if record.last_renewed_on:
                self.fields['last_renewed_on'].initial = record.last_renewed_on.strftime('%m/%d/%Y')

            # Add note field
            self.fields['note'] = forms.CharField(
                label='Comment/Note',
                help_text='This will be added as a private note to the teacher\'s record.',
                required=True,
                widget=forms.Textarea()
            )

    def clean_highschool(self):
        try:
            data = self.cleaned_data['highschool']
        except ValidationError as e:
            pass
        return data

    def save(self, request, commit=False):
        data = self.cleaned_data

        if data.get('id') == '-1':
            record = TeacherCourseCertificate()
        else:
            record = TeacherCourseCertificate.objects.get(
                pk=data.get('id')
            )

            # add note to teacher record
            note = TeacherNote(
                teacher=record.teacher_highschool.teacher,
                note=f'Updating teacher\'s course certificate for {record.course}, {record.status} (' + ( record.since.strftime('%m/%d/%Y') if record.since else 'N/A' ) + ') ' + data.get('note'),
                createdby=request.user,
                meta={
                    'type': ['private']
                },
            )
            note.save()

        record.status = data['status']
        record.since = data.get('since')
        record.expires_on = data.get('expires_on')
        record.renewal_required_by = data.get('renewal_required_by')
        record.last_renewed_on = data.get('last_renewed_on')
        record.highschool_course_name = data.get('highschool_course_name')
        record.course = data.get('course')
        record.teacher_highschool = data.get('highschool')

        if commit:
            record.save()
        return record

class TeacherHighSchoolForm(forms.Form):
    highschool = forms.ModelChoiceField(
        label='High School',
        queryset=None,
        required=True
    )

    status = forms.ChoiceField(choices=TeacherHighSchool.STATUS_OPTIONS)

    teacher = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )
    id = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )
    ajax = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )

    def __init__(self, id, teacher_id, ajax, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['highschool'].queryset = HighSchool.objects.all().order_by('name')
        self.fields['ajax'].initial = ajax

        if id == '-1':
            self.fields['id'].initial = id
            self.fields['teacher'].initial = teacher_id
        else:
            record = TeacherHighSchool.objects.get(
                pk=id
            )

            self.fields['id'].initial = id
            self.fields['highschool'].queryset = HighSchool.objects.filter(
                id=record.highschool.id
            )            
            self.fields['highschool'].initial = record.highschool
            self.fields['status'].initial = record.status

            self.fields['teacher'].initial = str(record.teacher.id)

            self.fields['courses'] = FFields.LongLabelField(
                required=False,
                label='Course Cert(s) in High School',
                widget=FFields.LongLabelWidget(
                    attrs={
                        'class':'border-0 bg-light h-100'
                    }
                )
            )

            cert_status = []
            for key, status in TeacherCourseCertificate.STATUS_OPTIONS:
                cert_status.append(key)

            courses = record.teacher.get_course_certificates(
                status=cert_status,
                highschool_ids=[record.highschool.id]
            )

            course_list = ""
            if courses:
                # allow user to change the course status in the high school
                self.fields['course_status'] = forms.CharField(
                    label='New Status of above Course Cert(s) in High School',
                    required=False,
                    widget=forms.Select(
                        choices=[('', 'Select')]+TeacherCourseCertificate.STATUS_OPTIONS,
                        attrs={
                            'class': 'col-md-6'
                        }
                    )
                )                
                
                for course in courses:
                    course_list += f"{course.course} - {course.status}<br>"
            self.fields['courses'].initial = course_list

            self.fields['note'] = forms.CharField(
                label='Comment/Note',
                help_text='This will be added as a private note to the teacher\'s record.',
                required=True,
                widget=CKEditorWidget(attrs={'class':'ckeditor'})
            )


    def save(self, request, commit=False):
        data = self.cleaned_data

        if data.get('id') == '-1':
            record = TeacherHighSchool()
            record.teacher = Teacher.objects.get(pk=data.get('teacher'))
        else:
            record = TeacherHighSchool.objects.get(
                pk=data.get('id')
            )

            if data.get('course_status'):

                TeacherCourseCertificate.objects.filter(
                    teacher_highschool=record
                ).update(
                    status=data.get('course_status'),
                    since=datetime.datetime.now()
                )

            # add note to teacher record
            note = TeacherNote(
                teacher=record.teacher,
                note='Updating teacher\'s high school status - ' + data.get('note'),
                createdby=request.user,
                meta={
                    'type': ['private']
                },
            )
            note.save()

        record.highschool = data.get('highschool')
        record.status = data.get('status')

        if commit:
            record.save()
        return record

class TeacherForm(forms.Form):
    first_name = forms.CharField(label='First Name', max_length=128)
    last_name = forms.CharField(label='Last Name', max_length=128)

    email = forms.EmailField(label='Primary Email')
    username = forms.CharField(label='User Name', max_length=128)

    psid = forms.CharField(label='EMPLID', max_length=10, required=False)
    alt_email = forms.EmailField(label='Alt Email', max_length=128, required=False)
    secondary_email = forms.EmailField(label='Secondary Email', max_length=128, required=False)

    primary_phone = forms.CharField(label='Primary Phone', max_length=50, required=False)
    secondary_phone = forms.CharField(label='Secondary Phone', max_length=50, required=False)
    alt_phone = forms.CharField(label='Alt Phone', max_length=50, required=False)

    address1 = forms.CharField(label='Address1', max_length=50, required=False)
    city = forms.CharField(label='City', max_length=50, required=False)
    state = forms.CharField(label='State', max_length=50, required=False)
    postal_code = forms.CharField(label='Zip Code', max_length=50, required=False)
    # postal_code = forms.CharField(label='Zip Code', max_length=50, required=False)

    def clean_username(self):
        data = self.cleaned_data['username']

        return data

    def clean_email(self):
        data = self.cleaned_data['email']
        return data.lower()

class TeacherUploadForm(forms.ModelForm):
    class Meta:
        model = TeacherUpload
        fields = '__all__'

    def __init__(self, teacher, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['teacher'].queryset = Teacher.objects.filter(
            id=teacher.id
        )
        self.fields['teacher'].initial = teacher.id


class InstructorCSVUploadForm(forms.Form):
    file = forms.FileField(
        widget=forms.FileInput(attrs={'accept': 'text/csv'})
    )
