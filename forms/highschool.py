from django import forms
from django.forms import ModelForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils.safestring import mark_safe

from django_recaptcha.fields import ReCaptchaField

from form_fields import fields as FFields

from cis.models.customuser import CustomUser
from cis.models.highschool import (
    HighSchool, HighSchoolCollegeAdvisor,
    HighSchoolTranscript
)

from cis.models.note import HSAdministratorNote

from cis.utils import YES_NO_SELECT_OPTIONS

from cis.models.district import District
from cis.models.highschool_administrator import (
    HSPosition, HSAdministratorPosition,
    HSAdministratorAccessRequest, HSAdministrator
)
from cis.models.teacher import TeacherCourseCertificate
from cis.utils import user_has_cis_role, get_foreign_key_references

from cis.validators import validate_html_short_code

class MigrateForm(forms.Form):
    
    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='migrate_highschool'
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

        self.fields['destination_record'].queryset = HighSchool.objects.all().exclude(
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
                    obj.highschool = data.get('destination_record')
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
            records = HSAdministrator.objects.filter(
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
        
        records = HSAdministrator.objects.filter(
            id__in=data.get('record_ids')
        )

        from django.core.mail import EmailMessage, EmailMultiAlternatives
        from django.template import Context, Template
        from mailer import send_mail, send_html_mail
        from django.conf import settings

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
                        send_mail(
                            subject,
                            message,
                            settings.DEFAULT_FROM_EMAIL,
                            to
                        )
                    except:
                        ...
            

        if data.get('force_password_change') == '1':
            CustomUser.objects.filter(
                id__in=records.values_list('user', flat=True)
            ).update(
                require_password_reset=True
            )

        return records

class HSTranscriptUploadForm(forms.ModelForm):
    class Meta:
        model = HighSchoolTranscript
        fields = ['description', 'media']

        labels = {
            'description': _("Description"),
            'media': _('File')
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

class HSAdminAccessRequestModelForm(ModelForm):
    captcha = ReCaptchaField(
        label=''
    )
  
    manage_student_recommendation = forms.ChoiceField(
        label='Manage Student Recommendation',
        choices=[
            ('', 'Select'),
            ('No', 'No'),
            ('Yes', 'Yes'),
        ],
        help_text='If access approved, then select'
    )
    class Meta:
        model = HSAdministratorAccessRequest
        fields = [
            'name', 'email', 'phone',
            'highschool', 'role',
            'status'
        ]
        widgets = {
            'name': forms.TextInput(
                attrs={'class': 'col-md-9'}
            ),
            'email': forms.TextInput(
                attrs={'class': 'col-md-6'}
            ),
            'phone': forms.TextInput(
                attrs={'class': 'col-md-5'}
            ),
            'role': forms.TextInput(
                attrs={'class': 'col-md-6'}
            )
        }
        labels = {
            'name': 'Your Name',
            'email': 'Your Email',
            'phone': 'Your Phone #',
            'highschool': 'Your High School',
            'role': 'Position/Title',
        }

    def clean_email(self):
        data = self.cleaned_data.get('email', '')
        return data.lower()

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request')

        super().__init__(*args, **kwargs)

        self.fields['highschool'].queryset = HighSchool.objects.filter(status__iexact='active')
        
        if not user_has_cis_role(self.request.user):
            del self.fields['status']
            del self.fields['manage_student_recommendation']
        else:
            del self.fields['captcha']

            instance = kwargs.get('instance')
            if instance and instance.status.lower() != 'submitted':
                
                # del self.fields['manage_student_recommendation']
                
                for field_name, field in self.fields.items():
                    field.disabled = True
                    field.widget.attrs['readonly'] = True

    def clean(self):
        cleaned_data = super().clean()

        email = cleaned_data.get('email')
        highschool = cleaned_data.get('highschool')
        role = cleaned_data.get('role')

        if HSAdministratorPosition.objects.filter(
                hsadmin__user__email=email,
                highschool=highschool,
                position__name__iexact=role
            ).exists():
            if not user_has_cis_role(self.request.user):
                raise ValidationError(
                    mark_safe(
                        'The selected role already exists for this email. Please <a href="/highschool_admin/">login or reset your password</a>.'
                ))

        return cleaned_data

class HSCollegeAdvisorForm(forms.Form):
    id = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )
    ajax = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )

    highschool = forms.ModelChoiceField(
            label='Select High School',
            queryset=None
        )
    advisor = forms.ModelChoiceField(
            label='Select Academic Advisor',
            queryset=None
        )
    status = forms.ChoiceField(
        choices=HighSchoolCollegeAdvisor.STATUS_OPTIONS
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['highschool'].queryset = HighSchool.objects.all()
        self.fields['advisor'].queryset = CustomUser.objects.filter(
            groups__name='ce'
        )

class HighSchoolOfferingLookupForm(forms.Form):
    highschool = forms.ModelChoiceField(
        label='Select High School',
        queryset=None
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['highschool'].queryset = HighSchool.objects.all()

class HSAdministratorPositionForm(forms.Form):
    highschool = forms.ModelChoiceField(queryset=None)
    position = forms.ModelChoiceField(queryset=None)

    status = forms.ChoiceField(choices=HSAdministratorPosition.STATUS_OPTIONS)
    since = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={
                'class': 'col-5'
            }
        )
    )

    manage_student_recommendation = forms.ChoiceField(
        label='Manage Student Recommendation',
        choices=[
            ('Yes', 'Yes'),
            ('No', 'No'),
        ],
        help_text='Setting the status to \'Inactive\' will disable this'
    )

    hs_admin = forms.CharField(
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

    def __init__(self, id, *args, **kwargs):
        super().__init__(*args, **kwargs)

        initial = kwargs.get('initial', kwargs.get('data', {'id':'-1'}))
        if id != '-1':
            self.fields['highschool'].widget.attrs['readonly'] = True
            self.fields['position'].widget.attrs['readonly'] = True

            self.fields['highschool'].queryset = HighSchool.objects.filter(
                pk=initial.get('highschool')
            )

            self.fields['position'].queryset = HSPosition.objects.filter(
                pk=initial.get('position')
            )

            self.fields['note'] = forms.CharField(
                label='Comment/Note',
                help_text='This will be added as a note',
                required=True,
                widget=forms.Textarea()
            )
        else:
            self.fields['highschool'].queryset = HighSchool.objects.all().order_by('name')
            self.fields['position'].queryset = HSPosition.objects.all().order_by('name')
        
    def save(self, request, commit=True):
        data = self.cleaned_data

        if data.get('id') != '-1':
            record = HSAdministratorPosition.objects.get(pk=data.get('id'))
            record.meta = {}

            message = f'Updating {record.position.name} @ {record.highschool.name} - {record.status}<br><br>{data["note"]}'

            note = HSAdministratorNote(
                hsadmin=record.hsadmin,
                createdby=request.user,
                note=message
            )
            note.save()
        else:
            record = HSAdministratorPosition()

            hs_admin = HSAdministrator.objects.get(pk=data.get('hs_admin'))
            record.hsadmin = hs_admin

        record.highschool = data.get('highschool')
        record.position = data.get('position')
        record.status = data.get('status')
        record.since = data.get('since')

        record.meta['manage_student_recommendation'] = data.get('manage_student_recommendation')
        
        if commit:
            record.save()

        return record

class HSAdministratorForm(forms.Form):
    first_name = forms.CharField(label='First Name', max_length=128)
    last_name = forms.CharField(label='Last Name', max_length=128)
    email = forms.EmailField(label='Primary Email')

    primary_phone = forms.CharField(label='Work Phone', max_length=20, required=False)
    secondary_phone = forms.CharField(label='Cell Phone', max_length=20, required=False)

    def clean_email(self):
        data = self.cleaned_data['email']
        return data.lower()


class HSAdministratorAddForm(forms.Form):
    """Extended form for adding new HS administrators — matches CSV import fields."""
    email = forms.EmailField(label='Email')
    first_name = forms.CharField(label='First Name', max_length=128)
    last_name = forms.CharField(label='Last Name', max_length=128)
    middle_name = forms.CharField(label='Middle Name', max_length=128, required=False)
    salutation = forms.CharField(label='Salutation', max_length=500, required=False)
    primary_phone = forms.CharField(label='Phone', max_length=50, required=False)
    ceeb = forms.CharField(
        label='CEEB Code(s)',
        max_length=500,
        help_text='Comma-separated CEEB codes for high school assignments'
    )
    position_title = forms.CharField(
        label='Position Title',
        max_length=200,
        required=False,
        initial='Primary Contact'
    )
    status = forms.ChoiceField(
        label='Status',
        choices=[('Active', 'Active'), ('Inactive', 'Inactive')],
        initial='Active',
        required=False
    )

    def clean_email(self):
        data = self.cleaned_data['email']
        return data.lower()


class MigrateHSPositionForm(forms.Form):
    
    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='migrate_position'
    )

    destination_record = forms.ModelChoiceField(
        required=True,
        queryset=None,
        label='Destination Record'
    )

    confirm = forms.BooleanField(
        required=True,
        label='I understand this action cannot be undone.'
    )
    
    def __init__(self, record, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['destination_record'].queryset = HSPosition.objects.all().exclude(
            id=record.id
        )

    def save(self, request, record):
        data = self.cleaned_data

        HSAdministratorPosition.objects.filter(
            position=record.id
        ).update(
            position=data.get('destination_record')
        )

        message = []
        message.append(
            f'Successfully moved records'
        )
        success = True
        return (success, message)


class HSPositionForm(ModelForm):
    class Meta:
        model = HSPosition
        fields = ['name']

class HighSchoolStatusUpdateForm(forms.Form):
    
    record_id = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )

    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )
    
    status = forms.ChoiceField(choices=HighSchool.STATUS_OPTIONS, label='New Status')

    note = forms.CharField(
        label='Comment/Note',
        help_text='This will be added as a private note to the high school\'s record.',
        required=True,
        widget=forms.Textarea()
    )

    hs_members = FFields.LongLabelField(
        required=False,
        label='School Members',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'border-0 bg-light h-100'
            }
        )
    )
    
    hs_member_status = forms.CharField(
        label='New Status of above School Members',
        required=False,
        help_text='Leave this blank to update individually',
        widget=forms.Select(
            choices=[('', 'Select')]+HSAdministratorPosition.STATUS_OPTIONS,
            attrs={
                'class': 'col-md-6'
            }
        )
    )

    hs_teachers = FFields.LongLabelField(
        required=False,
        label='Instructors',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'border-0 bg-light h-100'
            }
        )
    )

    hs_teacher_status = forms.CharField(
        label='New Status of above School Instructors',
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
        hs_admins = HSAdministratorPosition.objects.filter(
            highschool=record
        ).order_by(
            'hsadmin__user__last_name'
        )

        hs_admin_list = ""
        for hs_admin in hs_admins:
            hs_admin_list += f"{hs_admin.hsadmin} / {hs_admin.position} => {hs_admin.status}<br>"

        self.fields['hs_members'].initial = hs_admin_list

        teacher_certs = TeacherCourseCertificate.objects.filter(
            teacher_highschool__highschool=record
        ).order_by(
            'teacher_highschool__teacher__user__last_name'
        )

        teacher_cert_list = ""
        for teacher_cert in teacher_certs:
            teacher_cert_list += f"{teacher_cert.teacher_highschool.teacher} / {teacher_cert.course} => {teacher_cert.status}<br>"
        self.fields['hs_teachers'].initial = teacher_cert_list

    def save(self, request, record, commit=True):
        data = self.cleaned_data

        note_message = f"Updating status from {record.status} => {data['status']}<br>" + data.get('note')

        record.status = data.get('status')
        record.save()

        record.add_note(request.user, note_message)
        
        if data.get('hs_member_status'):
            HSAdministratorPosition.objects.filter(
                highschool=record
            ).update(
                status=data.get('hs_member_status')
            )
        
        if data.get('hs_teacher_status'):
            TeacherCourseCertificate.objects.filter(
                teacher_highschool__highschool=record
            ).update(
                status=data.get('hs_teacher_status')
            )
        
class HighSchoolUploadForm(forms.Form):
    file = forms.FileField(
        widget=forms.FileInput(attrs={'accept': 'text/csv'})
    )

class HSMemberUploadForm(forms.Form):
    file = forms.FileField(
        widget=forms.FileInput(attrs={'accept': 'text/csv'})
    )

class HSModelForm(ModelForm):
    class Meta:
        model = HighSchool
        fields = '__all__'
        exclude = [
            'country',
            'access_approver',
            'oncampus_sections'
        ]
        labels = {
            'district': _('District'),
            'po_box': 'PO Box',
            'state_code': 'State Code',
            'postal_code': 'Zip/Postal Code',
            'hs_type': 'School Type',
            'code': 'CEEB Code',
            'sau': 'Bldg Code'
            # 'access_approver': 'Access Approver',
            # 'oncampus_sections': 'On-Campus Sections # (comma separated)'
        }
        widgets = {
            'state': forms.TextInput(attrs={'class': 'col-md-4 col-sm-6'}),
            'state_code': forms.TextInput(attrs={'class': 'col-md-4 col-sm-6'}),
            'address2': forms.TextInput(attrs={'class': 'col-md-6 col-sm-6'}),
            'po_box': forms.TextInput(attrs={'class': 'col-md-3 col-sm-6'}),
            'city': forms.TextInput(attrs={'class': 'col-md-8 col-sm-6'}),
            'postal_code': forms.TextInput(attrs={'class': 'col-md-5 col-sm-6'}),
            'primary_phone': forms.TextInput(attrs={'class': 'col-md-6 col-sm-6'}),
            'secondary_phone': forms.TextInput(attrs={'class': 'col-md-6 col-sm-6'}),
            'fax': forms.TextInput(attrs={'class': 'col-md-6 col-sm-6'}),
            # 'oncampus_sections': forms.Textarea(attrs={'class': 'col-12'}),
        }
        help_texts = {
            'district': _('If not in list, <a href="#" class="ajax-add_new" data-parent="-1" data-id="-1" data-modal="modal-add_new" data-model="district" data-updater="id_district">Add New</a>')
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance:
            del self.fields['status']

        # if self.instance.name:
        #     self.fields['access_approver'].queryset = self.instance.administrators_in_highschool()
        # else:
        #     del self.fields['access_approver']

    def save(self, commit=True):
        instance = super(HSModelForm, self).save(commit=False)
        if commit:
            instance.save()
        return instance

    # def clean_district(self):
    #     data = self.cleaned_data['district']
    #     if not data:
    #         raise ValidationError(_("District is required"))
    #     return data

    def clean_name(self):
        data = self.cleaned_data['name'].strip()

        if not data:
            self._errors['name'] = self.error_class(['Min. 5 chars'])
        return data


def _looks_like_uuid(value):
    import uuid as _uuid
    try:
        _uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


UNCHANGED = ''
UNCHANGED_LABEL = '\u2014 leave unchanged \u2014'


class BulkRoleEditForm(forms.Form):
    """Edit a set of HSAdministratorPosition rows in one pass.

    Combines what used to be two separate bulk actions - 'edit_status' and the
    'toggle_student_recommendation' toggle - into a single 'edit' form, so
    staff set both attributes (and record a note) in one round trip.

    Each attribute defaults to 'leave unchanged'. A bulk edit that always wrote
    every field would silently overwrite the student-recommendation flag on
    every selected row whenever someone only meant to change status.

    Mirrors BulkPasswordChangeForm: instantiated with a list of record ids for
    the GET (modal render) pass, and with `data` for the POST (apply) pass.
    """
    record_ids = forms.MultipleChoiceField(
        required=True,
        label='Records to Update',
        widget=forms.CheckboxSelectMultiple,
        choices=[]
    )

    status = forms.ChoiceField(
        required=False,
        label='Status',
        choices=[]
    )

    manage_student_recommendation = forms.ChoiceField(
        required=False,
        label='Manage Student Recommendation',
        choices=[],
        help_text=(
            'Only takes effect while the role is Active. Setting the status to '
            'Inactive clears this automatically.'
        )
    )

    note = forms.CharField(
        required=False,
        label='Note',
        widget=forms.Textarea(attrs={'rows': 3}),
        help_text='Optional. Recorded on each affected administrator\'s Notes tab.'
    )

    action = forms.CharField(
        widget=forms.HiddenInput,
        initial='edit'
    )

    def __init__(self, record_ids=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        from cis.models.highschool_administrator import HSAdministratorPosition

        self.fields['status'].choices = (
            [(UNCHANGED, UNCHANGED_LABEL)] + list(HSAdministratorPosition.STATUS_OPTIONS)
        )
        self.fields['manage_student_recommendation'].choices = [
            (UNCHANGED, UNCHANGED_LABEL), ('Yes', 'Yes'), ('No', 'No'),
        ]

        if record_ids is None and kwargs.get('data') is not None:
            record_ids = kwargs['data'].getlist('record_ids')

        # Choices are always rebuilt from the database, so a client-supplied id
        # that is not a real position (or not a valid UUID) fails validation
        # rather than reaching the queryset.
        records = HSAdministratorPosition.objects.filter(
            id__in=[r for r in (record_ids or []) if _looks_like_uuid(r)]
        ).select_related('hsadmin__user', 'highschool', 'position')

        choices = []
        initial = []
        for record in records:
            label = (
                f"{record.hsadmin.user.last_name}, {record.hsadmin.user.first_name}"
                f" - {record.highschool.name} ({record.position.name})"
            )
            choices.append((str(record.id), label))
            initial.append(str(record.id))

        self.fields['record_ids'].choices = choices
        self.fields['record_ids'].initial = initial

    def clean(self):
        """At least one attribute must actually change.

        Without this, submitting the form with both selects left on
        'leave unchanged' would report "Successfully updated N record(s)"
        while writing nothing.
        """
        cleaned = super().clean()

        if not cleaned.get('status') and not cleaned.get('manage_student_recommendation'):
            raise forms.ValidationError(
                'Choose a status or a student-recommendation value to apply.'
            )

        return cleaned

    def save(self, request):
        """Apply the chosen attributes and write one note per affected admin.

        Only attributes the user actually chose are written; anything left on
        'leave unchanged' is not touched on any selected row.

        Returns (updated_count, notes_created_count).
        """
        from cis.models.highschool_administrator import HSAdministratorPosition
        from cis.models.note import HSAdministratorNote

        data = self.cleaned_data
        status = data.get('status')
        recommendation = data.get('manage_student_recommendation')
        note_text = (data.get('note') or '').strip()

        records = HSAdministratorPosition.objects.filter(
            id__in=data['record_ids']
        ).select_related('hsadmin__user', 'highschool', 'position')

        per_admin = {}
        updated = 0
        for record in records:
            if status:
                record.status = status
            if recommendation:
                record.meta['manage_student_recommendation'] = recommendation
            record.save()
            updated += 1
            per_admin.setdefault(record.hsadmin, []).append(
                f"{record.highschool.name} ({record.position.name})"
            )

        changes = []
        if status:
            changes.append(f'Status set to {status}')
        if recommendation:
            changes.append(f'Manage student recommendation set to {recommendation}')
        summary = '; '.join(changes)

        notes_created = 0
        if note_text:
            for hsadmin, places in per_admin.items():
                note = HSAdministratorNote()
                note.hsadmin = hsadmin
                note.createdby = request.user
                note.note = (
                    f"{summary} for: " + ', '.join(sorted(places))
                    + f"\n\n{note_text}"
                )
                note.save()
                notes_created += 1

        return updated, notes_created
