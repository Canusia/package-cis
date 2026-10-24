from django import forms
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from django.forms import ValidationError

from cis.utils import get_movable_reference_choices, move_references
from cis.campus_context import is_multi_campus
from cis.campus_gate import get_process_campus_ids, scope_queryset_by_campus
from cis.services.term_hierarchy import apply_term_tree, term_with_descendant_ids
from cis.models.term import (
    Term, AcademicYear
)


def _year_campus(year):
    return year.campus if year else None


def _term_campus(term):
    return term.academic_year.campus


def _same_campus(a, b):
    """Unassigned (null) campus matches any campus, as in the campus scoping."""
    return a is None or b is None or a.pk == b.pk


def _campus_choices(field, queryset, user, campus_path, campus_of):
    """Multi-campus only (#113): limit to the user's campuses (null campus stays)
    and add the campus to each label, since two campuses' years share names.

    Returns the queryset to use; single-campus deployments get it unchanged.
    """
    if not is_multi_campus():
        return queryset
    if user is not None:
        queryset = scope_queryset_by_campus(queryset, user, campus_path=campus_path)
    # Group by campus first, keeping the existing order within each campus.
    order = queryset.query.order_by or queryset.model._meta.ordering
    queryset = queryset.order_by(f'{campus_path}__name', *order)
    base = field.label_from_instance

    def label(obj):
        campus = campus_of(obj)
        return f'{base(obj)} ({campus.name if campus else "unassigned"})'
    field.label_from_instance = label
    return queryset

class AcademicYearUploadForm(forms.Form):
    file = forms.FileField(
        widget=forms.FileInput(attrs={'accept': 'text/csv'})
    )


class TermUploadForm(forms.Form):
    file = forms.FileField(
        widget=forms.FileInput(attrs={'accept': 'text/csv'})
    )


class MigrateAcademicYearForm(forms.Form):
    
    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='migrate_academic_year'
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

    def __init__(self, record, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        qs = AcademicYear.objects.select_related('campus').exclude(id=record.id)
        if is_multi_campus() and record.campus_id:
            # Moving references to another campus's year is never wanted.
            qs = qs.filter(Q(campus=record.campus_id) | Q(campus__isnull=True))
        self.fields['destination_record'].queryset = _campus_choices(
            self.fields['destination_record'], qs, user, 'campus', _year_campus)

        # EXISTS only -- loading every referencing row timed out large records.
        self.fields['move_items'].choices = get_movable_reference_choices(record)

    def save(self, request, record):
        data = self.cleaned_data
        # Sets each row's matched field (not a fixed attribute) and saves
        # it once, keeping signals and history (issue #70).
        success, message = move_references(
            record, data.get('destination_record'), data.get('move_items'))

        return (success, message)

class MigrateTermForm(forms.Form):
    
    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='migrate_term'
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

    def __init__(self, record, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        field = self.fields['destination_record']
        qs = Term.objects.select_related(
            'academic_year__campus').exclude(id=record.id)
        campus_id = record.academic_year.campus_id
        if is_multi_campus() and campus_id:
            qs = qs.filter(Q(academic_year__campus=campus_id)
                           | Q(academic_year__campus__isnull=True))
        apply_term_tree(field, _campus_choices(
            field, qs, user, 'academic_year__campus', _term_campus))

        # EXISTS only -- loading every referencing row timed out large records.
        self.fields['move_items'].choices = get_movable_reference_choices(record)

    def save(self, request, record):
        data = self.cleaned_data
        # Sets each row's matched field (not a fixed attribute) and saves
        # it once, keeping signals and history (issue #70).
        success, message = move_references(
            record, data.get('destination_record'), data.get('move_items'))

        return (success, message)

class AcademicYearForm(forms.ModelForm):
    """
    Academic Year Form
    """
    hs_start_date = forms.DateField(
        widget=forms.DateInput(format='%m/%d/%Y'),
        label="HS Start Date",
        required=False
    )

    hs_end_date = forms.DateField(
        widget=forms.DateInput(format='%m/%d/%Y'),
        label="HS End Date",
        required=False
    )

    class Meta:
        model = AcademicYear
        fields = '__all__'
        exclude = [
            'cost_per_credit',
            'temp_id',
            'meta'
        ]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['hs_start_date'].required = True
        self.fields['hs_end_date'].required = True

        # Multi-campus (#116): a CE user may only put a year on a campus they
        # process, or the year -- and its terms -- would move out of reach.
        campus_field = self.fields.get('campus')
        if (campus_field is not None and user is not None and is_multi_campus()
                and not getattr(user, 'is_superuser', False)):
            campus_field.queryset = campus_field.queryset.filter(
                id__in=get_process_campus_ids(user))
        
    def clean_hs_start_date(self):
        data = self.cleaned_data['hs_start_date']
        return data

    def clean_hs_end_date(self):
        """
        Check to ensure end date is after start date, if not
        raises ValidationError
        """
        start_date = self.cleaned_data['hs_start_date']
        end_date = self.cleaned_data['hs_end_date']

        if end_date < start_date:
            raise ValidationError(
                _("Enter a valid end date in the future"),
                code='invalid')
        return end_date

class BulkAssignParentForm(forms.Form):
    parent = forms.ModelChoiceField(
        required=True, label='Parent Term',
        queryset=Term.objects.select_related('academic_year__campus').order_by(
            '-academic_year__name', '-code'),
    )

    def __init__(self, ids=None, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.ids = [str(i) for i in (ids or [])]
        self.user = user
        field = self.fields['parent']
        qs = field.queryset
        if self.ids:
            qs = qs.exclude(pk__in=self.ids)
        apply_term_tree(field, _campus_choices(
            field, qs, user, 'academic_year__campus', _term_campus))

    def save(self):
        """Returns (assigned, skipped); skips self, cycles and, in multi-campus
        mode, terms on another campus or outside the user's campuses."""
        parent = self.cleaned_data['parent']
        terms = Term.objects.select_related('academic_year__campus').filter(
            pk__in=self.ids)
        multi = is_multi_campus()
        if multi and self.user is not None:
            terms = scope_queryset_by_campus(
                terms, self.user, campus_path='academic_year__campus')
        assigned = 0
        skipped = len(self.ids) - len(terms)
        for term in terms:
            if (term.pk == parent.pk or term.would_create_cycle(parent)
                    or (multi and not _same_campus(
                        _term_campus(term), _term_campus(parent)))):
                skipped += 1
                continue
            term.parent = parent
            term.save(update_fields=['parent'])
            assigned += 1
        return assigned, skipped


class TermForm(forms.ModelForm):

    # payment_due_date = forms.DateField(
    #     widget=forms.DateInput(format='%m/%d/%Y'),
    #     label="Payment Due Date",
    #     help_text='This is not the sequence class payment due date'
    # )

    class Meta:
        model = Term
        fields = '__all__'

        exclude = [
            'temp_id',
            'dates',
            'meta'
        ]
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        year_field = self.fields['academic_year']
        years = AcademicYear.objects.select_related('campus')
        if is_multi_campus():
            years = years.order_by('-name')  # grouped by campus below
        year_field.queryset = _campus_choices(
            year_field, years, user, 'campus', _year_campus)

        parent_field = self.fields['parent']
        qs = Term.objects.select_related('academic_year__campus').order_by(
            '-academic_year__name', '-code')
        if self.instance and self.instance.pk:
            # Itself and its own sub-terms can never be its parent.
            qs = qs.exclude(pk__in=term_with_descendant_ids(self.instance.pk))
        # The pk is a uuid default, so a new term has one too: check its year.
        if self.instance.academic_year_id:
            campus_id = self.instance.academic_year.campus_id
            if is_multi_campus() and campus_id:
                qs = qs.filter(Q(academic_year__campus=campus_id)
                               | Q(academic_year__campus__isnull=True))
        apply_term_tree(parent_field, _campus_choices(
            parent_field, qs, user, 'academic_year__campus', _term_campus))
        parent_field.required = False

    def clean_parent(self):
        parent = self.cleaned_data.get('parent')
        if parent is None:
            return parent
        if self.instance and self.instance.pk:
            if parent.pk == self.instance.pk:
                raise ValidationError('A term cannot be its own parent.')
            if self.instance.would_create_cycle(parent):
                raise ValidationError(
                    'That parent would create a circular term hierarchy.')
        return parent

    def clean(self):
        cleaned = super().clean()
        parent = cleaned.get('parent')
        year = cleaned.get('academic_year')
        # Compared with the year chosen on this submission, not the saved one.
        if (is_multi_campus() and parent and year
                and not _same_campus(_year_campus(year), _term_campus(parent))):
            self.add_error(
                'parent', 'The parent term must be on the same campus as this '
                          "term's academic year.")
        # Moving a parent term to another campus would strand its sub-terms.
        if (is_multi_campus() and year and year.campus_id
                and not self.instance._state.adding
                and self.instance.sub_terms.filter(
                    academic_year__campus__isnull=False).exclude(
                    academic_year__campus=year.campus_id).exists()):
            self.add_error(
                'academic_year', 'This term has sub-terms on another campus; '
                                 'move or detach them first.')
        return cleaned

    def save(self, commit=False):
        record = super().save(commit=False)
        data = self.cleaned_data

        dates = record.dates if record.dates else {}
        # dates['payment_due_date'] = data.get('payment_due_date').strftime('%m/%d/%Y')
        
        record.dates = dates
        if commit:
            record.save()

        return record