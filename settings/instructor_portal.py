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

from cis.menu import INSTRUCTOR_MENU as PORTAL_PAGES

class SettingForm(forms.Form):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        import json
        from cis.settings.menu import menu as menu_settings
        
        role_name = 'instructor'
        conf = menu_settings.from_db()
        menu = json.loads(conf.get(f'{role_name}_menu'))

        menu.append({
            'name': 'side_bar',
            'label': 'Sidebar on Dashboard'
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
                        help_text=f'Displayed at the top of {sub_menu["label"]} page. <a href="#" class="float-right" onClick="do_bulk_action(\'instructor_portal\', \'{sub_menu["name"]}_blurb\')" >See Preview</a>',
                        label=sub_menu['label']
                    )
            else:        
                self.fields[
                    f'{menu_item["name"]}_blurb'
                ] = forms.CharField(
                    widget=forms.Textarea,
                    help_text=f'Displayed at the top of {menu_item["label"]} page. <a href="#" class="float-right" onClick="do_bulk_action(\'instructor_portal\', \'{menu_item["name"]}_blurb\')" >See Preview</a>',
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

class instructor_portal(SettingForm):
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

    def install(self):
        defaults = {
            'dashboard_blurb': "Change this in Settings -> Instructor -> Portal Language",
            'classes_blurb': "Change this in Settings -> Instructor -> Portal Language",
            'class_blurb': "Change this in Settings -> Instructor -> Portal Language",
            'documents_blurb': "Change this in Settings -> Instructor -> Portal Language"
        }

        try:
            setting = Setting.objects.get(key=self.key)
        except Setting.DoesNotExist:
            setting = Setting()
            setting.key = self.key

        setting.value = defaults
        setting.save()

    def preview(self, request, field_name):
        from django.shortcuts import (
            render
        )
        from django.conf import settings

        from cis.models.student import Student
        from cis.models.term import AcademicYear
        from cis.models.course import Cohort, Course
        from cis.forms.student import StudentForm
        from cis.settings.instructor_portal import instructor_portal as portal_lang

        if field_name in ['home_blurb']:
            template = 'instructor/dashboard.html',
        elif field_name in ['course_apps_blurb']:
            template = 'instructor/si_apps.html'
        elif field_name in ['uploads_blurb']:
            template = 'instructor/files.html'
        elif field_name in ['grades_blurb']:
            template = 'instructor/class_section_grade.html'
        elif field_name in ['drop_wd_requests_blurb']:
            template = 'drop_wd/instructor/requests.html'
        elif field_name in ['docrepo_blurb']:
            template = 'docrepo/student/index.html'
        elif field_name in ['class_blurb']:
            template = 'instructor/class_section.html'
        elif field_name in ['classes_blurb']:
            template = 'instructor/classes.html'
        return render(
            request,
            template,
            {
                'menu': None,
                'form': '',
                'intro': portal_lang(request).from_db().get(field_name, 'Change me'),
                'announcements': [],
                'nav_items': None
            })

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

        setting.value = self._to_python()
        setting.save()

        return JsonResponse({
            'message': 'Successfully saved settings',
            'status': 'success'})
