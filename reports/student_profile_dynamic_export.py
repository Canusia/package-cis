import csv
import datetime
import io

from django import forms
from django.core.files.base import ContentFile
from django.db.models import Min
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.html import strip_tags
from django.utils.translation import gettext as _

from cis.backends.storage_backend import PrivateMediaStorage
from cis.campus_gate import get_accessible_campuses, scope_report_by_campus
from cis.forms.student_profile import StudentProfileForm
from cis.models.course import Campus
from cis.models.student import Student
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit


def _widget_is_effectively_hidden(widget):
    """True if this field should not appear in tester-facing CSV (HiddenInput UI)."""
    if widget is None:
        return False
    if isinstance(widget, forms.HiddenInput):
        return True
    if isinstance(widget, forms.MultiWidget):
        sub = getattr(widget, "widgets", None) or []
        if not sub:
            return False
        return all(_widget_is_effectively_hidden(w) for w in sub)
    return False


class student_profile_dynamic_export(forms.Form):
    campus = forms.ModelMultipleChoiceField(
        queryset=Campus.objects.none(), required=True, label='Campus',
    )

    created_on = forms.DateField(
        required=True,
        label="Created Account On and After",
        widget=forms.DateInput(
            format="%m/%d/%Y",
            attrs={
                "class": "col-md-6 col-sm-12 dateinput",
                "placeholder": "mm/dd/yyyy",
                "autocomplete": "off",
            },
        ),
    )

    created_until = forms.DateField(
        required=True,
        label="Created Account Until",
        widget=forms.DateInput(
            format="%m/%d/%Y",
            attrs={
                "class": "col-md-6 col-sm-12 dateinput",
                "placeholder": "mm/dd/yyyy",
                "autocomplete": "off",
            },
        ),
    )

    roles = []
    request = None

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request

        self.helper = FormHelper()
        self.helper.form_method = "POST"
        self.helper.add_input(Submit("submit", "Generate Export"))
        self._configure_date_defaults()

        if self.request:
            self.fields["campus"].queryset = get_accessible_campuses(
                self.request.user
            )
            self.helper.form_action = reverse_lazy(
                "report:run_report", args=[request.GET.get("report_id")]
            )

    def _configure_date_defaults(self):
        bounds = Student.objects.aggregate(oldest=Min("user__created_at"))
        oldest_dt = bounds.get("oldest")
        today = timezone.localdate()

        if oldest_dt:
            oldest_date = timezone.localtime(oldest_dt).date()
        else:
            oldest_date = today

        self.fields["created_on"].initial = oldest_date
        self.fields["created_until"].initial = today

        if oldest_dt:
            self.fields["created_on"].help_text = _(
                "The oldest student in the database was created on: %(date)s"
            ) % {"date": oldest_date.strftime("%m/%d/%Y")}
        else:
            self.fields["created_on"].help_text = _(
                "There are no student accounts in the database yet."
            )

    def _parse_date_input(self, value):
        if isinstance(value, datetime.date):
            return value

        if isinstance(value, list):
            value = value[0] if value else None

        if not value:
            return None

        value = str(value).strip()
        for date_format in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                return datetime.datetime.strptime(value, date_format).date()
            except ValueError:
                continue
        return None

    def _form_fields_for_export(self):
        form = StudentProfileForm(student=None, request=self.request)
        export_fields = []
        valid_targets = {"user", "student", "meta"}

        for field_name, field in form.fields.items():
            target = getattr(field, "storage_target", None)
            if target not in valid_targets:
                continue
            if _widget_is_effectively_hidden(field.widget):
                continue

            path = getattr(field, "storage_path", None) or field_name
            header = strip_tags(force_str(field.label or field_name)).strip() or field_name
            export_fields.append(
                {
                    "name": field_name,
                    "target": target,
                    "path": path,
                    "header": header,
                }
            )
        return export_fields

    def _value_for_field(self, record, field_meta):
        target = field_meta["target"]
        path = field_meta["path"]

        if target == "user":
            val = getattr(record.user, path, "")
        elif target == "student":
            val = getattr(record, path, "")
        elif target == "meta":
            val = (record.meta or {}).get(path, "")
        else:
            val = ""
        if val is None:
            return ""
        return val

    def get_result(self, data, user=None):
        created_on = self._parse_date_input(data.get("created_on"))
        created_until = self._parse_date_input(data.get("created_until"))

        if not created_on or not created_until:
            return Student.objects.none()

        start_dt = timezone.make_aware(
            datetime.datetime.combine(created_on, datetime.time.min),
            timezone.get_current_timezone(),
        )
        until_exclusive = created_until + datetime.timedelta(days=1)
        end_dt = timezone.make_aware(
            datetime.datetime.combine(until_exclusive, datetime.time.min),
            timezone.get_current_timezone(),
        )

        records = Student.objects.select_related("user", "highschool").filter(
            user__created_at__gte=start_dt,
            user__created_at__lt=end_dt,
        )

        records = scope_report_by_campus(
            records, user, data.get("campus"),
            campus_path="studentregistration__class_section__course__campus",
            distinct=True,
        )

        return records

    def run(self, task, data):
        records = self.get_result(data, user=getattr(task, "created_by", None))
        fields = self._form_fields_for_export()

        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=",")

        writer.writerow([field["header"] for field in fields])
        for record in records.iterator():
            row = []
            for field in fields:
                row.append(force_str(self._value_for_field(record, field)))
            writer.writerow(row)

        file_name = "student-profile-form-export.csv"
        now = timezone.localtime(timezone.now()).strftime("%Y/%m")
        path = f"reports/{now}/{task.id}/{file_name}"
        media_storage = PrivateMediaStorage()
        path = media_storage.save(path, ContentFile(stream.getvalue().encode("utf-8")))
        return media_storage.url(path)

    def run_report(self):
        ...
