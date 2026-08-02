# student form
import re, uuid, json
import datetime

from django import forms
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from django.utils.safestring import mark_safe

from passwords.validators import (
    DictionaryValidator, LengthValidator, ComplexityValidator
)

from cis.models.term import Term
from cis.models.course import Campus
from cis.models.customuser import CustomUser
from cis.models.student import (
    Student, ParentConsent, StudentAgreement, StudentFerpa,
    StudentCampusID, StudentRecommendation, StudentSupportingDocument,
    StudentTuitionAssistance, StudentTuitionAssistanceDocument
)
from cis.models.note import StudentNote

from cis.models.section import StudentDropRequest, StudentRegistration
from cis.models.highschool import HighSchool
from cis.models.customuser import CustomUser

from cis.utils import (
    YES_NO_OPTIONS, STUDENT_GRADE_OPTIONS, STUDENT_GPA_OPTIONS,
    YES_NO_SELECT_OPTIONS,
    COUNTRY_LIST,
    active_term,
    registration_terms, user_has_cis_role, is_valid_address
)
from form_fields import fields as FFields

from django_recaptcha.fields import ReCaptchaField

from cis.settings.signup import signup as signup_settings
from cis.forms.utils import with_meta

import logging
logger = logging.getLogger(__name__)


from student_transactions.models import StudentTransaction
class BulkPaymentForm(forms.Form):
    
    action = forms.CharField(
        widget=forms.HiddenInput,
        initial='add_payment'
    )

    term = forms.ModelChoiceField(
        queryset=None,
        required=True,
        label='Payment Term'
    )

    check_number = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.TextInput(
            attrs={
                'class': 'col-3'
            }
        )
    )

    check_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class':'col-4'})
    )
        
    description = forms.CharField(
        required=False,
        max_length=500
    )

    def __init__(self, record_ids=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['term'].queryset = Term.objects.all().order_by('-code')

        if record_ids:

            records = Student.objects.filter(
                id__in=record_ids,
            ).order_by('user__last_name')

            for record in records:
                self.fields[f'{record.id}_amount'] = forms.DecimalField(
                    label=f'School Payment Amount for {record}',
                    required=False,
                    initial=round(float(record.current_school_balance), 2),
                    widget=forms.TextInput(
                        attrs={
                            'placeholder': '0.00',
                            'class': 'form-control col-md-3'
                        }
                    )
                )
                self.fields[f'{record.id}_amount'].widget.attrs['data-student'] = record.id
                
            # self.fields['record_ids'].choices = record_choices
            # self.fields['record_ids'].initial = record_ids
        # else:
        #     record_choices = []
        #     for record_id in kwargs.get('data').getlist('record_ids'):
        #         record_choices.append(
        #             (record_id, record_id)
        #         )

        #     self.fields['record_ids'].choices = record_choices
        #     self.fields['record_ids'].required = False

    def save(self, request=None):
        cleaned_data = self.cleaned_data
        data = self.data

        for key, value in data.items():
            if key.endswith('_amount'):
                student_id = key.split('_')[0]
                amount = data.get(key)

                if amount:
                    try:
                        amount = float(amount)
                    except Exception as e:
                        raise ValidationError('Please enter a valid amount')

                    if amount > 0:
                        student = Student.objects.get(pk=student_id)
                        term = cleaned_data.get('term')

                        transaction = StudentTransaction(
                            student=student,
                            term=term,
                            t_type='credit',
                            amount=amount,
                            label='school_pay',
                            description=cleaned_data['description'],
                            created_by=request.user,
                            meta={
                                'check_number': cleaned_data.get('check_number'),
                                'check_date': cleaned_data.get('check_date').strftime('%m/%d/%Y') if cleaned_data.get('check_date') else ''
                            }
                        )
                        transaction.save()
        print(data, cleaned_data)

class StudentProfileReviewForm(forms.Form):
    
    needs_update = forms.ChoiceField(
        choices=YES_NO_SELECT_OPTIONS,
        label='Do you need to update any information that is shown above?',
        help_text='',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}))

class StudentVerifyAccountForm(forms.Form):
    """
    Student Form
    """
    verification_id = forms.CharField(
        label='Student Legal First Name',
        max_length=128,
        widget=forms.HiddenInput
    )


class MarkStudentWaiverForm(forms.Form):
    
    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='mark_waiver'
    )

    recommendations = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],
        label='Student(s)'
    )

    waiver_approved = forms.ChoiceField(
        choices=[
            ('', 'Select'),
            ('Yes', 'Yes'),
            ('No', 'No'),
        ],
        required=True
    )

    note = forms.CharField(
        widget=forms.Textarea,
        required=False
    )

    def __init__(self, recommendation_ids, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if kwargs.get('data'):
            data = kwargs.get('data')
            student_ids = data.getlist('recommendations')

            records = StudentRecommendation.objects.filter(
                id__in=student_ids
            )
        else:
            records = StudentRecommendation.objects.filter(
                id__in=recommendation_ids
            )
    
        self.fields['recommendations'].choices = [
            (str(recommendation.id), f"{recommendation.student} - ({recommendation.student.user.email})") for recommendation in records
        ]
        self.fields['recommendations'].initial = [
            str(recommendation.id) for recommendation in records
        ]

    def save(self, request, commit=True):
        data = self.cleaned_data

        recommendations = StudentRecommendation.objects.filter(id__in=data.get('recommendations'))
        for rec in recommendations:
            recommendation = rec.recommendation
            recommendation['waiver_approved'] = data.get('waiver_approved')

            rec.recommendation = recommendation
            rec.save()

            rec.student.add_note(
                request.user,
                f'Added recommendation waiver - {recommendation["waiver_approved"]}'
            )

        return recommendations

class UpdateGPAForm(forms.Form):
    
    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='update_gpa'
    )

    recommendations = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],
        label='Student(s)'
    )

    student_gpa = forms.CharField(
        label='Student\'s Unweighted GPA',
        widget=forms.TextInput(
            attrs={
                'class': 'col-md-3'
            }
        ),
        required=True
    )

    note = forms.CharField(
        widget=forms.Textarea,
        required=False
    )

    def __init__(self, recommendation_ids, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if kwargs.get('data'):
            data = kwargs.get('data')
            student_ids = data.getlist('recommendations')

            records = StudentRecommendation.objects.filter(
                id__in=student_ids
            )
        else:
            records = StudentRecommendation.objects.filter(
                id__in=recommendation_ids
            )
    
        self.fields['recommendations'].choices = [
            (str(recommendation.id), f"{recommendation.student} - ({recommendation.student.user.email})") for recommendation in records
        ]
        self.fields['recommendations'].initial = [
            str(recommendation.id) for recommendation in records
        ]

    def save(self, request, commit=True):
        data = self.cleaned_data

        recommendations = StudentRecommendation.objects.filter(id__in=data.get('recommendations'))
        for rec in recommendations:
            recommendation = rec.recommendation
            recommendation['student_gpa'] = data.get('student_gpa')

            rec.recommendation = recommendation
            rec.save()

            rec.student.add_note(
                request.user,
                f'Update GPA - {recommendation["student_gpa"]}'
            )

        return recommendations


class ChangeApplicationStatusForm(forms.Form):
    application_status = forms.ChoiceField(
        label='Application Status',
        choices=[],
        required=True,
    )
    note = forms.CharField(
        label='Note (optional)',
        widget=forms.Textarea(attrs={'rows': 3}),
        required=False,
    )

    def __init__(self, student_ids, *args, **kwargs):
        from cis.models.student import Student
        super().__init__(*args, **kwargs)
        self._student_ids = list(student_ids)
        self.fields['application_status'].choices = list(Student.APPLICATION_STATUS_CHOICES)

    def save(self, request):
        from cis.models.student import Student
        data = self.cleaned_data
        new_status = data['application_status']
        note = data.get('note') or ''

        students = Student.objects.filter(id__in=self._student_ids)
        updated = 0
        for student in students:
            old_status = student.application_status
            if old_status == new_status:
                continue
            student.application_status = new_status
            student.save(update_fields=['application_status'])
            msg = f'Application status changed: {old_status} -> {new_status}'
            if note:
                msg += f' ({note})'
            student.add_note(request.user, msg)
            updated += 1
        return updated


class StudentSupportingDocumentForm(forms.ModelForm):

    action = forms.CharField(
        widget=forms.HiddenInput
    )

    # Rendered as a dropdown populated from the CE-configurable
    # support_docs setting (see __init__). Shared by the CE, student, and
    # any HS-admin upload entry points.
    document_type = forms.ChoiceField(
        required=False,
        choices=[],
        label='Document Type',
    )


    class Meta:
        model = StudentSupportingDocument
        fields = '__all__'

        # `status` is set via the CE bulk action, not at upload time.
        exclude = ['meta', 'status']

        widgets = {
            'student': forms.HiddenInput,
        }

        labels = {
            'media': 'Select File',
            'description': 'Note (optional)'
        }

        help_texts = {

        }

    def __init__(self, student, term=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['action'].initial = 'upload_support_doc'
        self.fields['student'].initial = student.id

        from cis.settings.support_docs import support_docs
        self.fields['document_type'].choices = (
            [('', 'Select type')] + [(t, t) for t in support_docs.get_types()]
        )

        from cis.utils import active_term
        if not term:
            term = active_term()

        if term:
            self.fields['term'].initial = term
            self.fields['term'].widget = forms.HiddenInput()


class MarkSupportDocStatusForm(forms.Form):
    """Bulk-set the status of selected StudentSupportingDocument rows.

    Status choices come from the CE-configurable support_docs setting.
    Mirrors MarkStudentWaiverForm: a record_ids checkbox list (to review the
    selection) plus the value to apply.
    """

    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='mark_support_doc_status'
    )

    record_ids = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],
        label='Document(s)'
    )

    status = forms.ChoiceField(
        required=True,
        choices=[],
        label='Status'
    )

    def __init__(self, doc_ids=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        from cis.settings.support_docs import support_docs
        self.fields['status'].choices = (
            [('', 'Select')] + [(s, s) for s in support_docs.get_statuses()]
        )

        if kwargs.get('data'):
            ids = kwargs['data'].getlist('record_ids')
            records = StudentSupportingDocument.objects.filter(id__in=ids)
        else:
            records = StudentSupportingDocument.objects.filter(id__in=doc_ids or [])

        self.fields['record_ids'].choices = [
            (str(doc.id), f'{doc.student} - {doc.filename}') for doc in records
        ]
        self.fields['record_ids'].initial = [str(doc.id) for doc in records]

    def save(self, request=None):
        data = self.cleaned_data
        status = data.get('status')
        # Per-instance save (not QuerySet.update) so the status-change signal
        # fires for each document.
        docs = list(StudentSupportingDocument.objects.filter(id__in=data.get('record_ids')))
        for doc in docs:
            doc.status = status
            doc.save()
        return docs


class MigrateStudentForm(forms.Form):
    
    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='migrate_student'
    )

    destination_student_id = forms.CharField(
        required=True,
        label='Destination Student UUID',
        help_text='This is a 36 character ID available in student details.<br>Looks like 52885f2e-9276-4673-ac9b-343191089285'
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

    class Media:
        js = [
            'js/student_migration.js'
        ]

    def clean_destination_student_id(self):
        data = self.cleaned_data.get('destination_student_id')

        try:
            if not Student.objects.filter(
                id=data
            ).exists():
                raise ValidationError('The ID entered did not match any student')
        except:
            raise ValidationError('The ID entered did not match any student')
        return data

    def save(self, request, student):
        data = self.cleaned_data

        destination_student = Student.objects.get(pk=data.get('destination_student_id'))

        destination_student.add_note(
            request.user,
            f'Moving records from {student}, ' + ', '.join(data.get('move_items'))
        )

        success, message = True, []
        if 'registrations' in data.get('move_items'):
            try:
                StudentRegistration.objects.filter(
                    student=student
                ).update(
                    student=destination_student
                )

                message.append(
                    'Successfully moved registrations'
                )
            except Exception as e:
                success = False
                destination_student.add_note(
                    request.user,
                    f'Unable to move registrations records from {student}, ' + str(e)
                )
                message.append(
                    'Unable to move registrations ' + str(e)
                )

        if 'student_recommendation' in data.get('move_items'):
            try:
                StudentRecommendation.objects.filter(
                    student=student
                ).update(
                    student=destination_student
                )
                message.append('Successfully moved recommendations.')
            except Exception as e:
                destination_student.add_note(
                    request.user,
                    f'Unable to move recommendation records from {student}, ' + str(e)
                )
                success = False
                message.append('Unable to move recommendations ' + str(e))

        if 'support_docs' in data.get('move_items'):
            try:
                StudentSupportingDocument.objects.filter(
                    student=student
                ).update(
                    student=destination_student
                )
                message.append('Successfully moved support docs.')
            except Exception as e:
                destination_student.add_note(
                    request.user,
                    f'Unable to move support doc. records from {student}, ' + str(e)
                )
                
                success = False
                message.append('Unable to move support docs. ' + str(e))
                
        if 'student_agreements' in data.get('move_items'):
            try:
                StudentAgreement.objects.filter(
                    student=student
                ).update(
                    student=destination_student
                )
                message.append('Successfully moved student agreements.')
            except Exception as e:
                destination_student.add_note(
                    request.user,
                    f'Unable to move stuent agreements records from {student}, ' + str(e)
                )
                
                success = False
                message.append('Unable to move student agreements ' + str(e))
                
        if 'parent_consent' in data.get('move_items'):
            try:
                ParentConsent.objects.filter(
                    student=student
                ).update(
                    student=destination_student
                )
                message.append('Successfully moved parent consents.')
            except Exception as e:
                destination_student.add_note(
                    request.user,
                    f'Unable to move parent consent records from {student}, ' + str(e)
                )
                
                success = False
                message.append('Unable to move parent consents ' + str(e))
                
        if 'notes' in data.get('move_items'):
            try:
                StudentNote.objects.filter(
                    student=student
                ).update(
                    student=destination_student
                )
                message.append('Successfully moved notes.')
            except Exception as e:
                destination_student.add_note(
                    request.user,
                    f'Unable to move notes records from {student}, ' + str(e)
                )
                
                success = False
                message.append('Unable to move notes ' + str(e))

        return (success, message)

class StudentCampusIDForm(forms.Form):
    id = forms.CharField(
        required=True,
        widget=forms.HiddenInput()
    )

    student_id = forms.CharField(
        required=True,
        widget=forms.HiddenInput()
    )

    campus = forms.ModelChoiceField(
        required=True,
        queryset=None
    )

    username = forms.CharField(
        widget=forms.TextInput(),
        required=False
    )

    user_id = forms.CharField(
        widget=forms.TextInput(),
        label='User ID'
    )

    email = forms.EmailField(
        widget=forms.EmailInput(),
        required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['campus'].queryset = Campus.get_all()

    def save(self):
        data = self.cleaned_data

        if data['id'] == '-1':
            student_id = StudentCampusID()
            student_id.student = Student.objects.get(pk=data['student_id'])
        else:
            student_id = StudentCampusID.objects.get(
                pk=data['id']
            )
        student_id.campus = data['campus']
        student_id.username = data['username'].lower()
        student_id.user_id = data['user_id']
        student_id.email = data['email']

        student_id.save()
        return student_id

class StudentStateQForm(forms.Form):

    student_id = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )

    father_education = forms.ChoiceField(
        choices=Student.PARENT_EDUCATION_OPTIONS,
        label='Father\'s Education Level'
    )

    mother_education = forms.ChoiceField(
        choices=Student.PARENT_EDUCATION_OPTIONS,
        label='Mother\'s Education Level'
    )

    military_family = forms.ChoiceField(
        choices=YES_NO_SELECT_OPTIONS,
        label='Are you a military family member?'
    )

    homeless = forms.ChoiceField(
        choices=YES_NO_SELECT_OPTIONS,
        label='Are you homeless?'
    )

    education_plans = forms.ChoiceField(
        choices=[
            ('complete_at_butler', 'Complete degree/certificate at Butler only'),
            ('transfer', 'Complete degree/certificate then transfer')
        ],
        widget=forms.RadioSelect,
        label='What is your education goal?'
    )

    plan_to_transfer = forms.ChoiceField(
        choices=YES_NO_SELECT_OPTIONS,
        label='Do you plan to transfer after Butler?'
    )

    transfer_where = forms.CharField(
        required=False,
        label='If yes, where?'
    )

    state_q_header = FFields.ReadOnlyField(
        required=False,
        label=mark_safe('<h4>Per Kansas state statute (KAR 28-1-30) for prevention and control of TB please answer the questions below. Failure to complete as instructed could result in being dropped from classes. College Health will contact students indicating "Y" or refusal to answer the items below:</h4>'),
        initial='',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'border-0 bg-light h-100'
            }
        )
    )

    foreign_born = forms.ChoiceField(
        choices=YES_NO_SELECT_OPTIONS,
        label='Are you foreign born?'
    )

    birth_place = forms.CharField(
        required=False,
        label='If yes, where?'
    )

    been_outside_us = forms.ChoiceField(
        choices=YES_NO_SELECT_OPTIONS,
        label='You\'ve been outside the U.S. more than 30 days.?'
    )

    outside_where = forms.CharField(
        required=False,
        label='If yes, where?'
    )

    contact_with_tb = forms.ChoiceField(
        choices=YES_NO_SELECT_OPTIONS,
        label='You have ever been in contact with a person who has been diagnosed with known active Tuberculosis (TB).'
    )

    any_symptoms = forms.ChoiceField(
        choices=YES_NO_SELECT_OPTIONS,
        label='You have recently had any of the following unexplained signs or symptoms: coughing up blood, chest pain, weight loss or loss of appetite, fever or chills, cough (more than 3 weeks), fatigue, respiratory difficulty, or night sweats.'
    )

    contact_by_ds = forms.ChoiceField(
        choices=YES_NO_SELECT_OPTIONS,
        label='Would you like to be contacted by the office of Disability Services? '
    )

    def __init__(self, student, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field_name, field in self.fields.items():
            self.fields[field_name].initial = student.meta.get(field_name)

    def clean(self):
        self.cleaned_data = super().clean()
        
        return self.cleaned_data

    def save(self, student):
        cleaned_data = self.cleaned_data

        if not student.meta:
            student.meta = {}

        for k, v in cleaned_data.items():
            student.meta[k] = v

        student.save()

        return student

class StudentDropRequestForm(forms.Form):
    student = forms.CharField(
        required=True,
        widget=forms.HiddenInput()
    )

    registration = forms.ChoiceField(
        required=True,
        choices=(),
        label='Class Section',
        widget=forms.Select()
    )

    note = forms.CharField(
        required=True,
        widget=forms.Textarea(),
        label='Please explain why you want to drop or withdraw from the course'
    )

    def __init__(self, applied_sections, *args, **kwargs):
        super().__init__(*args, **kwargs)

        sections = [('','Select')]
        for registration in applied_sections:
            sections.append(
                (
                    registration.id,
                    f"{registration.class_section.term}: {registration.class_section.course} / {registration.class_section.class_number} @ {registration.class_section.campus} - {registration.status.title()}"
                )
            )

        self.fields['registration'] = forms.ChoiceField(
            choices=sections,
            label='Class Section',
            widget=forms.Select(),
            required=True
        )

    def clean(self):
        cleaned_data = super().clean()

        if StudentDropRequest.exists(
            cleaned_data['student'],
            cleaned_data['registration']
        ):
            raise ValidationError('Looks like a request has been submitted for the selected class section. Please select a different class section.')

        return cleaned_data

    def save(self):
        cleaned_data = self.cleaned_data
        drop_request = StudentDropRequest.add_new(
            cleaned_data['student'],
            cleaned_data['registration'],
            cleaned_data['note']
        )
        return drop_request

class StudentAgreementForm(forms.Form):
    
    agreement_terms = FFields.LongLabelField(
        required=False,
        label='',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'border-0 bg-light h-100'
            }
        )
    )

    student = forms.CharField(
        required=True,
        widget=forms.HiddenInput()
    )

    term_id = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )

    student_signature = forms.CharField(
        label='Signature of Student',
        required=True,
        error_messages={
            'required':'Please sign in the box'
        },
        help_text='Please type your name in the box'
    )

    def clean(self):
        cleaned_data = super().clean()

        if not cleaned_data.get('student_signature', None):
            raise ValidationError(_('Student Signature is required. Please sign in the box below.'), code='invalid')

        return cleaned_data

    def save(self):
        cleaned_data = self.cleaned_data
        
        student = Student.objects.get(pk=cleaned_data['student'])
        terms = registration_terms()

        from student_onboarding.signals import onboarding_event
        from student_onboarding import events as onboarding_events

        for term in terms:
            try:
                student_agreeement = StudentAgreement()
                student_agreeement.student = student
                student_agreeement.term = term #Term.objects.get(pk=cleaned_data['term'])

                student_agreeement.student_signature = cleaned_data['student_signature']
                student_agreeement.student_signed_on = datetime.datetime.now()

                student_agreeement.save()
            except:
                pass

        onboarding_event.send(
            sender=__name__,
            event=onboarding_events.STUDENT_AGREEMENT_SIGNED,
            student=student,
        )
        return student_agreeement

class ParentConsentVerificationForm(forms.Form):

    student = forms.CharField(
        required=True,
        widget=forms.HiddenInput()
    )

    term = forms.CharField(
        required=True,
        widget=forms.HiddenInput()
    )

    student_dob = forms.CharField(
        required=True,
        label='Students\' Date of Birth',
        
        widget=forms.TextInput(
            attrs={'placeholder':'mm/dd/yyyy', 'class': 'col-md-4'}
        )
    )

    student_zip = forms.CharField(
        required=True,
        label='Students\' Mailing Zipcode',
        widget=forms.TextInput(
            attrs={'placeholder':'12345', 'class': 'col-md-3'}
        )
    )

class ParentConsentRequestForm(forms.Form):

    student = forms.CharField(
        required=True,
        widget=forms.HiddenInput()
    )

    parent_first_name = forms.CharField(
        required=True,
        label='Parent/Guardian First Name',
        widget=forms.TextInput()
    )

    parent_last_name = forms.CharField(
        required=True,
        label='Parent/Guardian Last Name',
        widget=forms.TextInput()
    )

    parent_email = forms.EmailField(
        required=True,
        label='Parent/Guardian Email',
        widget=forms.EmailInput()
    )

    term = forms.CharField(
        required=True,
        widget=forms.HiddenInput()
    )

    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput(),
        initial='request_parent_consent'
    )

    def __init__(self, student, term_id, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['parent_first_name'].initial = student.parent_first_name
        self.fields['parent_last_name'].initial = student.parent_last_name
        self.fields['parent_email'].initial = student.parent_email
        self.fields['student'].initial = student.id
        self.fields['term'].initial = term_id

    def save(self, student):
        data = self.cleaned_data

        student.parent_first_name = data.get('parent_first_name')
        student.parent_last_name = data.get('parent_last_name')
        student.parent_email = data.get('parent_email')

        student.save()

        from cis.models.student import ParentConsent
        ParentConsent.send_notification(
            student=student,
            term_id=data.get('term'),
            parent_name=data['parent_first_name'] + ' ' + data['parent_last_name'],
            parent_email=data['parent_email']
        )

        student.add_note(None, 'Parent consent request email sent by student.')
        return student
    
    def clean_parent_email(self):
        student_id = self.data.get('student')
        try:
            student = Student.objects.get(pk=student_id)
        except Exception as e:
            raise ValidationError('There was an error with the student id passed. Please try again or contact our office.')
        
        if student.user.email.lower() == self.data.get('parent_email', '').lower():
            raise ValidationError('The parent email and student email cannot be the same. Please try again')
    
        return self.data.get('parent_email').lower()

class ParentConsentForm(forms.Form):

    consent_terms = FFields.LongLabelField(
        required=False,
        label='',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'border-0 bg-light h-100'
            }
        )
    )

    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='submit_parent_consent'
    )
    
    student = forms.CharField(
        required=True,
        widget=forms.HiddenInput()
    )

    term = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )

    parent_signature = FFields.SignatureField(
        label='Signature of Parent/Guardian',
        required=True,
        widget=FFields.SignatureWidget
    )

    def clean(self):
        cleaned_data = super().clean()
        
        if not cleaned_data.get('parent_signature', None):
            raise ValidationError(_('Parent/Guardian Signature is required. Please sign in the box below.'), code='invalid')

        return cleaned_data

    def save(self):
        cleaned_data = self.cleaned_data
        
        student = Student.objects.get(pk=cleaned_data['student'])
        terms = registration_terms()

        registered_term_ids = StudentRegistration.objects.filter(
            student=student,
            class_section__term__in=terms
        ).values_list('class_section__term__id', flat=True)

        for term in terms:
            if term.id not in registered_term_ids:
                continue

            try:
                parent_consent = ParentConsent()
                parent_consent.student = student
                parent_consent.term = term

                parent_consent.parent_signature = cleaned_data['parent_signature']
                parent_consent.parent_signed_on = datetime.datetime.now()

                parent_consent.save()
            except:
                pass
        return
  
class StudentExportForm(forms.Form):
    start_date = forms.DateField(
        widget=forms.DateInput(
            format='%m/%d/%Y', attrs={
                'class': 'col-md-6',
                'placeholder': 'mm/dd/yyyy'}),
        help_text='',
        label="From")
    
    end_date = forms.DateField(
        widget=forms.DateInput(
            format='%m/%d/%Y', attrs={
                'class': 'col-md-6',
                'placeholder': 'mm/dd/yyyy'}),
        help_text='',
        label="Until")
    
    def clean_end_date(self):
        if self.cleaned_data['end_date'] < self.cleaned_data['start_date']:
            raise ValidationError(_("Choose a valid end date"))
        return self.cleaned_data['end_date']

    def clean(self):
        from datetime import timedelta

        cleaned_data = super().clean()
        if cleaned_data['start_date'] == cleaned_data['end_date']:
            cleaned_data['end_date'] = cleaned_data['end_date'] + timedelta(days=1)

        return cleaned_data

class UserPasswordChangeForm(forms.Form):
    """
    User Password Change Form
    """
    current_password = forms.CharField(
        max_length=128,
        label="Current Password",
        widget=forms.PasswordInput(attrs={'class': 'col-md-6 col-sm-12'})
    )
    password = forms.CharField(
        max_length=128,
        validators=[
            DictionaryValidator(words=['banned_word'], threshold=0.9),
            LengthValidator(min_length=12),
            ComplexityValidator(complexities=dict(
                UPPER=1,
                LOWER=1,
                DIGITS=1
            ))
        ],
        label="New Password",
        widget=forms.PasswordInput(attrs={'class': 'col-md-6 col-sm-12'})
    )
    confirm_password = forms.CharField(
        max_length=128,
        label="Retype New Password",
        widget=forms.PasswordInput(attrs={'class': 'col-md-6 col-sm-12'})
    )

    def __init__(self, user=None, *args, **kwargs):
        self.user = user
        super(UserPasswordChangeForm, self).__init__(*args, **kwargs)

    def clean_current_password(self):
        current_password = self.cleaned_data['current_password']
        if not self.user.check_password(current_password):
            raise ValidationError(_("Your current password does not match. Please try again"))
        return current_password
    
    def clean_confirm_password(self):
        password = self.cleaned_data.get('password','')
        confirm_password = self.cleaned_data['confirm_password']

        if password != confirm_password:
            raise ValidationError(_("The new passwords don't match. Please retry again."))
        return confirm_password


class ManageFAAForm(forms.Form):

    faa = forms.ModelChoiceField(
        queryset=None,
        required=True,
        widget=forms.HiddenInput()
    )

    status = forms.ChoiceField(
        choices=StudentTuitionAssistance.STATUS_OPTIONS
    )

    public_note = forms.CharField(
        widget=forms.Textarea,
        required=False,
        label='Public Note',
        help_text='This will be sent to the student and parent.'
    )

    amount = forms.CharField(
        required=False,
        initial=0.0,
        label='Amount or Percentage',
        help_text='Eg: 100 or 60%. Adding amount or % will add a new TA to the student. If adding percentage it will calculated based off student balance.'
    )

    notify_student = forms.BooleanField(
        label='Notify Student and Parent',
        required=False
    )

    file = forms.FileField(
        required=False,
        label='Most Recent 1040 Federal Income Tax Form',
        help_text=''
    )

    def __init__(self, faa, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['faa'].queryset = StudentTuitionAssistance.objects.filter(
            pk=faa.id
        )
        self.fields['status'].initial = faa.status
        self.fields['faa'].initial = faa.id

        self.fields['public_note'].initial = faa.information.get('public_note')

        if faa:
            files = faa.files

            if files:
                file_label = '<br><h5>Uploaded Files</h5><table class="table table-striped">'
                for file in files:
                    file_label += "<tr><td>"
                    file_label += f"<a href='{file.media.url}'>{file.filename}</a><br>"
                    file_label += "</td>"

                    file_label += f"<td><a href='?delete_taa_file={file.id}'>Delete</a></td>"
                    file_label += "</tr>"
                
                file_label += "</table>"
                self.fields['file'].help_text = mark_safe(file_label)

    def clean_amount(self):
        amount = self.data.get('amount')

        if amount.endswith('%'):
            amount = amount.replace('%', '')

        try:
            amount = float(amount)
        except:
            raise ValidationError('Please enter a valid amount or %')
        
        return self.data.get('amount')
    
    def save(self, request, commit=True):
        data = self.cleaned_data

        record = data.get('faa')
        
        record.status = data.get('status')
        record.updated_on = datetime.date.today()

        if not record.information:
            record.information = {}

        if not record.information.get('updates'):
            record.information['updates'] = []

        if data.get('public_note'):
            record.student.add_note(
                request.user,
                f'Updated tuition assistance - {data.get("public_note")}'
            )
            
        record.information['public_note'] = data.get('public_note', '')
        message = f'Updated by {request.user}'

        amount = data.get('amount')
        if amount.endswith('%'):
            amount = amount.replace('%', '')
            amount = float(amount)
            amount = ( record.student.current_student_balance * amount ) / 100
        else:
            amount = float(amount)

        if amount > 0:
            message += ', adding $' + str(amount)

            scholarship = StudentTransaction(
                student=record.student,
                term=record.term,
                t_type='credit',
                amount=amount,
                label='1',
                description='Tuition Assistance',
                created_by=request.user,
                meta={}
            )
            scholarship.save()

            record.student.add_note(
                request.user,
                f'Added tuition assistance of {scholarship.amount}'
            )

        if data.get('notify_student'):
            record.send_email()

            record.student.add_note(
                request.user,
                f'Sent notification to student and parent'
            )

        record.information['updates'].append(message)
        record.save()

        return record
    
    
class StudentTuitionAssistanceForm(forms.Form):

    student = forms.ModelChoiceField(
        queryset=None,
        required=True,
        widget=forms.HiddenInput()
    )
    
    term = forms.ModelChoiceField(
        queryset=None,
        required=True,
        widget=forms.HiddenInput()
    )

    other_info = forms.CharField(
        widget=forms.Textarea,
        label=mark_safe('Financial Hardship Statement'),
        help_text='',
        required=True
    )

    personal_statement = forms.FileField(
        required=False,
        label='500-word Essay Written by the Student',
        help_text=""
    )

    file = forms.FileField(
        required=False,
        label='Most Recent 1040 Federal Income Tax Form',
        help_text=mark_safe('You may obtain your most recent Tax Return Transcript by visiting <a href=\'http://www.irs.gov/\' target="_blank">http://www.irs.gov/</a> or calling the IRS automated phone transcript service at 800-908-9946.')
    )

    def __init__(self, student, term, faa=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['student'].queryset = Student.objects.filter(
            pk=student.id
        )
        self.fields['term'].queryset = Term.objects.filter(
            pk=term.id
        )

        self.fields['student'].initial = student
        self.fields['term'].initial = term

        if faa:
            self.fields['other_info'].initial = faa.other_info
            files = faa.files

            if files:
                file_label = '<br><h5>Uploaded Files</h5><table class="table table-striped">'
                for file in files:
                    file_label += "<tr><td>"
                    file_label += f"<a href='{file.media.url}'>{file.filename}</a><br>"
                    file_label += "</td>"
                    file_label += "<td>"
                    file_label += f"{file.description}"
                    file_label += "</td>"

                    file_label += f"<td><a href='?delete_taa_file={file.id}'>Delete</a></td>"
                    file_label += "</tr>"
                
                file_label += "</table>"
                self.fields['file'].help_text = mark_safe(file_label)

    def save(self, commit=True):
        data = self.cleaned_data

        if not StudentTuitionAssistance.objects.filter(
            student=data.get('student'),
            term=data.get('term')
        ).exists():
            record = StudentTuitionAssistance(
                student=data.get('student'),
                term=data.get('term'),
                status='Not Yet Submitted'
            )
        else:
            record = StudentTuitionAssistance.objects.filter(
                student=data.get('student'),
                term=data.get('term')
            )

            record = record[0]
        
        if not record.information:
            record.information = {}

        record.information['other_info'] = data.get('other_info')

        if commit:
            record.save()

        return record



class StudentForm(forms.Form):
    ...

class StudentProfileForm(forms.Form):
    ...

# class StudentForm(forms.Form):
#     """
#     Student Form
#     """
#     first_name = forms.CharField(
#         label='Student Legal First Name',
#         max_length=128,
#         widget=forms.TextInput(attrs={'class': 'col-md-6 col-sm-12'}))

#     last_name = forms.CharField(
#         label='Student Legal Last Name',
#         max_length=128,
#         widget=forms.TextInput(attrs={'class': 'col-md-8 col-sm-12'}))

#     middle_name = forms.CharField(
#         label='Middle Name or Initial',
#         max_length=128,
#         required=False,
#         widget=forms.TextInput(attrs={'class': 'col-md-4 col-sm-12'}))

#     suffix = forms.ChoiceField(
#         label='Suffix (if applicable)',
#         choices=[
#             ('', 'Select'),
#             ('Sr', 'Sr'),
#             ('Jr', 'Jr'),
#             ('I', 'I'),
#             ('II', 'II'),
#             ('III', 'III'),
#             ('IV', 'IV')
#         ],
#         required=False,
#         widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'})
#     )

#     preferred_name = forms.CharField(
#         label='Preferred Name (if different from above)',
#         required=False,
#         max_length=128,
#         widget=forms.HiddenInput()
#         # widget=forms.TextInput(attrs={'class': 'col-md-8 col-sm-12'})
#     )

#     email = forms.EmailField(
#         label='Student Personal Email',
#         help_text='',
#         widget=forms.TextInput(attrs={'class': 'col-md-7 col-sm-6'}))

#     password = forms.CharField(
#         max_length=128,
#         label="Password",
#         validators=[
#             DictionaryValidator(words=['banned_word'], threshold=0.9),
#             LengthValidator(min_length=12),
#             ComplexityValidator(complexities=dict(
#                 UPPER=1,
#                 LOWER=1,
#                 DIGITS=1
#             ))
#         ],
#         help_text='Please choose a strong password, with min. 12 characters, at least 1 digit, 1 special character and 1 uppercase letter',
#         widget=forms.PasswordInput(attrs={'class': 'col-md-5 col-sm-12', 'autocomplete': 'off'})
#     )

#     confirm_password = forms.CharField(
#         max_length=128,
#         label="Retype Password",
#         widget=forms.PasswordInput(attrs={'class': 'col-md-5 col-sm-12', 'autocomplete': 'off'})
#     )
    
#     highschool = forms.ModelChoiceField(
#         queryset=None,
#         label='High School',
#         required=True,
#         help_text=mark_safe(''),
#         widget=forms.Select(attrs={'class': 'col-12'}))

#     cte = forms.ModelChoiceField(
#         queryset=None,
#         label='If you also attend a CTE Program, please select',
#         required=False,
#         help_text='',
#         widget=forms.Select(attrs={'class': 'col-12'}))

#     new_highschool_name = forms.CharField(
#         label='High School Name',
#         required=False,
#         max_length=100,
#         help_text='Some helper text'
#     )

#     new_highschool_counselor_name = forms.CharField(
#         label='High School Counselor Name',
#         required=False,
#         max_length=100
#     )
    
#     new_highschool_counselor_email = forms.EmailField(
#         label='High School Counselor Email',
#         help_text='We will send them an email - some other text',
#         required=False,
#         max_length=100
#     )

#     current_grade_level = forms.ChoiceField(
#         choices=Student.GRADE_LEVEL,
#         required=False,
#         label='Current Grade Level',
#         help_text='',
#         widget=forms.HiddenInput
#     )

#     # graduation_date = forms.DateField(
#     #     label='High School Graduation Date',
#     #     required=False,
#     #     widget=forms.HiddenInput()
#     # )

#     graduation_year = forms.ChoiceField(
#         choices=[],
#         label='Graduation Year'
#     )
    
#     tuition_assistance_header = FFields.ReadOnlyField(
#         required=False,
#         label=mark_safe('<p>Tuition Assistance is available for students who meet the federal guidelines for free and reduced lunch based on household income requirements or other need-based circumstances.</p>'),
#         initial='',
#         widget=FFields.LongLabelWidget(
#             attrs={
#                 'class':'border-0 bg-light h-100'
#             }
#         )
#     )

#     qualify_tuition_assistance = forms.ChoiceField(
#         choices=Student.TRUE_FALSE_CHOICES,
#         required=False,
#         label='Please indicate if you believe that you might be eligible for tuition assistance?',
#         help_text='',
#         widget=forms.Select(attrs={'class': 'col-md-6 col-sm-12'})
#     )

#     date_of_birth = forms.DateField(
#         widget=forms.SelectDateWidget(),
#         # help_text='Enter date as mm/dd/yyyy',
#         label="Date of Birth"
#     )

#     # confirm_email = forms.EmailField(
#     #     label='Confirm Email',
#     #     help_text='',
#     #     widget=forms.TextInput(attrs={'class': 'col-md-7 col-sm-6'}))


#     # date_of_birth = forms.DateField(
#     #     widget=forms.DateInput(
#     #         format='%m/%d/%Y', attrs={
#     #             'class': 'col-md-4',
#     #             'placeholder': 'mm/dd/yyyy'}),
#     #     help_text='Enter date as mm/dd/yyyy',
#     #     label="Date of Birth")

#     us_citizen = forms.ChoiceField(
#         choices=Student.TRUE_FALSE_CHOICES,
#         required=True,
#         label='Are you a US Citizen?',
#         help_text='',
#         widget=forms.Select(attrs={'class': 'col-md-6 col-sm-12'})
#     )

#     sevis_id = forms.CharField(
#         label='SEVIS ID',
#         max_length=15,
#         help_text='',
#         required=False,
#         widget=forms.TextInput(attrs={'class': 'col-md-4 col-sm-12'}))
    
#     ssn = forms.CharField(
#         label='Social Security Number',
#         max_length=15,
#         help_text='',
#         required=True,
#         widget=forms.TextInput(attrs={'class': 'col-md-4 col-sm-12'}))

#     verify_student_ssn = forms.CharField(
#         label='Verify Social Security Number',
#         max_length=15,
#         help_text='',
#         required=True,
#         widget=forms.TextInput(attrs={'class': 'col-md-4 col-sm-12'}))

#     gender = forms.ChoiceField(
#         choices=Student.GENDER_OPTIONS,
#         label='Gender',
#         required=True,
#         help_text='',
#         widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}))
    
#     gender_identity = forms.ChoiceField(
#         choices=Student.GENDER_IDENTITY_OPTIONS,
#         required=False,
#         label='Gender Designation',
#         help_text='',
#         widget=forms.HiddenInput()
#     )
    
#     gender_pronoun = forms.ChoiceField(
#         choices=Student.GENDER_PRONOUN_OPTIONS,
#         required=False,
#         label='Gender Pronoun',
#         help_text='',
#         widget=forms.HiddenInput()
#     )

#     cell_phone = forms.CharField(
#         label='Cell Phone Number',
#         max_length=15,
#         required=True,
#         help_text='(Eg: 5551231234)',
#         widget=forms.TextInput(attrs={'class': 'col-md-5 col-sm-6'}))
    
#     cell_phone_opt_in = forms.CharField(
#         label='By checking box, I opt-in to receive text message notifications. Standard message and data rates apply.',
#         required=False,
#         widget=forms.CheckboxInput
#     )

#     home_phone = forms.CharField(
#         label='Home Phone Number',
#         max_length=15,
#         required=False,
#         help_text='(Eg: 5551231234)',
#         widget=forms.HiddenInput()
#     )

#     mailing_address = forms.CharField(
#         label='Home Address',
#         max_length=128,
#         required=True,
#         help_text='<ul class="us-autocomplete-pro-menu" style="display:none;"></ul>',
#         widget=forms.TextInput(attrs={
#             'class': 'col-md-8 col-sm-12'}))

#     address_2 = forms.CharField(
#         label='Address Line 2',
#         max_length=128,
#         required=False,
#         widget=forms.HiddenInput(attrs={'class': 'col-md-8 col-sm-12'}))

#     city = forms.CharField(
#         label='City',
#         max_length=128,
#         required=True,
#         widget=forms.TextInput(attrs={
#             'class': 'col-md-5 col-sm-6'}))
    
#     county = forms.CharField(
#         label='county',
#         max_length=128,
#         required=False,
#         widget=forms.HiddenInput
#     )

#     state = forms.CharField(
#         required=True,
#         widget=forms.TextInput(attrs={
#             'class': 'col-md-3'
#         })
#     )

#     zip_code = forms.CharField(
#         label='Zip Code',
#         max_length=10,
#         required=True,
#         widget=forms.TextInput(attrs={
#             'class': 'col-md-4 col-sm-6'}))

#     hispanic = forms.ChoiceField(
#         choices=Student.TRUE_FALSE_CHOICES,
#         required=False,
#         label='Are you Hispanic/Latino?',
#         widget=forms.Select(attrs={'class': 'col-md-6 col-sm-12'}))
    
#     ethnicity = forms.MultipleChoiceField(
#         choices=Student.ETHNICITY_OPTIONS,
#         required=False,
#         label='Please indicate your race (select one or more):',
#         widget=forms.CheckboxSelectMultiple(attrs={'class': 'col-md-6 col-sm-12'}))

#     parent_name = forms.CharField(
#         required=True,
#         label='Parent/Guardian 1 Name',
#         widget=forms.TextInput()
#     )

#     parent_email = forms.EmailField(
#         required=True,
#         label='Parent/Guardian 1 Email',
#         widget=forms.EmailInput()
#     )

#     parent_phone = forms.CharField(
#         required=True,
#         label='Parent/Guardian 1 Cell Phone'
#     )

#     parent2_name = forms.CharField(
#         required=False,
#         label='Parent/Guardian 2 Name',
#         widget=forms.TextInput()
#     )

#     parent2_email = forms.EmailField(
#         required=False,
#         label='Parent/Guardian 2 Email',
#         widget=forms.EmailInput()
#     )

#     parent2_phone = forms.CharField(
#         required=False,
#         label='Parent/Guardian 2 Cell Phone'
#     )

#     parent1_education_level = forms.ChoiceField(
#         choices=Student.PARENT_EDUCATION_OPTIONS,
#         required=True,
#         label='Parent/Guardian 1 Highest Level of Education'
#     )

#     parent2_education_level = forms.ChoiceField(
#         choices=Student.PARENT_EDUCATION_OPTIONS,
#         required=False,
#         label='Parent/Guardian 2 Highest Level of Education'
#     )
    
#     parent1_interest = forms.ChoiceField(
#         choices=Student.PARENT_INTEREST_OPTIONS,
#         required=False,
#         label='Parent/Guardian 1 Interest in Seton Hill\'s Online Bachelor\'s, Certificate, or Graduate Programs?'
#     )

#     parent2_interest = forms.ChoiceField(
#         choices=Student.PARENT_INTEREST_OPTIONS,
#         required=False,
#         label='Parent/Guardian 2 Interest in Seton Hill\'s Online Bachelor\'s, Certificate, or Graduate Programs?'
#     )

#     confirm_term_language = FFields.LongLabelField(
#         label='',
#         widget=forms.HiddenInput(),
#         required=False
#     )

#     confirm_term = forms.CharField(
#         label='',
#         required=False,
#         widget=forms.HiddenInput()
#     )

#     signature = forms.CharField(
#         required=False,
#         label='Signature',
#         help_text='Please type your name',
#         widget=forms.HiddenInput()
#     )

#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)
        
#         YEARS = []
        
#         this_year = datetime.date.today().year
#         if datetime.datetime.now().month >= 6:
#             this_year += 1
#         graduation_years = [('', 'Select')] + [(grad_year, grad_year) for grad_year in range(this_year, this_year + 4)]
#         self.fields['graduation_year'].choices = graduation_years

#         from cis.settings.registrations import registrations as regis_settings
#         reg_settings = regis_settings.from_db()

#         # self.fields['highschool_start_date'].widget = FFields.GraduationMonthYearWidget(
#         #     years=range(datetime.datetime.now().year - 5, datetime.datetime.now().year)
#         # )
#         # start_year = datetime.datetime.now().year
#         # if datetime.datetime.now().month >= 6:
#         #     start_year += 1

#         # self.fields['graduation_date'].widget = FFields.GraduationMonthYearWidget(
#         #     years=range(start_year, start_year+4)
#         # )

#         self.fields['highschool'].queryset = HighSchool.objects.filter(status__iexact='Active').exclude(name__icontains='career')

#         self.fields['cte'].queryset = HighSchool.objects.filter(
#             name__icontains='career'
#         ).order_by('name')
        
#         try:
#             dob_start = datetime.datetime.strptime(
#                 reg_settings.get('starting_birth_date'),
#                 '%m/%d/%Y'
#             )

#             dob_end = datetime.datetime.strptime(
#                 reg_settings.get('ending_birth_date'),
#                 '%m/%d/%Y'
#             )

#             if dob_start.year < dob_end.year:
#                 dob_start_year = dob_start.year
#                 dob_end_year = dob_end.year

#                 while dob_start_year <= dob_end_year:
#                     YEARS.append(
#                         dob_start_year
#                     )
#                     dob_start_year += 1

#             self.fields['date_of_birth'].widget = forms.SelectDateWidget(
#                 years=YEARS
#             )

#             # residency_years = range(dob_start.year, datetime.datetime.now().year+1)
#             # self.fields['residency_date'].widget = forms.SelectDateWidget(
#             #     years=residency_years
#             # )
#         except Exception as e:
#             print(e)

#         form_settings = signup_settings.from_db()
#         form_labels = json.loads(form_settings.get('form_field_messages', '{}'))

#         for field_name in self.fields:
#             field = self.fields[field_name]

#             if form_labels.get(field_name):
#                 field_attr = form_labels.get(field_name, {})

#                 field.label = mark_safe(field_attr.get('label', ''))
#                 field.help_text = mark_safe(field_attr.get('help_text', ''))

#         # self.fields['confirm_term'].label = Student.get_student_signup_terms()

#         if kwargs.get('data'):
#             data = kwargs.get('data')

#             if data.get('highschool_not_listed'):
#                 help_text = self.fields['highschool'].help_text
#                 help_text = help_text.replace(
#                     '<input type="checkbox" name="highschool_not_listed" value="highschool_not_listed" id="id_highschool_not_listed">',
#                     '<input type="checkbox" name="highschool_not_listed" checked value="highschool_not_listed" id="id_highschool_not_listed">'
#                 )
#                 self.fields['highschool'].help_text = help_text

#                 self.fields['new_highschool_name'].widget = forms.TextInput()
#                 self.fields['new_highschool_name'].required = True

#                 self.fields['new_highschool_counselor_name'].widget = forms.TextInput()
#                 self.fields['new_highschool_counselor_name'].required = True

#                 self.fields['new_highschool_counselor_email'].widget = forms.TextInput()
#                 self.fields['new_highschool_counselor_email'].required=True


#     def clean(self):
#         cleaned_data = super().clean()

#         first_name = cleaned_data.get('first_name')
#         last_name = cleaned_data.get('last_name')
#         dob = cleaned_data.get('date_of_birth')
#         highschool = cleaned_data.get('highschool')

#         if not cleaned_data.get('new_highschool_name') and not cleaned_data.get('highschool'):
#             raise ValidationError('Please choose your high school from the drop-down list or select \'Not in the list\'')

#         try:
#             if not self.student:
#                 pass

#             if cleaned_data.get('ssn'):
#                 if Student.objects.filter(user__ssn=cleaned_data.get('ssn')).exclude(id=self.student.id).exists():
#                     self.add_error(
#                         'ssn', 'This SSN is already associated with another account. Please verify or call our office for further assistance.')
#         except Exception as e:
#             if Student.objects.filter(
#                     user__first_name__iexact=first_name,
#                     user__last_name__iexact=last_name,
#                     user__date_of_birth=dob,
#                     highschool=highschool
#                 ).exists():
#                     self.add_error('first_name', 'There is already an account for a student with the same name and high school. You must use your original email address. Please use the password reset to recover your account.')
                    
#                     self.add_error('last_name', 'There is already an account for a student with the same name and high school. You must use your original email address. Please use the password reset to recover your account.')

#                     self.add_error('highschool', 'There is already an account for a student with the same name and high school. You must use your original email address. Please use the password reset to recover your account.')

#                     self.add_error('date_of_birth', 'There is already an account for a student with the same name and high school. You must use your original email address. Please use the password reset to recover your account.')           

#         # print(self.cleaned_data)
#         address = self.cleaned_data.get('mailing_address')
#         city = self.cleaned_data.get('city')
#         state = self.cleaned_data.get('state')
#         zipcode = self.cleaned_data.get('zip_code')

#         if address:
#             (is_valid, message, mailing_address, city, state, zipcode, plus4, county) = is_valid_address(
#                 address,
#                 city,
#                 state,
#                 zipcode,
#                 self.cleaned_data.get('address_2')
#             )

#             if not is_valid:
#                 self.add_error(None, f'{message}. The address you entered is not valid.')
#                 self.add_error('mailing_address', 'Enter a valid address, city, zip code')
#             else:
#                 cleaned_data['mailing_address'] = mailing_address
#                 cleaned_data['city'] = city
#                 cleaned_data['state'] = state
#                 cleaned_data['zip_code'] = zipcode
#                 cleaned_data['county'] = county
#                 cleaned_data['plus4'] = plus4

#         return cleaned_data

#     def clean_other_college_credits(self):
#         data = self.data.get('other_college_credits')

#         college_attended_1 = self.data.get('college_attended_1_0')
#         college_attended_2 = self.data.get('college_attended_2_0')
#         college_attended_3 = self.data.get('college_attended_3_0')

#         if data == '1':
#             if not any([college_attended_1, college_attended_2, college_attended_3]):
#                 raise ValidationError('Please enter the name of the college(s) attended1')
#             return data
#         return data
    
#     # def clean_graduation_date(self):
#     #     import datetime

#     #     data = self.cleaned_data.get('graduation_date')
#     #     # highschool_start_date = self.cleaned_data.get('highschool_start_date')

#     #     if not data:
#     #         raise ValidationError(_("Please enter a graduation date"), code='invalid')
        
#     #     if data < datetime.date.today():
#     #         if not self.fields['graduation_date'].required:
#     #             return None
            
#     #         raise ValidationError(_("Please enter a graduation date in the future"), code='invalid')
        
#     #     # if data < highschool_start_date:
#     #     #     if not self.fields['graduation_date'].required:
#     #     #         return None
            
#     #     #     raise ValidationError(_("Please check the graduation date entered"), code='invalid')
#     #     return data

#     def clean_residency_date(self):
#         data = self.cleaned_data.get('residency_date')
#         dob = self.cleaned_data.get('date_of_birth')

#         if data and dob and data < dob:
#             raise ValidationError("The residency date cannot be prior to your date of birth. Please correct it and try again.")
        
#         return data

#     def clean_email(self):
#         """
#         Email should not exist in the system. Checks for duplicate in
#         column 'email' or 'alt_email' of CustomUser
#         """
#         data = self.cleaned_data['email'].lower()
        
#         if CustomUser.objects.filter(
#                 Q(email=data) |
#                 Q(username=data) |
#                 Q(secondary_email=data)
#         ).exists():
#             raise ValidationError(_("This email is already registered in the system. Please login or choose a different email address"), code='invalid')
#         return data

#     def clean_confirm_email(self):
#         email = self.cleaned_data.get('email', '').lower()
#         confirm_email = self.cleaned_data.get('confirm_email').lower()

#         if email != confirm_email:
#             raise ValidationError(_("The email address does not match. Please re-type the email address."))
#         return confirm_email

#     def clean_date_of_birth(self):
#         dob = self.cleaned_data['date_of_birth']
#         if not Student.is_valid_age_range(dob):
#             raise ValidationError(_("The date of birth entered falls outside the current allowable range. Please enter a valid date of birth"))
#         return dob

#     def clean_confirm_password(self):
#         password = self.cleaned_data.get('password','')
#         confirm_password = self.cleaned_data['confirm_password']

#         if password != confirm_password:
#             raise ValidationError(_("The passwords don't match. Please retry again."))
#         return confirm_password

#     def clean_cell_phone(self):
#         from phonenumber_field.phonenumber import PhoneNumber


#         data = self.cleaned_data['cell_phone']
#         home_phone = self.data['home_phone']
#         if not data and not home_phone:
#             if not self.fields['cell_phone'].required:
#                 return None
            
#             raise ValidationError('Please enter a cell phone or home phome number')

#         try:
#             number = PhoneNumber.from_string(data)
#             if not number.is_valid():
#                 raise ValidationError('Enter a valid phone number (e.g. (506) 234-5678) or a number with an international call prefix.')
#             return number.as_international
#         except:
#             raise ValidationError('Enter a valid phone number (e.g. (506) 234-5678) or a number with an international call prefix.')
    
#     def clean_parent_phone(self):
#         from phonenumber_field.phonenumber import PhoneNumber

#         data = self.cleaned_data['parent_phone']
#         # home_phone = self.data['home_phone']
#         if not data:
#             if not self.fields['parent_phone'].required:
#                 return None
            
#             raise ValidationError('Please enter a parent/guardian cell phone number')

#         try:
#             number = PhoneNumber.from_string(data)
#             if not number.is_valid():
#                 raise ValidationError('Enter a valid phone number (e.g. (506) 234-5678) or a number with an international call prefix.')
#             return number.as_international
#         except:
#             raise ValidationError('Enter a valid phone number (e.g. (506) 234-5678) or a number with an international call prefix.')
            
#     def clean_first_name(self):
#         data = self.cleaned_data['first_name']
#         return data.title()
    
#     def clean_last_name(self):
#         data = self.cleaned_data['last_name']
#         return data.title()
    
#     def clean_highschool(self):
#         highschool_not_listed = self.data.get('highschool_not_listed')

#         if highschool_not_listed:
#             new_highschool_name = self.data.get('new_highschool_name')
#             new_highschool_counselor_name = self.data.get('new_highschool_counselor_name')
#             new_highschool_counselor_email = self.data.get('new_highschool_counselor_email')

#             if not new_highschool_name or not new_highschool_counselor_name or not new_highschool_counselor_email:
#                 raise ValidationError('Please enter new high school name and counselor information')
#                 return self.data.get('highschool')

#         data = self.cleaned_data.get('highschool')
#         return data

#     def clean_parent_email(self):
#         data = self.cleaned_data['parent_email']

#         if not data:
#             return data

#         if data.lower() == self.cleaned_data.get('email', '').lower():
#             raise ValidationError(_("The student and parent email cannot be the same. Please correct that and try again."))
#         return data
    
#     def clean_verify_student_ssn(self):
#         ssn = self.cleaned_data.get('ssn')
#         verify_student_ssn = self.cleaned_data.get('verify_student_ssn')

#         if ssn and ssn != verify_student_ssn:
#             raise ValidationError(
#                 _(
#                     'Please verify that you have entered matching SSN'
#                 ), code='invalid'
#             )
#         return verify_student_ssn

#     def clean_ssn(self):
#         ssn = self.cleaned_data.get('ssn')
#         no_ssn = self.data.get('no_ssn')

#         if not ssn and not self.fields['ssn'].required:
#             return None
        
#         if self.cleaned_data.get('us_citizen') in [True, 'True']:
#             if not ssn:
#                 raise ValidationError('Please enter your SSN', code='invalid')
                        
#         if ssn:
#             from cis.validators import validate_ssn
#             validate_ssn(self.cleaned_data['ssn'])
#         return ssn

#     def clean_parent_email(self):
#         data = self.cleaned_data['parent_email']

#         if data.lower() == self.cleaned_data.get('email', '').lower():
#             raise ValidationError(_("The student and parent email cannot be the same. Please correct that and try again."))
#         return data
    
#     def clean_phone(self):

#         import re
#         phone_num = (re.findall(r'\d+', self.cleaned_data['phone']))
#         phone_num = ''.join(phone_num)

#         if len(phone_num) != 10:
#             raise ValidationError(_("Enter a 10 digit phone number. Eg: 5551231234"))
#         return phone_num

# class StudentProfileForm(StudentForm, forms.Form):

#     psid = forms.CharField(
#         label='Student ID',
#         max_length=128,
#         required=True,
#         widget=forms.TextInput(attrs={'class': 'col-md-4 col-sm-12'}))
    
#     alt_username = forms.CharField(
#         label='Student Banner User Name',
#         max_length=128,
#         required=False,
#         widget=forms.TextInput(attrs={'class': 'col-md-4 col-sm-12'}))
    
#     secondary_email = forms.CharField(
#         label='Student College Email',
#         max_length=128,
#         required=False,
#         widget=forms.TextInput(attrs={'class': 'col-md-4 col-sm-12'}))

#     id = forms.CharField(
#         widget=forms.HiddenInput
#     )
    
#     class Media:
#         js = [
#             'js/student_application.js',
#             'js/address_auto_complete.js',
#         ]

#         css = {
#             "all": ["css/address_auto_complete.css"],
#         }
    
#     EDITABLE_FIELDS_AFTER_SIS = [
#         'mailing_address', 'city', 'state', 'zip_code',
#         'cell_phone', 'home_phone', 'highschool', 'cte',
#         'parent_email', 'parent_phone', 'parent2_email', 'parent2_phone',
#         'attended_college', 'complete_college', 'email', 'cell_phone_opt_in',
#         'qualify_tuition_assistance', 'parent1_education_level',
#         'parent2_education_level', 'parent1_interest', 'parent2_interest',
#         'confirm_term', 'signature', 'sevis_id'
#     ]

#     def __init__(self, student=None, request=None, *args, **kwargs):
#         super().__init__(*args, **kwargs)
        
#         self.student = student
#         self.request = request
#         self.is_cis_user = request and user_has_cis_role(request.user)
        
#         self._handle_us_citizen_requirements()
#         self._configure_fields_by_role()
        
#         if student is not None:
#             self._populate_initial_values(student)
#             self._configure_field_permissions(student)
    

#     def _handle_us_citizen_requirements(self):
#         """Handle SSN field requirements based on citizenship status"""
#         if self.data.get('us_citizen') in [False, 'False', '']:
#             self.fields['ssn'].required = False
#             self.fields['verify_student_ssn'].required = False
    
#     def _configure_fields_by_role(self):
#         """Show/hide fields based on user role"""
#         if self.is_cis_user:
#             if 'verify_student_ssn' in self.fields:
#                 del self.fields['verify_student_ssn']
#             self._make_all_fields_optional()
#         else:
#             self._remove_admin_fields()
    
#     def _make_all_fields_optional(self):
#         """Make all fields optional for CIS users"""
#         for field_name in self.fields:
#             self.fields[field_name].required = False
    
#     def _remove_admin_fields(self):
#         """Remove admin-only fields for non-CIS users"""
#         admin_fields = ['psid', 'alt_username', 'secondary_email']
#         for field in admin_fields:
#             if field in self.fields:
#                 del self.fields[field]
    
#     def _populate_initial_values(self, student):
#         """Populate all field initial values from student object"""
#         self.fields['id'].initial = student.id
        
#         # User fields
#         self._populate_user_fields(student.user)
        
#         # Student fields
#         self._populate_student_fields(student)
        
#         # Parent fields
#         self._populate_parent_fields(student)
        
#         # Notifications
#         self._populate_notifications(student)
        
#         # Admin fields (if applicable)
#         if self.is_cis_user:
#             self._populate_admin_fields(student.user)
        
#         # Handle date of birth year edge case
#         self._ensure_dob_year_in_widget(student.user.date_of_birth)
    
#     def _populate_user_fields(self, user):
#         """Populate fields from user object"""
#         field_mappings = {
#             'first_name': user.first_name,
#             'last_name': user.last_name,
#             'middle_name': user.middle_name,
#             'suffix': user.suffix,
#             'email': user.email,
#             'date_of_birth': user.date_of_birth,
#             'mailing_address': user.address1,
#             'city': user.city,
#             'state': user.state,
#             'zip_code': user.postal_code,
#             'cell_phone': user.primary_phone,
#             'home_phone': user.secondary_phone,
#             'ssn': user.ssn,
#         }
        
#         for field, value in field_mappings.items():
#             if field in self.fields:
#                 self.fields[field].initial = value
    
#     def _populate_student_fields(self, student):
#         """Populate fields from student object"""
#         field_mappings = {
#             'preferred_name': student.preferred_name,
#             'gender': student.gender,
#             'gender_identity': student.gender_identity,
#             'gender_pronoun': student.gender_pronoun,
#             'hispanic': student.hispanic,
#             'ethnicity': student.ethnicity,
#             'sevis_id': student.sevis_id,
#             'qualify_tuition_assistance': student.qualify_tuition_assistance,
#             'highschool': student.highschool,
#             'cte': student.cte if student.cte else None,
#             'graduation_year': student.graduation_year,
#             'us_citizen': student.us_citizen,
#             'parent1_education_level': student.parent1_education_level,
#             'parent2_education_level': student.parent2_education_level,
#         }
        
#         for field, value in field_mappings.items():
#             if field in self.fields and value is not None:
#                 self.fields[field].initial = value
        
#         # Handle meta fields
#         if student.meta:
#             self.fields['parent1_interest'].initial = student.meta.get('parent1_interest')
#             self.fields['parent2_interest'].initial = student.meta.get('parent2_interest')
    
#     def _populate_parent_fields(self, student):
#         """Populate parent/guardian fields"""
#         field_mappings = {
#             'parent_name': student.parent_name,
#             'parent_email': student.parent_email,
#             'parent_phone': student.parent_phone,
#             'parent2_name': student.parent2_name,
#             'parent2_email': student.parent2_email,
#             'parent2_phone': student.parent2_phone,
#         }
        
#         for field, value in field_mappings.items():
#             if field in self.fields:
#                 self.fields[field].initial = value
    
#     def _populate_notifications(self, student):
#         """Populate notification preferences"""
#         notifications = student.notifications or {}
#         cell_opt_in = notifications.get('cell_phone_opt_in', 'False') == 'True'
#         self.fields['cell_phone_opt_in'].initial = cell_opt_in
    
#     def _populate_admin_fields(self, user):
#         """Populate admin-only fields for CIS users"""
#         if 'psid' in self.fields:
#             self.fields['psid'].initial = user.psid
#         if 'alt_username' in self.fields:
#             self.fields['alt_username'].initial = user.alt_username
#         if 'secondary_email' in self.fields:
#             self.fields['secondary_email'].initial = user.secondary_email
    
#     def _ensure_dob_year_in_widget(self, dob):
#         """Add DOB year to widget if not present"""
#         if dob and dob.year not in self.fields['date_of_birth'].widget.years:
#             self.fields['date_of_birth'].widget.years.append(dob.year)
    
#     def _configure_field_permissions(self, student):
#         """Configure which fields are disabled/editable"""
#         # Handle special case: student not yet in SIS
#         if student.user.psid == '-':
#             self._handle_pre_sis_student()
#             return
        
#         # Always disable email except for special cases
#         self.fields['email'].disabled = True
        
#         if self.is_cis_user:
#             self._handle_cis_user_permissions()
#         else:
#             self._handle_regular_user_permissions(student)
    
#     def _handle_pre_sis_student(self):
#         """Handle students not yet sent to SIS"""
#         if not self.is_cis_user:
#             fields_to_remove = ['ssn', 'verify_student_ssn']
#             for field in fields_to_remove:
#                 if field in self.fields:
#                     del self.fields[field]
        
#         # Remove password and confirmation fields
#         for field in ['password', 'confirm_password', 'confirm_term']:
#             if field in self.fields:
#                 del self.fields[field]
    
#     def _handle_cis_user_permissions(self):
#         """Configure permissions for CIS users"""
#         self.fields['email'].disabled = False
        
#         # Remove password fields for admin users
#         for field in ['password', 'confirm_password']:
#             if field in self.fields:
#                 del self.fields[field]
    
#     def _handle_regular_user_permissions(self, student):
#         """Configure permissions for regular users"""
#         # If student has been sent to SIS, limit editable fields
#         if self._is_sent_to_sis(student):
#             self.fields['email'].disabled = False
#             self._disable_non_editable_fields()
            
#             try:
#                 del self.fields['password']
#                 del self.fields['confirm_password']
                
#                 del self.fields['ssn']
#                 del self.fields['verify_student_ssn']

#             except KeyError:
#                 pass

#     def _is_sent_to_sis(self, student):
#         """Check if student has been sent to SIS"""
#         return (student.user.psid and len(student.user.psid) >= 5) or student.sis_sent_on
    
#     def _disable_non_editable_fields(self):
#         """Disable all fields except those in the editable list"""
#         for field_name in self.fields:
#             if field_name not in self.EDITABLE_FIELDS_AFTER_SIS:
#                 self.fields[field_name].disabled = True

#     def clean_date_of_birth(self):
#         return self.cleaned_data['date_of_birth']

#     def clean_email(self):
#         """
#         Email should not exist in the system. Checks for duplicate in
#         column 'email' or 'alt_email' of CustomUser
#         """
#         data = self.cleaned_data['email'].lower()
        
#         if CustomUser.objects.filter(
#                 Q(email=data) |
#                 Q(username=data) |
#                 Q(secondary_email=data)
#             ).exclude(pk=self.student.user.id).exists():
#             raise ValidationError(_("This email is already registered in the system. Please login or choose a different email"), code='invalid')

#         return data
        
#     def save(self, student):
#         """Save form data to student and user objects"""
#         data = self.cleaned_data
        
#         self._save_user_data(student.user, data)
#         self._save_student_data(student, data)
#         self._handle_new_highschool(student, data)
#         self._save_notifications(student, data)
#         self._save_parent_data(student, data)
#         self._finalize_student_record(student, data)
        
#         student.save()
#         return student

#     def _save_user_data(self, user, data):
#         """Update user model fields"""
#         # Name fields
#         if data.get('first_name'):
#             user.first_name = data['first_name']
#         if data.get('last_name'):
#             user.last_name = data['last_name']
#         if data.get('middle_name'):
#             user.middle_name = data['middle_name']
#         if data.get('suffix'):
#             user.suffix = data['suffix']
        
#         # Email and auth fields
#         user.email = data['email']
#         if data.get('alt_username'):
#             user.alt_username = data['alt_username']
#         if data.get('secondary_email'):
#             user.secondary_email = data['secondary_email']
#         if data.get('psid'):
#             user.psid = self.data.get('psid')
#         if data.get('password'):
#             user.set_password(data['password'])
        
#         # Identification
#         if data.get('ssn'):
#             user.ssn = data['ssn']
#         if data.get('date_of_birth'):
#             user.date_of_birth = data['date_of_birth']
#         if data.get('country_of_birth'):
#             user.country_of_birth = data['country_of_birth']
        
#         # Contact info
#         if data.get('cell_phone'):
#             user.primary_phone = data['cell_phone']
#         user.secondary_phone = data.get('home_phone', '')
        
#         # Address
#         self._save_user_address(user, data)
        
#         user.save()

#     def _save_user_address(self, user, data):
#         """Update user address fields"""
#         if data.get('mailing_address'):
#             user.address1 = data['mailing_address']
#             user.city = data['city']
#             user.state = data['state']
#             user.postal_code = data['zip_code']
#             user.county = data['county']

#     def _save_student_data(self, student, data):
#         """Update student model fields"""
#         # Personal info
#         student.preferred_name = data.get('preferred_name', '')
#         student.gender = data.get('gender', '')
#         student.gender_identity = data.get('gender_identity', '')
#         student.gender_pronoun = data.get('gender_pronoun', '')
        
#         # Demographics
#         if data.get('hispanic'):
#             student.hispanic = data['hispanic']
#         if data.get('ethnicity'):
#             student.ethnicity = data['ethnicity']
        
#         # School info
#         if data.get('highschool'):
#             student.highschool = data['highschool']
#         if data.get('cte'):
#             student.cte = data['cte']
#         if data.get('graduation_year'):
#             student.graduation_year = data['graduation_year']
        
#         # Education levels
#         student.parent1_education_level = data.get('parent1_education_level')
#         student.parent2_education_level = data.get('parent2_education_level')
        
#         # Citizenship
#         if data.get('us_citizen'):
#             if not student.meta:
#                 student.meta = {}
#             student.meta['us_citizen'] = data['us_citizen']

#     def _handle_new_highschool(self, student, data):
#         """Handle creation of new high school if needed"""
#         if not self.data.get('highschool_not_listed'):
#             return
        
#         new_hs_name = data.get('new_highschool_name')
#         new_counselor_name = data.get('new_highschool_counselor_name')
#         new_counselor_email = data.get('new_highschool_counselor_email')
        
#         # Create new high school
#         import time
#         new_highschool = HighSchool.get_or_add(
#             new_hs_name + "*",
#             status='active',
#             code=time.time()
#         )
        
#         # Notify counselor and log result
#         email_sent = HighSchool.notify_new_counselor(
#             new_counselor_name,
#             new_counselor_email
#         )
        
#         note_prefix = 'Sent' if email_sent else 'Failed to send'
#         student.add_note(
#             None,
#             f'{note_prefix} email to school counselor {new_counselor_name}, {new_counselor_email}'
#         )
        
#         # Store counselor info in notifications
#         notifications = student.notifications or {}
#         notifications['new_highschool_counselor_name'] = new_counselor_name
#         notifications['new_highschool_counselor_email'] = new_counselor_email
#         student.notifications = notifications
        
#         # Update form data with new high school
#         data['highschool'] = new_highschool

#     def _save_notifications(self, student, data):
#         """Update student notification preferences"""
#         notifications = student.notifications or {}
        
#         notifications['cell_phone_opt_in'] = data.get('cell_phone_opt_in')
        
#         if self.data.get('no_ssn'):
#             notifications['signed_no_ssn_waiver'] = True
        
#         student.notifications = notifications

#     def _save_parent_data(self, student, data):
#         """Update parent/guardian information"""
#         if not student.meta:
#             student.meta = {}
        
#         # Parent 1
#         if data.get('parent_name'):
#             student.meta['parent_name'] = data['parent_name']
#         if data.get('parent_email'):
#             student.parent_email = data['parent_email']
#         if data.get('parent_phone'):
#             student.parent_phone = data['parent_phone']
#         if data.get('parent_education'):
#             student.meta['parent_education'] = data['parent_education']
        
#         # Parent 2
#         if data.get('parent2_name'):
#             student.meta['parent2_name'] = data['parent2_name']
#         if data.get('parent2_phone'):
#             student.meta['parent2_phone'] = data['parent2_phone']
#         if data.get('parent2_email'):
#             student.meta['parent2_email'] = data['parent2_email']
        
#         # Parent interests
#         student.meta['parent1_interest'] = data.get('parent1_interest')
#         student.meta['parent2_interest'] = data.get('parent2_interest')
        
#         # Other parent-related fields
#         if data.get('sevis_id'):
#             student.meta['sevis_id'] = data['sevis_id']
        
#         student.meta['qualify_tuition_assistance'] = data.get('qualify_tuition_assistance', False)

#     def _finalize_student_record(self, student, data):
#         """Set final student record fields before save"""
#         student.profile_last_reviewed = active_term()
        
#         if data.get('graduation_year'):
#             student.grade_level = student.get_grade_level(data.get('graduation_year'))
#             data = self.cleaned_data

#             user = student.user

#             if data.get('first_name'):
#                 user.first_name = data['first_name']

#             if data.get('last_name'):
#                 user.last_name = data['last_name']

#             if data.get('middle_name'):
#                 user.middle_name = data['middle_name']

#             if data.get('suffix'):
#                 user.suffix = data['suffix']

#             user.email = data['email']
#             # user.secondary_email = data['email']

#             if data.get('alt_username'):
#                 user.alt_username = data['alt_username']

#             if data.get('secondary_email'):
#                 user.secondary_email = data['secondary_email']
            
#             if data.get('psid'):
#                 user.psid = self.data.get('psid')
                
#             if data.get('ssn'):
#                 user.ssn = data['ssn']
#             # else:
#             #     user.ssn = ''

#             if data.get('cell_phone'):
#                 user.primary_phone = data['cell_phone']
#             user.secondary_phone = data.get('home_phone', '')

#             if data.get('date_of_birth'):
#                 user.date_of_birth = data['date_of_birth']

#             if data.get('country_of_birth'):
#                 user.country_of_birth = data.get('country_of_birth')

#             if data.get('mailing_address'):
#                 user.address1 = data['mailing_address']
#                 user.city = data['city']
#                 user.state = data['state']
#                 user.postal_code = data['zip_code']
#                 user.county = data['county']

#             if data.get('password'):
#                 user.set_password(data['password'])
                
#             user.save()

#             student.user = user
#             notifications = student.notifications
#             if not notifications:
#                 notifications = {}

#             if self.data.get('highschool_not_listed'):
#                 new_highschool_name = data.get('new_highschool_name')
#                 new_highschool_counselor_name = data.get('new_highschool_counselor_name')
#                 new_highschool_counselor_email = data.get('new_highschool_counselor_email')

#                 import time
#                 # create new high school and email counselor
#                 new_highschool = HighSchool.get_or_add(
#                     new_highschool_name + "*",
#                     status='active',
#                     code=time.time()
#                 )

#                 if not HighSchool.notify_new_counselor(
#                     new_highschool_counselor_name,
#                     new_highschool_counselor_email
#                 ):
#                     student.add_note(
#                         None,
#                         'Failed to send email to school counselor ' + data.get('new_highschool_counselor_name') + ', ' + data.get('new_highschool_counselor_email')
#                     )
#                 else:
#                     student.add_note(
#                         None,
#                         'Sent email to school counselor ' + data.get('new_highschool_counselor_name') + ', ' + data.get('new_highschool_counselor_email')
#                     )

#                 notifications['new_highschool_counselor_name'] = data.get('new_highschool_counselor_name')
#                 notifications['new_highschool_counselor_email'] = data.get('new_highschool_counselor_email')

#                 # assign new high school to form high school field
#                 data['highschool'] = new_highschool

#             notifications['cell_phone_opt_in'] = data.get('cell_phone_opt_in')
#             student.notifications = notifications

#             if self.data.get('no_ssn'):
#                 notifications['signed_no_ssn_waiver'] = True
                
#             student.preferred_name = data.get('preferred_name', '')

#             student.gender = data.get('gender', '')
#             student.gender_identity = data.get('gender_identity', '')
#             student.gender_pronoun = data.get('gender_pronoun', '')

#             if data.get('hispanic'):
#                 student.hispanic = data['hispanic']

#             if data.get('ethnicity'):
#                 student.ethnicity = data['ethnicity']
            
#             if not student.meta:
#                 student.meta = {}

#             if data.get('parent_name'):
#                 student.meta['parent_name'] = data['parent_name']

#             if data.get('sevis_id'):
#                 student.meta['sevis_id'] = data['sevis_id']

#             if data.get('parent_email'):
#                 student.parent_email = data['parent_email']
            
#             if data.get('parent_phone'):
#                 student.parent_phone = data['parent_phone']

#             if data.get('parent2_name'):
#                 student.meta['parent2_name'] = data['parent2_name']

#             if data.get('parent2_phone'):
#                 student.meta['parent2_phone'] = data['parent2_phone']

#             if data.get('parent2_email'):
#                 student.meta['parent2_email'] = data['parent2_email']

#             if data.get('parent_education'):
#                 student.meta['parent_education'] = data['parent_education']

#             if data.get('highschool'):
#                 student.highschool = data['highschool']

#             if data.get('cte'):
#                 student.cte = data['cte']

#             if data.get('graduation_year'):
#                 student.graduation_year = data['graduation_year']

#             if data.get('us_citizen'):
#                 student.meta['us_citizen'] = data['us_citizen']

#             student.parent1_education_level = data.get('parent1_education_level')
#             student.parent2_education_level = data.get('parent2_education_level')

#             student.meta['parent1_interest'] = data.get('parent1_interest')
#             student.meta['parent2_interest'] = data.get('parent2_interest')

#             student.meta['qualify_tuition_assistance'] = data.get('qualify_tuition_assistance', False)

#             student.profile_last_reviewed = active_term()
#             if data.get('graduation_year'):
#                 student.grade_level = student.get_grade_level(data.get('graduation_year'))
#             student.save()

#             return student


_TENANT_FORMS = {
    'StudentRecommendationForm': 'recommendation_form',
    'StudentFerpaForm': 'ferpa_form',
    'StudentVerifyEmailForm': 'verify_email_form',
}


def __getattr__(name):
    """Back-compat shim: these forms moved to the tenant app
    (myce_tenant_configs.services.<module>), resolved via get_tenant_service.
    Importers keep `from cis.forms.student import StudentRecommendationForm`
    (or StudentFerpaForm) unchanged. PEP 562 module __getattr__ runs only for
    names not already defined in this module."""
    if name in _TENANT_FORMS:
        from cis.services.tenant_services import get_tenant_service
        return getattr(get_tenant_service(_TENANT_FORMS[name]), name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')