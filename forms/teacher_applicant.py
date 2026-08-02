
import logging
from datetime import date

from django import forms
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.core.validators import validate_email

from django_recaptcha.fields import ReCaptchaField

from cis.models.customuser import CustomUser
from ..models.highschool import HighSchool
from ..models.term import AcademicYear
from ..models.course import Course
from ..models.teacher_applicant import (
    TeacherApplication, ApplicantRecommendation,
    ApplicantSchoolCourse, ApplicationUpload,
    ApplicantCourseReviewer
)
from ..models.course import CourseAppRequirement

from cis.models.note import TeacherApplicationNote

from cis.utils import get_foreign_key_references

logger = logging.getLogger(__name__)
from form_fields import fields as FFields

from passwords.validators import (
    DictionaryValidator, LengthValidator, ComplexityValidator
)


class MigrateForm(forms.Form):
    
    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='migrate_teacher_application'
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

        self.fields['destination_record'].queryset = TeacherApplication.objects.all().exclude(
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
                    obj.teacher_application = data.get('destination_record')
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
    
class EditTeacherAppCourseUploadForm(forms.Form):
    
    id = forms.CharField(
        required=True,
        widget=forms.HiddenInput()
    )
    
    associated_with = forms.MultipleChoiceField(
        label='For',
        help_text='<b>Click the box next to each requirement for upload. If you select multiple boxes for one upload, this allows you to upload the same document for multiple requirements.</b>',
        choices=(),
        widget=forms.CheckboxSelectMultiple()
    )
    
    action = forms.CharField(
        widget=forms.HiddenInput,
        initial='edit_teacher_application_upload'
    )

    def __init__(self, teacher_application=None, upload_id=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.fields['id'].initial = upload_id

        interested_courses = ApplicantSchoolCourse.objects.filter(
            teacherapplication=teacher_application
        ).values_list('course__id', flat=True)

        course_reqs = CourseAppRequirement.objects.filter(
            course__id__in=interested_courses
        )
        req_list = []
        for req in course_reqs:
            req_list.append((str(req.id), f'{req.name} for {req.course.name}'))
        self.fields['associated_with'].choices = req_list

    def save(self, teacher_application):
        data = self.cleaned_data

        record = ApplicationUpload.objects.get(pk=data.get('id'))
        record.associated_with = data.get('associated_with')
        record.save()

        return record
        
class NoteReplyForm(forms.Form):
    
    message = forms.CharField(
        widget=forms.Textarea,
        label='Response',
        help_text=''
    )

    captcha = ReCaptchaField(
        label=''
    )

    def __init__(self, note, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def save(self, request, parent_note):
        note = TeacherApplicationNote(
            teacher_application=parent_note.teacher_application,
            note=self.cleaned_data.get('message'),
            createdby=parent_note.teacher_application.user,
            parent=parent_note.id,
            meta={
                'type':'response'
            }
        )
        note.save()

        return note

class ApplicantCourseFinalStatusForm(forms.Form):
    decision = forms.ChoiceField(
        choices=ApplicantSchoolCourse.STATUS_OPTIONS,
        label='Final Decision'
    )

    note = forms.CharField(
        widget=forms.Textarea,
        label='Note',
        required=False
    )

    application_course_id = forms.CharField(
        widget=forms.HiddenInput
    )

    def save(self):
        data = self.cleaned_data

        course = ApplicantSchoolCourse.objects.get(
            pk=data['application_course_id']
        )
        course.status = data['decision']
        course.note = data.get('note')
        course.save()

class ApplicantReviewForm(forms.Form):
    decision = forms.ChoiceField(
        choices=ApplicantCourseReviewer.STATUS_OPTIONS,
        label='Your Decision/Recommendation'
    )

    comment = forms.CharField(
        widget=forms.Textarea,
        label='Comment',
        help_text='This information is only visible to SUPA Staff',
        required=False
    )

    application_course_id = forms.CharField(
        widget=forms.HiddenInput
    )

class ApplicantCourseReviewerForm(forms.ModelForm):
    application_course_id = forms.CharField(
        widget=forms.HiddenInput,
        required=True
    )

    class Meta:
        model = ApplicantCourseReviewer

        fields = [
            'reviewer'
        ]

        labels = {
            'reviewer': 'Reviewer'
        }

    def __init__(self, application_course, *args, **kwargs):
        super().__init__(*args, **kwargs)

        faculty_coords = application_course.course.get_faculty_coordinators()
        self.fields['reviewer'].queryset = CustomUser.objects.filter(
            id__in=[fc.user.id for fc in faculty_coords]
        )
        self.fields['application_course_id'].initial = application_course.id

class EditTeacherApplicationForm(forms.Form):
    action = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )

    status = forms.ChoiceField(
        required=True,
        label='Status',
        choices=TeacherApplication.STATUS_OPTIONS
    )

    assigned_to = forms.CharField(
        required=False,
        label='Assigned To',
        widget=forms.HiddenInput
    )

    invite_to_interview = forms.CharField(
        required=False,
        widget=forms.HiddenInput,
        label='Invite to Interview Sent On'
    )

    interviewed_on = forms.CharField(
        required=False,
        widget=forms.HiddenInput,
        label='Interview Held On'
    )

    decision_letter_sent_on = forms.CharField(
        required=False,
        widget=forms.DateInput(),
        help_text='',
        label='Decision Letter Sent On'
    )

    participating_acad_year = forms.ChoiceField(
        required=False,
        choices=[],
        help_text='If approved to attend',
        label='Attending Academic Year'
    )
    
    psid = forms.CharField(
        required=False,
        help_text='If approved to attend',
        label='EMPLID'
    )

    # added_to_ps_on = forms.CharField(
    #     required=False,
    #     widget=forms.DateInput(),
    #     help_text='If approved to attend',
    #     label='Added to PS On'
    # )

    # imported_on = forms.CharField(
    #     required=False,
    #     widget=forms.DateInput(),
    #     help_text='If approved to attend',
    #     label='Added to PASS On'
    # )

    grad_credit = forms.ChoiceField(
        required=False,
        label='Graduate Credit/CTLE Option',
        help_text='If approved to attend',
        choices=[
            ('----', 'Select'),
            ('CTLE', 'CTLE'),
            ('Graduate Credit', 'Graduate Credit'),
            ('Not Interested', 'Not Interested'),
        ]
    )

    checklist = forms.MultipleChoiceField(
        required=False,
        label='Checklist',
        help_text='If approved to attend',
        widget=forms.CheckboxSelectMultiple(),
        choices=[
            ('Class Assigned', 'Class Assigned'),
            ('Hotel Room Requested', 'Hotel Room Requested'),
            ('NetID Activated', 'NetID Activated'),
            ('Imported into PS', 'Imported into PS')
        ]
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['assigned_to'].queryset = CustomUser.objects.filter(
            is_staff=True,
            is_active=True
        )

        self.fields['participating_acad_year'].choices = [
            (acad_year.id, acad_year.name) for acad_year in AcademicYear.objects.all()
        ]
        

    def save(self, teacher_application):
        data = self.cleaned_data

        teacher_application.status = data['status']
        # if data['assigned_to']:
        #     teacher_application.assigned_to = data['assigned_to']

        if data['invite_to_interview']:
            teacher_application.misc_info['invite_to_interview'] = data['invite_to_interview']

        if data['interviewed_on']:
            teacher_application.misc_info['interviewed_on'] = data['interviewed_on']

        if data['decision_letter_sent_on']:
            teacher_application.misc_info['decision_letter_sent_on'] = data['decision_letter_sent_on']
        
        teacher_application.misc_info['participating_acad_year'] = data.get('participating_acad_year')
        teacher_application.misc_info['grad_credit'] = data.get('grad_credit')
        teacher_application.misc_info['checklist'] = data.get('checklist')
        
        if data.get('psid'):
            teacher_application.user.psid = data.get('psid')
            teacher_application.user.save()

        teacher_application.save()
        return teacher_application

class AppUploadForm(forms.ModelForm):
    associated_with = forms.MultipleChoiceField(
        label='For',
        choices=()
    )

    class Meta:
        model = ApplicationUpload
        fields = [
            'upload'
        ]

        labels = {
            'upload': ''
        }

        help_texts = {
            'upload': 'Maximum file upload size is 8MB. For larger files please zip them prior to uploading.'
        }

    def __init__(self, teacher_application, *args, **kwargs):
        super().__init__(*args, **kwargs)

        interested_courses = ApplicantSchoolCourse.objects.filter(
            teacherapplication=teacher_application
        ).values_list('course__id', flat=True)

        course_reqs = CourseAppRequirement.objects.filter(
            course__id__in=interested_courses
        )
        req_list = []
        for req in course_reqs:
            req_list.append((str(req.id), f'{req.name}'))
        self.fields['associated_with'].choices = req_list

    def save(self, commit=False):
        record = super().save(commit=commit)

        data = self.cleaned_data
        record.associated_with = data.get('associated_with')
        return record

class EdBgForm(forms.Form):

    teacher_application = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )

    other_name = forms.CharField(
        required=False,
        label='Enter your name as it appears on your transcript(s), if different from your current name',
        help_text='Separate multiple names with commas'
    )

    ed_bg = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )

    transcripts = forms.ChoiceField(
        required=False,
        label='Select one of the statements below',
        choices=(
            (1, 'I will request, from each of the listed institutions, an official transcript be sent to SUPA'),
            (2, 'I believe that SUPA has official copies of all my current transcripts on file from a previous application')
        ),
        widget=forms.RadioSelect()
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
        label="If your Master’s degree is not specific to the discipline you will be teaching, please indicate the total number of Master’s-level credits in your discipline that you currently have completed:",
        help_text="For example, to teach a history course, a Master’s in History would be discipline specific, but a Master’s in Education would not. And so, if your M.Ed. includes any History department-designated course credits, you would note those credits here. Similarly, to teach an accounting course, a Master’s in Accounting would be discipline specific, but a Master’s in Economics or Statistics would not.",
        widget=forms.TextInput(
            attrs={
                'class': 'col-2'
            }
        )
    )

    grad_courses = forms.CharField(
        required=True,
        label='List graduate course work that particularly pertains to the Collge course that you are interested in teaching',
        widget=forms.Textarea
    )

    undergrad_program = forms.CharField(
        required=True,
        label='Describe your undergraduate program as it pertains to the Collge course that you are interested in teaching',
        widget=forms.Textarea
    )

    certified_states = forms.CharField(
        required=True,
        label='In what state(s) are you permanently certified to teach?',
        help_text='',
        widget=forms.TextInput(
            attrs={
                'class': 'col-8'
            }
        )
    )

    certified_subjects = forms.CharField(
        required=True,
        label='In what subject(s) are you permanently certified to teach?',
        help_text='',
        widget=forms.TextInput(
            attrs={
                'class': 'col-10'
            }
        )
    )
    highschool_years = forms.CharField(
        required=True,
        label='Total years of teaching High School',
        help_text='',
        widget=forms.TextInput(
            attrs={
                'class': 'col-2'
            }
        )
    )

    college_years = forms.CharField(
        required=True,
        label='Total years of teaching College',
        help_text='',
        widget=forms.TextInput(
            attrs={
                'class': 'col-2'
            }
        )
    )

    courses_taught = forms.CharField(
        required=True,
        label='Specific subjects you have taught or currently teaching that relate to the Collge course that you are interested in teaching',
        widget=forms.Textarea
    )

    def clean(self):
        self.cleaned_data = super().clean()

        institution = list(
            map(lambda x:str(x).strip(), self.data.getlist('ed_bg[institution]')))

        degree = list(
            map(lambda x:str(x).strip(), self.data.getlist('ed_bg[degree]')))

        major = list(
            map(lambda x:str(x).strip(), self.data.getlist('ed_bg[major]')))

        transcript_copy = self.data.getlist('ed_bg[transcript_copy]', {})
        transcript_recv = self.data.getlist('ed_bg[transcript_recv]', {})

        self.cleaned_data['ed_bg'] = {
            'institution':institution,
            'degree': degree,
            'major': major,
            'transcript_copy': transcript_copy,
            'transcript_recv': transcript_recv,
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

    def save(self, teacher_application):
        user = teacher_application.user
        if self.cleaned_data['other_name']:
            user.previous_names = self.cleaned_data['other_name']

        user.education_background = self.cleaned_data['ed_bg']
        user.save()

class RecommondationForm(forms.ModelForm):

    teacher_application = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )

    name = forms.CharField(
        required=True,
        label='Your Name',
        widget=forms.TextInput()
    )

    position = forms.CharField(
        required=True,
        label='Your Position',
        widget=forms.TextInput()
    )

    email = forms.CharField(
        required=True,
        label='Your Email',
        widget=forms.TextInput()
    )

    terms = forms.CharField(
        required=False,
        label='I have reviewed the <a href="#" target="_blank">SUPA Administrative Guide</a> and affirm that I understand and agree to the high school\'s responsibilities as a SUPA Partner school.',
        widget=forms.HiddenInput
    )

    years = forms.CharField(
        required=True,
        label='Number of years you have worked with or known the applicant',
        widget=forms.TextInput(
            attrs={
                'class':'col-md-2',
                'placeholder':'Ex: 2'
            }
        )
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # self.fields['name'].widget.attrs['readonly'] = True
        self.fields['email'].widget.attrs['readonly'] = True

    class Meta:
        model = ApplicantRecommendation
        fields = [
            'email',
            'name',
            'position',
            'years',
            'upload',
            'terms'
        ]

        labels = {
            'upload': 'Please upload your letter of recommendation:'
        }

        help_texts = {
            'upload': 'Maximum file upload size is 8MB.'
        }

class StaffRecUploadForm(RecommondationForm, forms.ModelForm):

    years = forms.CharField(
        required=False,
        label='Number of years you have worked with the applicant',
        widget=forms.TextInput(
            attrs={
                'class':'col-md-2',
                'placeholder':'Ex: 2'
            }
        )
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        del self.fields['terms']

        self.fields['email'].widget.attrs['readonly'] = False
        self.fields['name'].label = 'Name'
        self.fields['position'].label = 'Position'
        self.fields['email'].label = 'Email'

class RecommendationRequestForm(forms.Form):

    teacher_application = forms.CharField(
        required=True,
        widget=forms.HiddenInput()
    )

    name = forms.CharField(
        required=True,
        label='Name 1',
        help_text='This is how their email will be addressed. Include their first name and last name.',
        widget=forms.TextInput(
            attrs={
            'placeholder':'Ex: John Doe',
            'class':'col-md-8'
            }
        )
    )

    email = forms.EmailField(
        required=True,
        label='Email 1',
        widget=forms.EmailInput(
            attrs={
                'class':'col-md-7'
            }
        )
    )

    name_2 = forms.CharField(
        required=True,
        label='Name 2',
        help_text='This is how their email will be addressed. Include their first name and last name.',
        widget=forms.TextInput(
            attrs={
            'placeholder':'Ex: John Doe',
            'class':'col-md-8'
            }
        )
    )

    email_2 = forms.EmailField(
        required=True,
        label='Email 2',
        widget=forms.EmailInput(
            attrs={
                'class':'col-md-7'
            }
        )
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        initial = kwargs.get('initial')
        if initial:
            teacher_app = TeacherApplication.objects.get(
                pk=initial.get('teacher_application')
            )

            if teacher_app.has_recommender_submitted(initial.get('email')):
                self.fields['email'].widget.attrs['readonly'] = True
                self.fields['name'].widget.attrs['readonly'] = True
                self.fields['email'].help_text =  'Recommendation has been received'
            else:
                if initial.get('email'):
                    self.fields['email'].help_text = 'You can email this link - ' + teacher_app.get_recommendation_url(initial.get('email')) + ' or click the button below to resend the email'

            if teacher_app.has_recommender_submitted(initial.get('email_2')):
                self.fields['email_2'].widget.attrs['readonly'] = True
                self.fields['name_2'].widget.attrs['readonly'] = True
                self.fields['email_2'].help_text =  'Recommendation has been received'
            else:
                if initial.get('email_2'):
                    self.fields['email_2'].help_text = 'You can email this link - ' + teacher_app.get_recommendation_url(initial.get('email_2')) + ' or click the button below to resend the email'

    def clean_email(self):
        return self.data.get('email', '').lower()
    
    def clean_email_2(self):
        return self.data.get('email_2', '').lower()
    
    def clean(self):
        cleaned_data = super().clean()

        if cleaned_data.get('email') == cleaned_data.get('email_2'):
            raise ValidationError('Looks like both recommenders have the same email. Please enter unique email addresses')

    def save(self):
        from datetime import datetime
        cleaned_data = self.cleaned_data

        teacher_app = TeacherApplication.objects.get(
            pk=cleaned_data['teacher_application']
        )

        teacher_app.update_recommendation_request_info(
            cleaned_data['name'],
            cleaned_data['email'],
            cleaned_data['name_2'],
            cleaned_data['email_2'],
        )

        teacher_app.send_recommendation_request(
            cleaned_data['name'],
            cleaned_data['email']
        )

        teacher_app.send_recommendation_request(
            cleaned_data['name_2'],
            cleaned_data['email_2']
        )

        return True


class AddCourseForm(forms.Form):
    
    id = forms.CharField(
        required=True,
        widget=forms.HiddenInput()
    )

    course = forms.ModelMultipleChoiceField(
        queryset=None,
        label='Course(s)',
    )

    academic_year = forms.ModelChoiceField(
        queryset=None,
        label='Starting Academic Year',
    )

    action = forms.CharField(
        widget=forms.HiddenInput,
        initial='add_teacher_application_course'
    )

    def __init__(self, teacher_application=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.fields['academic_year'].queryset = AcademicYear.objects.all().order_by('-name')
        self.fields['course'].queryset = Course.objects.filter(
            status__iexact='active'
        ).exclude(
            id__in=ApplicantSchoolCourse.objects.filter(
                teacherapplication=teacher_application
            ).values_list('course__id', flat=True)
        )

        if teacher_application:
            self.fields['id'].initial = teacher_application.id
        
    def save(self, teacher_application):
        data = self.cleaned_data

        courses = data.get('course')
        for course in courses:
            try:
                app_course = ApplicantSchoolCourse(
                    teacherapplication=teacher_application,
                    course=course,
                    starting_academic_year=data.get('academic_year'),
                    highschool=teacher_application.highschool,
                    misc_info={}
                )

                app_course.save()
            except Exception as e:
                print(e)

        # add reviewers if applicable
        teacher_application.notify_status_change(teacher_application.status)
        return teacher_application
    
class EditSchoolCourseForm(forms.Form):
    
    id = forms.CharField(
        required=True,
        widget=forms.HiddenInput()
    )

    highschool = forms.ChoiceField(
        choices=('', ''),
        label='High School',
        help_text='Select the school at which you instructor is applying to teach.'
    )

    action = forms.CharField(
        widget=forms.HiddenInput,
        initial='edit_teacher_application_highschool'
    )

    def __init__(self, teacher_application=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        highschools = [
            ('', 'Select')
        ]
        highschools += [
            (h.id, h.name) for h in HighSchool.objects.filter(
                status__in=['Active']
            )
        ]
        self.fields['highschool'].choices = highschools

        if teacher_application:
            self.fields['id'].initial = teacher_application.id
            if teacher_application.highschool:
                self.fields['highschool'].initial = teacher_application.highschool.id

    def save(self, teacher_application):
        data = self.cleaned_data

        highschool = HighSchool.objects.get(pk=data.get('highschool'))
        teacher_application.highschool = highschool
        teacher_application.save()

        return teacher_application
    
class SchoolCourseForm(forms.Form):

    id = forms.CharField(
        required=True,
        widget=forms.HiddenInput()
    )

    highschool_subsection = FFields.LongLabelField(
        required=False,
        label='',
        initial='Select your School',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'h-100 border-0',
                'style': 'padding-left: 0; font-size: 1.3em;'
            }
        )
    )

    highschool = forms.ChoiceField(
        choices=('', ''),
        label='High School',
        help_text='Select the school at which you are applying to teach. If your school is not in the list please contact us at <a href="mailto:help@canusia.com">info@canusia.com</a>'
    )

    new_school_name = forms.CharField(
        label='School Name',
        max_length=128,
        required=False,
        widget=forms.HiddenInput
    )

    student_body = forms.CharField(
        label='Approximate size of the student body',
        max_length=4,
        required=False,
        widget=forms.HiddenInput
    )

    grades_served = forms.CharField(
        label='Grades Served by School',
        required=False,
        widget=forms.HiddenInput
    )

    instructional_days = forms.CharField(
        label='Number of Instructional Days',
        max_length=3,
        required=False,
        widget=forms.HiddenInput
    )

    academic_supports = forms.CharField(
        label='Describe the Academic supports available for students who might struggle with course expectations',
        required=False,
        widget=forms.HiddenInput
    )

    currently_offering = forms.CharField(
        label='Does your school currently offer Collge courses?',
        required=False,
        widget=forms.HiddenInput
    )

    course_subsection = FFields.LongLabelField(
        required=False,
        label='',
        initial='Course Information',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'h-100 border-0',
                'style': 'padding-left: 0; font-size: 1.3em;'
            }
        )
    )

    course_description = FFields.LongLabelField(
        required=False,
        label='',
        initial='override this in __init__',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'border-0 bg-light h-100'
            }
        )
    )

    course = forms.ChoiceField(
        label='Which course are you applying to teach?',
        required=True,
        choices=()
    )

    starting_year = forms.ChoiceField(
        label='Which academic year are you applying to begin teaching?',
        choices=(),
        required=True
    )

    teacher_application = forms.CharField(
        widget=forms.HiddenInput,
        required=False
    )

    first_time = forms.CharField(
        label='Is this the first time this course would be offered at your school?',
        widget=forms.HiddenInput,
        required=False
    )

    replace_instructor = forms.CharField(
        label='Are you applying to replace or substitute for a current instructor?',
        widget=forms.HiddenInput,
        required=False
    )

    instructor_name = forms.CharField(
        label='Name of instructor you will replace/substitute, if known',
        widget=forms.HiddenInput,
        required=False
    )

    start_date = forms.CharField(
        max_length=12,
        widget=forms.HiddenInput,
        required=False
    )

    end_date = forms.CharField(
        max_length=12,
        widget=forms.HiddenInput,
        required=False
    )

    def save(self, teacher_application):
        data = self.cleaned_data

        if data.get('highschool', None):
            if data['highschool'] == '-1':
                highschool = HighSchool(
                    name=data['new_school_name']+'**',
                    status='Pending'
                )
                highschool.save()
            else:
                highschool = HighSchool.objects.get(
                    pk=data['highschool']
                )
        else:
            highschool = teacher_application.highschool

        if data['id'] == '-1':
            teacher_course = ApplicantSchoolCourse()
            teacher_course.teacherapplication = teacher_application
        else:
            teacher_course = ApplicantSchoolCourse.objects.get(
                id=data['id']
            )

        teacher_course.highschool = highschool
        teacher_course.course = Course.objects.get(pk=data['course'])
        teacher_course.starting_academic_year = AcademicYear.objects.get(
            pk=data['starting_year']
        )

        misc_data = {
            # 'student_body':data['student_body'],
            # 'grades_served':data['grades_served'],
            # 'instructional_days':data['instructional_days'],
            # 'academic_supports':data['academic_supports'],
            'first_time':data['first_time'],
            'replace_instructor':data['replace_instructor'],
            'instructor_name':data['instructor_name'],
            'start_date':'',
            'end_date':''
        }
        
        # try:
        #     if data['start_date']:
        #         misc_data['start_date'] = data['start_date'].strftime('%m/%d/%Y')
        #         misc_data['end_date'] = data['end_date'].strftime('%m/%d/%Y')
        # except AttributeError:
        #     logger.error('Invalid date received')
        #     logger.error(data)
        #     pass

        teacher_course.misc_info = misc_data
        teacher_course.save()

        return teacher_course

    def __init__(self, teacher_application, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # init course, high school and academic year choices
        highschools = [
            ('', 'Select')
        ]
        highschools += [
            (h.id, h.name) for h in HighSchool.objects.filter(
                status__in=['Active']
            )
        ]
        self.fields['highschool'].choices = highschools

        # Available courses to select from
        available_courses = Course.objects.filter(
            status='Active',
            meta__available_for_si='1'
        )

        if teacher_application and teacher_application.highschool:
            del self.fields['highschool']
            del self.fields['highschool_subsection']
            del self.fields['new_school_name']
            del self.fields['student_body']
            del self.fields['grades_served']
            del self.fields['instructional_days']
            del self.fields['academic_supports']
            del self.fields['currently_offering']

        try:
            interested_course = ApplicantSchoolCourse.objects.filter(
                teacherapplication=teacher_application
            ).first()
            self.fields['course_subsection'].initial = 'Select Course'
            available_courses = Course.objects.filter(
                status='Active',
                cohort=interested_course.course.cohort
            )
        except ApplicantSchoolCourse.DoesNotExist:
            pass
        except AttributeError:
            pass
            
        course_choices = [('', 'Select')] + [
            (c.id, str(c) + ': ' + c.title) for c in available_courses
        ]
        self.fields['course'].choices = course_choices

        self.fields['starting_year'].choices = [('', 'Select')] + [
            (a.id, a.name) for a in AcademicYear.objects.filter(
                hs_start_date__gte=date.today(),
                hs_end_date__gte=date.today()
            )
        ]

    def clean(self):
        data = super().clean()
        return data

class TeacherApplicantForm(forms.Form):
    """
    Teacher Applicant Form
    """
    first_name = forms.CharField(
        label='First Name',
        max_length=128,
        widget=forms.TextInput(attrs={'class': 'col-md-6 col-sm-12'}))

    middle_name = forms.CharField(
        label='Middle Name or Initial',
        max_length=128,
        required=False,
        widget=forms.TextInput(attrs={'class': 'col-md-4 col-sm-12'}))

    last_name = forms.CharField(
        label='Last Name',
        max_length=128,
        widget=forms.TextInput(attrs={'class': 'col-md-8 col-sm-12'}))

    maiden_name = forms.CharField(
        label='Maiden Name (if applicable)',
        max_length=128,
        required=False,
        widget=forms.TextInput(attrs={'class': 'col-md-8 col-sm-12'}))

    email = forms.EmailField(
        label='High School email address',
        widget=forms.TextInput(attrs={'class': 'col-md-5 col-sm-6'}))

    confirm_email = forms.EmailField(
        label='Confirm High School email address',
        widget=forms.TextInput(attrs={'class': 'col-md-5 col-sm-6'}))

    secondary_email = forms.EmailField(
        label='Personal Email ',
        widget=forms.TextInput(attrs={'class': 'col-md-5 col-sm-6'}))

    alt_email = forms.EmailField(
        label='',
        required=False,
        widget=forms.HiddenInput
    )

    secondary_phone = forms.CharField(
        label='Personal Phone (10-digit)',
        max_length=15,
        help_text='10 digits (i.e. 5551231234)',
        widget=forms.TextInput(attrs={'class': 'col-md-5 col-sm-6'}))

    primary_phone = forms.CharField(
        label='Work Phone (10-digit)',
        max_length=15,
        help_text='10 digits (i.e. 5551231234)',
        widget=forms.TextInput(attrs={'class': 'col-md-5 col-sm-6'}))

    alt_phone = forms.CharField(
        label='Other Phone (10-digit)',
        max_length=15,
        required=False,
        help_text='10 digits (i.e. 5551231234)',
        widget=forms.TextInput(attrs={'class': 'col-md-5 col-sm-6'}))

    date_of_birth = forms.DateField(
        label='Date of Birth',
        required=True,
        help_text='mm/dd/yyyy',
        widget=forms.DateInput(attrs={'class': 'col-md-5 col-sm-6'}))

    ssn = forms.CharField(
        label='SSN',
        required=False,
        help_text='US SSN Eg: xxx-xx-xxxx',
        widget=forms.TextInput(attrs={'class': 'col-md-5 col-sm-6'}))

    home_address = forms.CharField(
        label='Home Address',
        max_length=128,
        help_text='Do not enter symbols (e.g. #). You may include Apt, Unit, Box etc.',
        widget=forms.TextInput(attrs={'class': 'col-md-8 col-sm-12'}))

    city = forms.CharField(
        label='City',
        max_length=128,
        widget=forms.TextInput(attrs={'class': 'col-md-5 col-sm-6'}))

    state = forms.CharField(
        label='State',
        max_length=128,
        widget=forms.TextInput(attrs={'class': 'col-md-5 col-sm-6'}))

    zip_code = forms.CharField(
        label='Zip/Postal Code',
        max_length=10,
        widget=forms.TextInput(attrs={'class': 'col-md-4 col-sm-6'}))

    country = forms.CharField(
        label='Country',
        max_length=50,
        widget=forms.TextInput(attrs={'class': 'col-md-4 col-sm-6'}))

    password = forms.CharField(
        max_length=128,
        label="Create Password or Passphrase",
        validators=[
            DictionaryValidator(words=['banned_word'], threshold=0.9),
            LengthValidator(min_length=8),
            ComplexityValidator(complexities=dict(
                UPPER=1,
                LOWER=1,
                DIGITS=1
            ))
        ],
        help_text='Enter a strong password that is at least 8 characters',
        widget=forms.PasswordInput(attrs={'class': 'col-md-6, col-sm-12'})
    )

    confirm_password = forms.CharField(
        max_length=128,
        label="Retype Password or Passphrase",
        widget=forms.PasswordInput(attrs={'class': 'col-md-6, col-sm-12'})
    )

    captcha = ReCaptchaField(
        label=''
    )

    def clean_email(self):
        """
        Email should not exist in the system. Checks for duplicate in
        column 'email' or 'alt_email' of CustomUser
        """
        data = self.cleaned_data.get('email').lower()
       
        if CustomUser.objects.filter(
                Q(email__iexact=data) |
                Q(username__iexact=data) |
                Q(secondary_email__iexact=data)).exists():
            raise ValidationError(_("This email is already registered in the system. Please login or choose a different email"), code='invalid')

        return data

    def clean_confirm_email(self):
        email = self.data.get('email', '')
        confirm_email = self.data['confirm_email']

        if email != confirm_email:
            raise ValidationError(_("The email addresses don't match. Please retry again."))
        return confirm_email

    def clean_confirm_password(self):
        password = self.cleaned_data.get('password', '')
        confirm_password = self.cleaned_data['confirm_password']

        if password != confirm_password:
            raise ValidationError(_("The passwords don't match. Please retry again."))
        return confirm_password

    def clean_phone(self):
        import re
        phone_num = (re.findall(r'\d+', self.cleaned_data['phone']))
        phone_num = ''.join(phone_num)

        if len(phone_num) != 10:
            raise ValidationError(_("Enter a 10 digit phone number. Eg: 5551231234"))
        return phone_num

    def clean(self):
        from cis.utils import is_valid_address

        cleaned_data = super().clean()
        
        address = self.cleaned_data['home_address']
        city = self.cleaned_data['city']
        state = self.cleaned_data['state']
        zipcode = self.cleaned_data['zip_code']

        # (is_valid, message, home_address, city, state, zipcode) = is_valid_address(address, city, state, zipcode)

        # if not is_valid:
        #     self.add_error(None, f'{message}. The address you entered is not valid. Please remove any symbols(#). You may include Apt, Unit, Box etc')
        #     self.add_error('home_address', 'Enter a valid address, city, zip code')
        # else:
        #     cleaned_data['home_address'] = home_address
        #     cleaned_data['city'] = city
        #     cleaned_data['state'] = state
        #     cleaned_data['zip_code'] = zipcode

        return cleaned_data

class TeacherApplicantProfileForm(TeacherApplicantForm, forms.Form):

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.user = user

        del self.fields['password']
        del self.fields['confirm_password']
        del self.fields['confirm_email']
        del self.fields['captcha']

        self.fields['first_name'].initial = user.first_name
        self.fields['last_name'].initial = user.last_name
        self.fields['middle_name'].initial = user.middle_name
        self.fields['email'].initial = user.email
        self.fields['ssn'].initial = user.ssn

        if user.date_of_birth:
            self.fields['date_of_birth'].initial = user.date_of_birth.strftime('%m/%d/%Y')

        self.fields['secondary_email'].initial = user.secondary_email
        self.fields['alt_email'].initial = user.alt_email
        self.fields['secondary_phone'].initial = user.secondary_phone
        self.fields['primary_phone'].initial = user.primary_phone
        self.fields['alt_phone'].initial = user.alt_phone
        self.fields['home_address'].initial = user.address1
        self.fields['city'].initial = user.city
        self.fields['state'].initial = user.state
        self.fields['zip_code'].initial = user.postal_code
        # self.fields['country'].initial = user.country
        
    def clean_email(self):
        email = self.cleaned_data['email'].lower()

        try:
            user = CustomUser.objects.filter(
                email__iexact=email
            ).exclude(id=self.user.id)

            if user:
                raise ValidationError(_('This email is already registered. Please use a different email or contact our office for assistance'))
            return email
        except CustomUser.DoesNotExist:
            return email

    def save(self):
        data = self.cleaned_data
        user = self.user

        user.first_name = data['first_name']
        user.last_name = data['last_name']
        user.middle_name = data['middle_name']

        user.email = data['email']
        user.username = data['email']
        user.secondary_email = data['secondary_email']
        user.alt_email = data['alt_email']

        user.ssn = data.get('ssn')
        user.date_of_birth = data.get('date_of_birth')

        user.primary_phone = data['primary_phone']
        user.secondary_phone = data['secondary_phone']
        user.alt_phone = data['alt_phone']

        user.address1 = data['home_address']
        user.city = data['city']
        user.state = data['state']
        user.postal_code = data['zip_code']
        user.country = data['country']

        user.save()
        return user
