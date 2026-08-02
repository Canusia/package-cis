from django import forms
from django.forms import ModelForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

class NoteForm(forms.Form):
    """
    Generic form to add note
    """
    id = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )

    note = forms.CharField(
        required=True,
        widget=forms.Textarea
    )

    model = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )

    reply_to = forms.CharField(
        required=False,
        widget=forms.HiddenInput
    )

    add_to = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )

    ajax = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )

    def clean_note(self):
        """
        Check to make sure note is not empty
        """
        data = self.cleaned_data['note']
        if not data:
            raise ValidationError(_("Please enter a note"))
        return data

class StudentPlanNoteForm(NoteForm, forms.Form):
    note_type = forms.MultipleChoiceField(
        required=False,
        choices=[
            ('to_student', 'Email to Student'),
            # ('to_advisor', 'Email to Advisor'),
            ('to_parent', 'Email to Parent'),
            # ('sms_to_student', 'Send as SMS'),
            # ('to_counselor', 'Send to School Counselor')
        ],
        help_text='Default is \'Private\'',
        widget=forms.CheckboxSelectMultiple()
    )

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)

        from cis.utils import user_has_cis_role, user_has_highschool_admin_role

        if user_has_highschool_admin_role(request.user):
            self.fields['note_type'].choices = [
                ('to_advisor', 'Email to Advisor'),
                ('to_student', 'Email to Student')
            ]
            self.fields['note_type'].initial = 'to_advisor'
            
    def save(self, request, commit=True):
        data = self.cleaned_data
        from degree_plan.models import StudentPlanNote, StudentPlan

        note = StudentPlanNote(
            createdby=request.user
        )
        note.student_plan = StudentPlan.objects.get(
            pk=data['add_to']
        )
        note.note = data.get('note')

        meta = {}
        if data.get('note_type'):
            meta['type'] = data.get('note_type')

        else:
            meta['type'] = ['private']

        note.meta = meta
        note.save()

        if data.get('note_type')[0] == 'to_student':
            note.send_to_student()

        if data.get('note_type')[0] == 'to_counselor':
            note.send_to_counselor()
        return note

class StudentNoteForm(NoteForm, forms.Form):
    type = forms.MultipleChoiceField(
        required=False,
        choices=[
            ('to_student', 'Email to Student'),
            ('to_parent', 'Email to Parent'),
            ('sms_to_student', 'Send as SMS'),
            ('to_counselor', 'Send to School Counselor')
        ],
        help_text='Default is \'Private\'',
        widget=forms.CheckboxSelectMultiple()
    )

    # media = forms.FileField(
    #     required=False,
    #     widget=forms.FileInput(),
    #     label='Attach File (Optional)'
    # )


class TeacherNoteForm(NoteForm, forms.Form):
    type = forms.MultipleChoiceField(
        required=False,
        choices=[
            ('to_instructor', 'Email to Instructor'),
        ],
        help_text='Default is \'Private\'',
        widget=forms.CheckboxSelectMultiple()
    )

    # media = forms.FileField(
    #     required=False,
    #     widget=forms.FileInput(),
    #     label='Attach File (Optional)'
    # )

class StudentNoteReplyForm(StudentNoteForm, NoteForm, forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        del self.fields['type']

class TeacherApplicationNoteForm(NoteForm, forms.Form):
    type = forms.ChoiceField(
        required=False,
        choices=[
            ('to_instructor', 'Send to Instructor via Email'),
            ('public', 'Share with Faculty')
        ],
        help_text='Default is \'Private\' and visible to staff only. Notes shared with faculty will be visible to them when they are reviewing the application.',
        widget=forms.RadioSelect()
    )

class VisitReportNoteForm(NoteForm, forms.Form):
    type = forms.ChoiceField(
        required=False,
        choices=[
            ('public', 'Share with Faculty')
        ],
        help_text='Default is \'Private\' and visible to staff only. Notes shared with faculty will be emailed to them.',
        widget=forms.RadioSelect()
    )

class ClassSectionNoteForm(NoteForm, forms.Form):
    type = forms.ChoiceField(
        required=False,
        choices=[
            ('to_instructor', 'Send to Instructor'),
            ('public', 'Not Private')
        ],
        help_text='Default is \'Private\' and visible to staff only',
        widget=forms.RadioSelect()
    )

class EventNoteForm(NoteForm, forms.Form):
    ...