import io
import csv
import re

from django import forms
from django.db.models import Count, Q
from django.urls import reverse_lazy
from django.utils.encoding import force_str
from django.utils import timezone
from django.core.files.base import ContentFile

from cis.backends.storage_backend import PrivateMediaStorage
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.utils import COUNTRY_LIST, STATE_LIST, YES_NO_SELECT_OPTIONS, YES_NO_OPTIONS

from cis.models.student import Student
from cis.models.section import StudentRegistration


class undup_students(forms.Form):
    COUNTRY_CODE_TO_NAME = dict(COUNTRY_LIST)
    STATE_CODES = {abbr for abbr, _ in STATE_LIST}


    account_verified = forms.ChoiceField(
        choices=YES_NO_OPTIONS,
        label='Only Send Verified Records',
        required=False,
        widget=forms.Select(attrs={
            'disabled': True
        })
    )

    with_highschools = forms.ChoiceField(
        choices=YES_NO_OPTIONS,
        label='Only Send Completed Records',
        required=False,
        widget=forms.Select(attrs={
            'disabled': True
        })
    )
    
    not_sent_to_sis = forms.ChoiceField(
        choices=YES_NO_OPTIONS,
        label='Only Send "Not Sent to SIS" Records',
        required=True
    )

    mark_as_sent = forms.ChoiceField(
        choices=YES_NO_SELECT_OPTIONS,
        label='Mark Records as Sent to SIS',
        required=False
    )

    send_to_slate = forms.ChoiceField(
        choices=YES_NO_SELECT_OPTIONS,
        label='Send To Slate',
        required=False,
        help_text=''
    )

    roles = []
    request = None

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request

        self.helper = FormHelper()
        self.helper.attrs = {'target': '_blank'}
        self.helper.form_method = 'POST'

        # for cis users only show their campus
        if self.request:
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )
        
        self.helper.add_input(Submit('submit', 'Generate Export'))


    def get_result(self, data):
        # Export only students in the 'pending' lifecycle state (highschool
        # assigned, not yet sent to SIS). run() flips them to 'in_review' when
        # mark_as_sent=1 so subsequent runs skip them. See commit 5391fba.
        records = Student.objects.select_related(
            'user',
            'highschool'
        ).filter(
            application_status='pending'
        )

        return records

    def run_task(self, data):
        records = self.get_result(data)

    @staticmethod
    def _export_yes_no(value):
        if value in [True, "True", "true", 1, "1", "Yes", "YES"]:
            return "Yes"
        if value in [False, "False", "false", 0, "0", "No", "NO"]:
            return "No"
        return ""

    @staticmethod
    def _export_date(value):
        if not value:
            return ""
        return value.strftime("%m/%d/%Y")

    @staticmethod
    def _export_datetime(value):
        if not value:
            return ""
        return value.strftime("%m/%d/%Y %I:%M:%S %p")

    @staticmethod
    def _export_phone(value):
        if not value:
            return ""
        digits = re.sub(r"[^0-9]", "", str(value))
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) == 10:
            return f"1{digits[0:3]}{digits[3:6]}{digits[6:10]}"
        return str(value)

    def _country_name(self, value):
        if not value:
            return ""
        code = str(value).upper()
        return self.COUNTRY_CODE_TO_NAME.get(code, value)

    def _state_name(self, value):
        if not value:
            return ""
        state_value = str(value).strip().upper()
        if state_value in self.STATE_CODES:
            return state_value
        return str(value).strip()

    def _value_for_field(self, record, key, imported_at):
        if key == "export_created":
            return self._export_datetime(record.user.created_at)
        if key == "export_imported":
            return self._export_datetime(imported_at)
        if key == "export_canusia_app_id":
            return str(record.id)
        if key == "export_canusia_person_id":
            return str(record.user.id)
        if key == "export_application_submit_date":
            return self._export_date(record.user.created_at)
        if key == "export_start_term":
            return record.start_term or ""
        # if key == "export_banner_id":
        #     return record.user.psid or ""
        if key == "export_first_name":
            return record.user.first_name or ""
        if key == "export_preferred_first_name":
            return record.preferred_name or ""
        if key == "export_last_name":
            return record.user.last_name or ""
        if key == "export_date_of_birth":
            return self._export_date(record.user.date_of_birth)
        if key == "export_sex":
            legal_sex = (record.meta or {}).get("legal_sex", "")
            if legal_sex == "m":
                return "Male"
            if legal_sex == "f":
                return "Female"
            return ""
        if key == "export_email_address":
            return record.user.email or ""
        if key == "export_preferred_phone":
            return (record.meta or {}).get("preferred_phone", "") or ""
        if key == "export_preferred_phone_number":
            preferred_phone = (record.meta or {}).get("preferred_phone", "")
            raw_phone = record.user.primary_phone if preferred_phone == "Mobile" else record.user.secondary_phone
            return self._export_phone(raw_phone)
        if key == "export_permanent_address1":
            return record.user.address1 or ""
        if key == "export_permanent_address2":
            return record.user.address2 or ""
        if key == "export_permanent_city":
            return record.user.city or ""
        if key == "export_permanent_state":
            return self._state_name(record.user.state)
        if key == "export_permanent_zip":
            return record.user.postal_code or ""
        if key == "export_permanent_country":
            return (record.user.country or "").upper()
        if key == "export_mailing_address1":
            return getattr(record, "mailing_address", "") or ""
        if key == "export_mailing_address2":
            return getattr(record, "mailing_address2", "") or ""
        if key == "export_mailing_city":
            return getattr(record, "mailing_city", "") or ""
        if key == "export_mailing_state":
            return self._state_name(getattr(record, "mailing_state", "") or "")
        if key == "export_mailing_zip":
            return getattr(record, "mailing_zip_code", "") or ""
        if key == "export_mailing_country":
            mailing_country = getattr(record, "mailing_country", "") or ""
            return str(mailing_country).upper() if mailing_country else ""
        if key == "export_parent_first_name":
            return getattr(record, "parent_first_name", "") or ""
        if key == "export_parent_last_name":
            return getattr(record, "parent_last_name", "") or ""
        if key == "export_parent_email":
            return getattr(record, "parent_email", "") or ""
        if key == "export_contact_type":
            return (record.meta or {}).get("parent_guardian_type", "") or ""
        if key == "export_hispanic_latino":
            return self._export_yes_no(record.hispanic)
        if key == "export_race":
            if not record.ethnicity:
                return ""
            labels = []
            for option_key, label in record.ETHNICITY_OPTIONS:
                if str(option_key) in record.ethnicity:
                    labels.append(label)
            return ", ".join(labels)
        if key == "export_birth_country":
            return record.user.country_of_birth
        if key == "export_primary_citizenship_information":
            return self._country_name((record.meta or {}).get("primary_citizenship"))
        if key == "export_ssn":
            return record.user.ssn_sexy
        if key == "export_school_lookup":
            if not record.highschool:
                return ""
            return record.highschool.code or ""
        if key == "export_graduation_date":
            if not record.graduation_date:
                return ""
            return record.graduation_date.strftime("%m/%d/%Y")
        if key == "export_start_date":
            # HS start date from student.meta; export as mm/dd/yyyy (same as graduation_date).
            raw = (record.meta or {}).get("start_date")
            if not raw:
                return ""
            from datetime import date, datetime
            if isinstance(raw, (date, datetime)):
                return raw.strftime("%m/%d/%Y")
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m", "%m/%Y"):
                try:
                    return datetime.strptime(str(raw), fmt).strftime("%m/%d/%Y")
                except ValueError:
                    continue
            return str(raw)
        return ""

    def run(self, task, data):
        records = self.get_result(data)

        file_name = "student-export.csv"
        fields = {
            'export_created': 'Created',
            # 'export_imported': 'Imported',
            'export_canusia_app_id': 'Canusia App ID',
            'export_canusia_person_id': 'Canusia Person ID',
            'export_application_submit_date': 'Application Submit Date',
            'export_start_term': 'Start Term',
            'export_first_name': 'First name',
            'export_preferred_first_name': 'Prefered First Name',
            'export_last_name': 'Last name',
            'export_date_of_birth': 'Date of birth',
            'export_sex': 'Sex',
            'export_email_address': 'Email Address',
            'export_preferred_phone': 'Preferred phone',
            'export_preferred_phone_number': 'Preferred phone number',
            'export_permanent_address1': 'Permanent address - Address1',
            'export_permanent_address2': 'Permanent address - Address2',
            'export_permanent_city': 'Permanent address - City',
            'export_permanent_state': 'Permanent address - State',
            'export_permanent_zip': 'Permanent address - Zip',
            'export_permanent_country': 'Permanent address - Country',
            'export_mailing_address1': 'Mailing Address - Address1',
            'export_mailing_address2': 'Mailing Address - Address2',
            'export_mailing_city': 'Mailing Address - City',
            'export_mailing_state': 'Mailing Address - State',
            'export_mailing_zip': 'Mailing Address - Zip',
            'export_mailing_country': 'Mailing Address - Country',
            'export_parent_first_name': 'Parent First Name',
            'export_parent_last_name': 'Parent Last Name',
            'export_parent_email': 'Parent Email',
            'export_contact_type': 'Contact type',
            'export_hispanic_latino': 'Hispanic Latino',
            'export_race': 'Race',
            'export_birth_country': 'Birth country',
            'export_primary_citizenship_information': 'Primary Citizenship Information',
            'export_ssn': 'SSN',
            'export_school_lookup': 'School lookup',
            'export_graduation_date': 'Graduation date',
            'export_start_date': 'HS start date',
            
        }

        # Prefetch approved sections count to avoid N+1 queries
        student_ids = list(records.values_list('id', flat=True))
        approved_counts = dict(
            StudentRegistration.objects.filter(
                student_id__in=student_ids,
                status='approved'
            ).values('student_id').annotate(
                count=Count('id')
            ).values_list('student_id', 'count')
        )

        if data.get('send_to_slate')[0] == '1':
            from django.template import Context, Template
            from cis.settings.student_exporter import student_exporter
            from cis.utils import sftp_connect

            conf = student_exporter.from_db()

            now = timezone.localtime(timezone.now())
            file_name = Template(conf.get('path_to_file', '')).render(Context({
                'min': now.strftime("%M"),
                'hh': now.strftime("%H"),
                'mm': now.strftime("%m"),
                'dd': now.strftime("%d"),
                'yyyy': now.strftime("%Y"),
            }))
            path = file_name

            client, sftp = sftp_connect(
                host=conf.get('host_name'),
                port=conf.get('port') or 22,
                username=conf.get('username'),
                password=conf.get('password') or None,
                private_key=conf.get('private_key') or None,
            )

            stream = sftp.open(file_name, 'w')
            writer = csv.writer(stream, delimiter=',')
        else:
            stream = io.StringIO()
            writer = csv.writer(stream, delimiter=',')

        imported_at = timezone.now()
        writer.writerow(list(fields.values()))
        for record in records.iterator():
            row = []
            for key in fields.keys():
                row.append(force_str(self._value_for_field(record, key, imported_at)))

            if data.get('mark_as_sent')[0] == '1':
                record.sis_sent_on = timezone.now()
                record.application_status = 'in_review'
                record.save(update_fields=['sis_sent_on', 'application_status'])
                record.add_note(None, 'Application sent to SIS')

            writer.writerow(row)
        
        if data.get('send_to_slate')[0] != '1':
            path = "reports/" + str(task.id) + "/" + file_name
            media_storage = PrivateMediaStorage()

            path = media_storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
            path = media_storage.url(path)

            return path
        else:
            # `records` filters on application_status='pending', but the loop
            # above flips every exported record to 'in_review' when
            # mark_as_sent=1, so records.count() re-queries and returns 0.
            # student_ids was materialized before the loop — use its length.
            return (len(student_ids), path)

    def run_report(self):
        ...