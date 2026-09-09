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

class SettingForm(forms.Form):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        from cis.menu import get_role_menu

        # Only visible menu items get a blurb field. Text already stored for a
        # hidden item is left untouched by run_record().
        menu = get_role_menu('highschool_admin')

        menu.append({
            'name': 'side_bar',
            'label': 'Sidebar on Dashboard'
        })
        
        menu.append({
            'name': 'student',
            'label': 'Student Page'
        })
        
        for menu_item in menu:
            if menu_item.get('name') == 'logout':
                continue

            if menu_item.get('sub_menu'):
                for sub_menu in menu_item.get('sub_menu'):
                    self.fields[
                        f'{sub_menu["name"]}_blurb'
                    ] = forms.CharField(
                        widget=forms.Textarea,
                        help_text=f'Displayed at the top of {sub_menu["label"]} page',
                        label=sub_menu['label']
                    )
            else:        
                self.fields[
                    f'{menu_item["name"]}_blurb'
                ] = forms.CharField(
                    widget=forms.Textarea,
                    help_text=f'Displayed at the top of {menu_item["label"]} page. <a href="#" class="float-right" onClick="do_bulk_action(\'highschool_admin_portal\', \'{menu_item["name"]}_blurb\')" >See Preview</a>',
                    label=menu_item['label']
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
        from django.shortcuts import (
            render
        )
        from django.conf import settings

        from cis.models.student import Student
        from cis.models.term import AcademicYear
        from cis.models.course import Cohort, Course
        from cis.forms.student import StudentForm
        from cis.settings.highschool_admin_portal import highschool_admin_portal as portal_lang

        if field_name in ['home_blurb']:
            template = 'highschool_admin/dashboard.html'
        elif field_name in ['students_blurb']:
            template = 'highschool_admin/students.html'
        elif field_name in ['notes_blurb']:
            template = 'highschool_admin/student_notes.html'
        elif field_name in ['transcripts_blurb']:
            template = 'highschool_admin/transcripts.html'
        elif field_name in ['section_requests_blurb']:
            template = 'highschool_admin/section_requests.html'
        elif field_name in ['reports_blurb']:
            template = 'reports/index.html'
        elif field_name in ['administrators_blurb']:
            template = 'highschool_admin/personnel.html'
        elif field_name in ['manage_password_blurb']:
            template = 'highschool_admin/manage_password.html'
        return render(
            request,
            template,
            {
                'menu': None,
                'pending_applications': [],
                'form': '',
                'intro': portal_lang(request).from_db().get(field_name, 'Change me'),
                'announcements': [],
                'nav_items': None
            })

    def install(self):
        defaults = {
            'dashboard_blurb': "Change this in Settings -> HS Administrator -> Portal Language",
            'students_blurb': "Change this in Settings -> HS Administrator -> Portal Language",
            'student_notes_blurb': "Change this in Settings -> HS Administrator -> Portal Language",
            'reports_blurb': "Change this in Settings -> HS Administrator -> Portal Language",
            'school_personnel_blurb': "Change this in Settings -> HS Administrator -> Portal Language",
            'course_search_blurb': "Change this in Settings -> HS Administrator -> Portal Language"
        }

        try:
            setting = Setting.objects.get(key=self.key)
        except Setting.DoesNotExist:
            setting = Setting()
            setting.key = self.key

        setting.value = defaults
        setting.save()

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
