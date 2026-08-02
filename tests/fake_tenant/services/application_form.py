"""A minimal but complete stand-in for a real tenant's application spec.

Exercises every extension point at once — fields, rules, the validate()
escape hatch with VALIDATE_FIELDS, and post_save — so that running cis's suite
under cis.tests.armed_settings proves the engine's own tests are isolated from
whatever a tenant happens to declare.
"""
from django.core.exceptions import ValidationError

APPLICATION_FIELDS = [
    {'name': 'first_name', 'type': 'text', 'label': 'First name',
     'target': 'user', 'validators': ['title_case']},
    {'name': 'tribal_affiliation', 'type': 'text', 'label': 'Tribal affiliation',
     'target': 'meta', 'required': False},
    {'name': 'no_ssn', 'type': 'agreement', 'label': 'I have no SSN',
     'target': 'meta', 'required': False},
]

APPLICATION_RULES = [
    {'rule': 'fields_must_differ',
     'fields': ['first_name', 'tribal_affiliation']},
]

VALIDATE_FIELDS = ('tribal_affiliation',)


def validate(form, cleaned_data):
    if cleaned_data.get('tribal_affiliation') == 'invalid':
        raise ValidationError('tenant validator rejected this value')


def post_save(form, student, commit=True):
    """The derived write a storage target cannot express."""
    if form.cleaned_data.get('no_ssn'):
        notifications = student.notifications or {}
        notifications['signed_no_ssn_waiver'] = True
        student.notifications = notifications
