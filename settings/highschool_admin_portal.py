import json
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from ..models.term import Term, AcademicYear
from ..models.settings import Setting

from cis.menu import HS_ADMIN_MENU as PORTAL_PAGES

# Pages that show a blurb but have no menu item of their own.
EXTRA_BLURB_PAGES = (
    {'name': 'side_bar', 'label': 'Sidebar on Dashboard'},
    {'name': 'student', 'label': 'Student Page'},
)


def blurb_fields():
    """``[(field_name, label)]``: one ``<menu item name>_blurb`` per HS admin page.

    The single source for both the form's fields and ``preview()``, so every
    field the form shows has a preview (package-cis#111). Only visible menu
    items count; text already stored for a hidden item is left untouched by
    run_record().
    """
    from cis.menu import get_role_menu

    result = []
    for menu_item in list(get_role_menu('highschool_admin')) + list(EXTRA_BLURB_PAGES):
        if menu_item.get('name') == 'logout':
            continue
        for page in menu_item.get('sub_menu') or [menu_item]:
            result.append((f'{page["name"]}_blurb', page['label']))
    return result


class SettingForm(forms.Form):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field_name, label in blurb_fields():
            self.fields[field_name] = forms.CharField(
                widget=forms.Textarea,
                help_text=(
                    f'Displayed at the top of {label} page. '
                    f'<a href="#" class="float-right" onClick="do_bulk_action('
                    f'\'highschool_admin_portal\', \'{field_name}\')" >See Preview</a>'),
                label=label
            )

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        result = {}
        for key, value in self.cleaned_data.items():
            result[key] = value
        
        return result

class highschool_admin_portal(SettingForm):
    key = str(__name__)

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request
        self.helper = FormHelper()
        self.helper.attrs = {'target':'_blank'}
        self.helper.form_method = 'POST'
        self.helper.form_action = reverse_lazy(
            'setting:run_record', args=[request.GET.get('report_id')])
        self.helper.add_input(Submit('submit', 'Save Setting'))

    def preview(self, request, field_name):
        """Just the blurb, as it heads its page (package-cis#111).

        Any field name answers -- an unknown one gets a label derived from
        its name -- so the preview endpoint never 400s on a field the form
        builds from the tenant's menu.
        """
        from cis.services.blurb_preview import render_blurb_preview

        label = dict(blurb_fields()).get(field_name) or (
            field_name.removesuffix('_blurb').replace('_', ' ').title())
        return render_blurb_preview(request, label, self.from_db().get(field_name))

    def install(self):
        defaults = {
            'dashboard_blurb': "Change this in Settings -> HS Administrator -> Portal Language",
            'students_blurb': "Change this in Settings -> HS Administrator -> Portal Language",
            'student_notes_blurb': "Change this in Settings -> HS Administrator -> Portal Language",
            'reports_blurb': "Change this in Settings -> HS Administrator -> Portal Language",
            'school_personnel_blurb': "Change this in Settings -> HS Administrator -> Portal Language",
            'course_search_blurb': "Change this in Settings -> HS Administrator -> Portal Language"
        }

        Setting.install_defaults(self.key, defaults)

    @classmethod
    def from_db(cls):
        try:
            setting = Setting.objects.get(key=cls.key)
            return setting.value
        except Setting.DoesNotExist:
            return {}

    def run_record(self):
        try:
            setting = Setting.objects.get(key=self.key)
        except Setting.DoesNotExist:
            setting = Setting()
            setting.key = self.key

        # Merge, don't replace: a menu item hidden via its "display" flag has
        # no field in this form, and a wholesale replace would drop the blurb
        # stored for it.
        value = dict(setting.value or {})
        value.update(self._to_python())
        setting.value = value
        setting.save()

        return JsonResponse({
            'message': 'Successfully saved settings',
            'status': 'success'})
