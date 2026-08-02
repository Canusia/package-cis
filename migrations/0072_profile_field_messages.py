"""Move per-field label/help-text config off the signup setting.

`signup.form_field_messages` was a JSON string; it becomes a native dict on
`student_profile.field_messages`, where it joins field order and editability
in one settings page.

Only keys the new control can render (`_MESSAGE_FIELDS_AT_0072` — the profile
fields plus the three signup mechanics) are moved. The legacy JSON was free-form, so a
tenant may carry keys that are not profile fields at all (`highschool_not_listed`)
or fields since dropped from `StudentProfileForm`. Those have no row in the new
table, and the setting page rewrites `field_messages` wholesale on save, so
moving them across would destroy them the first time an admin hits Save. They
are instead left behind on the signup row (with a warning naming them) where
they remain readable and recoverable.
"""
import json
import logging

from django.conf import settings as django_settings
from django.db import migrations

logger = logging.getLogger(__name__)

PREFIX = getattr(django_settings, 'CAMPUS_CODE_PREFIX')
SIGNUP_KEY = f'{PREFIX}_signup'
PROFILE_KEY = f'{PREFIX}_student_profile'


def _get(Setting, key):
    return Setting.objects.filter(key=key).first()


# Frozen copy of cis.settings.student_profile.message_fields() as it stood when
# this migration was written (2026-07-28). Deliberately NOT imported from live
# code: that list is now derived from the tenant's form, and a historical
# migration must produce the same result on a fresh database in five years'
# time as it did on the day it was applied.
_MESSAGE_FIELDS_AT_0072 = [
    'first_name',
    'preferred_name',
    'last_name',
    'middle_name',
    'other_last_names_used',
    'email',
    'permanent_address_country',
    'permanent_address',
    'permanent_address2',
    'city',
    'county',
    'state',
    'zip_code',
    'same_as_permanent',
    'mailing_country',
    'mailing_address',
    'mailing_address2',
    'mailing_city',
    'mailing_county',
    'mailing_state',
    'mailing_zip_code',
    'preferred_phone',
    'home_phone',
    'cell_phone',
    'cell_phone_opt_in',
    'legal_sex',
    'gender',
    'date_of_birth',
    'country_of_birth',
    'primary_citizenship',
    'ssn',
    'verify_student_ssn',
    'hispanic',
    'ethnicity',
    'parent_guardian_type',
    'parent_first_name',
    'parent_last_name',
    'parent_email',
    'parent_phone',
    'highschool',
    'start_date',
    'cte',
    'graduation_date',
    'new_highschool_name',
    'new_highschool_counselor_name',
    'new_highschool_counselor_email',
    'current_grade_level',
    'password',
    'confirm_password',
    'signature',
]


def _allowed_keys():
    """Field names the new profile-fields table can render a row for."""
    return set(_MESSAGE_FIELDS_AT_0072)


def move_messages(apps, schema_editor):
    Setting = apps.get_model('cis', 'Setting')
    signup_row = _get(Setting, SIGNUP_KEY)
    if not signup_row or not isinstance(signup_row.value, dict):
        return
    raw = signup_row.value.get('form_field_messages')
    if raw in (None, ''):
        return
    try:
        messages = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning(
            'Leaving unparseable form_field_messages on %s in place', SIGNUP_KEY)
        return
    if not isinstance(messages, dict):
        return

    allowed = _allowed_keys()
    recognised = {k: v for k, v in messages.items() if k in allowed}
    leftover = {k: v for k, v in messages.items() if k not in allowed}

    if recognised:
        profile_row = _get(Setting, PROFILE_KEY)
        if profile_row is None:
            profile_row = Setting(key=PROFILE_KEY, value={})
        value = dict(profile_row.value or {})
        value['field_messages'] = recognised
        profile_row.value = value
        profile_row.save()

    signup_value = dict(signup_row.value)
    if leftover:
        # No row exists for these in the new table, and the setting page
        # rewrites field_messages wholesale on save — leave them on signup
        # rather than move them somewhere an admin would silently erase.
        logger.warning(
            'Not moving unrecognised form_field_messages keys from %s to %s; '
            'they stay on the signup setting: %s',
            SIGNUP_KEY, PROFILE_KEY, ', '.join(sorted(leftover)))
        signup_value['form_field_messages'] = json.dumps(leftover)
    else:
        signup_value.pop('form_field_messages', None)
    signup_row.value = signup_value
    signup_row.save()


def restore_messages(apps, schema_editor):
    Setting = apps.get_model('cis', 'Setting')
    profile_row = _get(Setting, PROFILE_KEY)
    if not profile_row or not isinstance(profile_row.value, dict):
        return
    messages = profile_row.value.get('field_messages')
    if messages is None:
        return

    signup_row = _get(Setting, SIGNUP_KEY)
    if signup_row is None:
        signup_row = Setting(key=SIGNUP_KEY, value={})
    signup_value = dict(signup_row.value or {})

    # The forward pass may have left unrecognised keys behind on signup; merge
    # onto them instead of clobbering. Keys we are restoring win.
    existing_raw = signup_value.get('form_field_messages')
    existing = {}
    if existing_raw not in (None, ''):
        try:
            existing = json.loads(existing_raw)
        except (TypeError, ValueError):
            logger.warning(
                'Unparseable form_field_messages already on %s; leaving both '
                'rows untouched rather than overwriting it', SIGNUP_KEY)
            return
        if not isinstance(existing, dict):
            logger.warning(
                'Non-dict form_field_messages already on %s; leaving both rows '
                'untouched rather than overwriting it', SIGNUP_KEY)
            return

    merged = dict(existing)
    merged.update(messages if isinstance(messages, dict) else {})
    signup_value['form_field_messages'] = json.dumps(merged)
    signup_row.value = signup_value
    signup_row.save()

    value = dict(profile_row.value)
    value.pop('field_messages', None)
    profile_row.value = value
    profile_row.save()


class Migration(migrations.Migration):

    dependencies = [
        ('cis', '0071_alter_historicalstudentregistration_status_and_more'),
    ]

    operations = [
        migrations.RunPython(move_messages, restore_messages),
    ]
