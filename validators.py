import datetime, os, json

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.template import Context, Template
from django.core import validators
from django.core.validators import RegexValidator, validate_email

from cron_validator import CronValidator

numeric = RegexValidator(r'^[0-9+]', 'Only digit characters.')
floating_number = RegexValidator(r'[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?')

def validate_json(value):
    try:
        val = json.loads(value)
        return value
    except:
        raise ValidationError('Please enter a valid JSON string')

def validate_html_short_code(value):
    context = Context()

    try:
        value = Template(value)
        value = value.render(context)
        return value
    except Exception as e:
        raise ValidationError('The text contains invalid shortcode. Please fix it and try again.')

def validate_11_number(value):

    value = str(value)
    if len(value) != 11:
        raise ValidationError('Enter an 11 digit phone number and try again.')

    if not int(value):
        raise ValidationError('The phone number can only contain numbers. Please fix it and try again.')

def validate_relative_path(value):
    if os.path.isabs(value):
        raise ValidationError(
            _(f'Enter a relative path. \'{value}\' is an absolute path')
        )
    return value

def validate_email_list(value):
    emails = value.split(',')
    for email in emails:
        try:
            validate_email(email)
        except:
            raise ValidationError(
                        _(f'\'{value}\' is not a valid comma email list')
                    )
    return ','.join(emails)

def validate_filename_hhmmddyyyy(value):
    try:
        now = datetime.datetime.now()

        file_name = Template(value)
        context = Context({
            'hh': now.strftime("%H"),
            'mm': now.strftime("%m"),
            'dd': now.strftime("%d"),
            'yyyy': now.strftime("%Y"),
        })

        file_name = file_name.render(context)
    except Exception as e:
        raise ValidationError(
            _(f'\'{value}\' is not a valid value')
        )

    return value

def validate_cron(value):
    try:
        if not CronValidator.parse(value):
            raise ValidationError(
                _(f'\'{value}\' is not a valid cron string. Please enter a valid string')
            )
    except:
        raise ValidationError(
                _(f'\'{value}\' is not a valid cron string. Please enter a valid string')
            )

    return value

def validate_ssn(value):
    import re
    ssn_text = (re.findall(r'\d+', value))
    not_allowed_values = [
        '000000000',
        '111111111',
        '222222222',
        '333333333',
        '444444444',
        '555555555',
        '666666666',
        '777777777',
        '888888888',
        '999999999',
        '123456789',
    ]
    ssn_pattern = r"^(?!0{3})(?!6{3})[0-8]\d{2}-(?!0{2})\d{2}-(?!0{4})\d{4}$"
    if not bool(re.match(ssn_pattern, value)):
        raise ValidationError(
            _(
                "Social Security Number entered is not valid. Please try again"
            ), code='invalid'
        )

    if str(ssn_text).startswith('8'):
        raise ValidationError(
            _(
                "Social Security Numbers starting with an 8 are not valid. Please try again"
            ), code='invalid'
        )
    
    if ssn_text and len(''.join(ssn_text)) != 9:
        raise ValidationError(
            _(
                "Please enter your 9 digit Social Security Number"
            ), code='invalid'
        )
    
    if ''.join(ssn_text) in not_allowed_values:
        raise ValidationError(
            _(
                "Please enter your 9 digit Social Security Number"
            ), code='invalid'
        )
    return value


def validate_profile_display(value):
    """Validate the configurable Student.asHTML layout (the `profile_display`
    setting). Blank is allowed (means: use the default). Otherwise the value
    must be a JSON list of rows; each row a JSON list of columns; each column
    either a string (field path or '' for a blank cell) or an object with both
    'field' and 'label' string keys. Every referenced field key must be in the
    allow-set derived from StudentProfileForm (available_display_fields()).
    Returns the original value on success."""
    if value in (None, ''):
        return value

    try:
        data = json.loads(value)
    except Exception:
        raise ValidationError('Please enter a valid JSON layout.')

    if not isinstance(data, list):
        raise ValidationError('Layout must be a JSON list of rows.')

    # Imported lazily to avoid a settings<->forms import cycle at module load.
    from cis.settings.student_profile import student_profile
    allowed = set(student_profile.available_display_fields().keys())
    allowed.add('')  # blank cell

    for row in data:
        if not isinstance(row, list):
            raise ValidationError('Each row must be a JSON list of columns.')
        for column in row:
            if isinstance(column, str):
                key = column
            elif isinstance(column, dict):
                if 'field' not in column or 'label' not in column:
                    raise ValidationError(
                        "Each object column must have 'field' and 'label'.")
                if not isinstance(column['field'], str) or not isinstance(
                        column['label'], str):
                    raise ValidationError(
                        "Column 'field' and 'label' must be strings.")
                key = column['field']
            else:
                raise ValidationError(
                    'Each column must be a string or a {field,label} object.')

            if key not in allowed:
                raise ValidationError(
                    f"Unknown field '{key}'. Allowed fields are listed in the "
                    f"setting help text.")

    return value


def validate_display_layout(value):
    """Validate a model-detail layout (the `profile_display` value used by the
    configurable asHTML layouts). Blank is allowed (means: use the default).

    Otherwise the value must be a JSON list of rows; each row a JSON list of
    columns; each column either a string (a field path, or '' for a blank cell)
    or an object with string 'field' and 'label' keys. Field keys are NOT
    restricted to a known set — any model path/property is allowed (an unknown
    path simply renders as a blank cell). Returns the original value on success.
    """
    if value in (None, ''):
        return value

    try:
        data = json.loads(value)
    except Exception:
        raise ValidationError('Please enter a valid JSON layout.')

    if not isinstance(data, list):
        raise ValidationError('Layout must be a JSON list of rows.')

    for row in data:
        if not isinstance(row, list):
            raise ValidationError('Each row must be a JSON list of columns.')
        for column in row:
            if isinstance(column, str):
                continue
            if isinstance(column, dict):
                if 'field' not in column or 'label' not in column:
                    raise ValidationError(
                        "Each object column must have 'field' and 'label'.")
                if not isinstance(column['field'], str) or not isinstance(
                        column['label'], str):
                    raise ValidationError(
                        "Column 'field' and 'label' must be strings.")
                continue
            raise ValidationError(
                'Each column must be a string or a {field,label} object.')

    return value