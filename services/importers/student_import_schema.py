"""Single source of truth for student-importer CSV columns.

Columns are DERIVED from StudentProfileForm so they cannot drift from the
fields a student fills in manually. Rules:
  * every non-hidden form field becomes a column;
  * a field that is required in the form is required in the CSV;
  * password/confirm/ssn-verify mechanic fields are never exposed;
  * the form's `highschool` (a PK ModelChoiceField) is replaced by a single
    `highschool_ceeb` column that the importer resolves against HighSchool.code.
"""
from django import forms

from cis.forms.student_profile import StudentProfileForm


class StudentImportColumns:
    # Mechanic / system-managed fields that never appear in the CSV.
    EXCLUDED = frozenset({
        'password', 'confirm_password', 'verify_student_ssn',
        'signature', 'cte',
        # highschool is represented by highschool_ceeb instead of a PK
        'highschool',
    })

    # Inserted in place of the form's `highschool` field.
    CEEB_COLUMN = 'highschool_ceeb'

    @classmethod
    def _form_fields(cls):
        # Unbound instance is enough to read field declarations + widgets.
        return StudentProfileForm().fields

    @classmethod
    def _is_hidden(cls, field):
        return isinstance(field.widget, forms.HiddenInput)

    @classmethod
    def headers(cls):
        cols = []
        for name, field in cls._form_fields().items():
            if name in cls.EXCLUDED or cls._is_hidden(field):
                if name == 'highschool':
                    cols.append(cls.CEEB_COLUMN)
                continue
            cols.append(name)
        if cls.CEEB_COLUMN not in cols:
            cols.append(cls.CEEB_COLUMN)
        return cols

    @classmethod
    def required(cls):
        req = []
        for name, field in cls._form_fields().items():
            if name in cls.EXCLUDED or cls._is_hidden(field):
                continue
            if field.required:
                req.append(name)
        req.append(cls.CEEB_COLUMN)
        return req

    @classmethod
    def field_definitions(cls):
        required = set(cls.required())
        defs = []
        fields = cls._form_fields()
        for name in cls.headers():
            if name == cls.CEEB_COLUMN:
                defs.append({
                    'name': name,
                    'required': True,
                    'label': 'High School CEEB code',
                })
                continue
            field = fields[name]
            defs.append({
                'name': name,
                'required': name in required,
                'label': str(field.label or name),
            })
        return defs
