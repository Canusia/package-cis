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

from cis.menu import FACULTY_MENU as PORTAL_PAGES

class SettingForm(forms.Form):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        import json
        from cis.settings.menu import menu as menu_settings
        
        role_name = 'faculty'
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
                        help_text=f'Displayed at the top of {sub_menu["label"]} page',
                        label=sub_menu['label']
                    )
            else:        
                self.fields[
                    f'{menu_item["name"]}_blurb'
                ] = forms.CharField(
                    widget=forms.Textarea,
                    help_text=f'Displayed at the top of {menu_item["label"]} page. <a href="#" class="float-right" onClick="do_bulk_action(\'faculty_portal\', \'{menu_item["name"]}_blurb\')" >See Preview</a>',
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

class faculty_portal(SettingForm):
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
        from cis.settings.faculty_portal import faculty_portal as portal_lang

        
        if field_name in ['classes_blurb']:
            template = 'schedule/faculty/visits.html'
            return render(
                request,
                'faculty/classes.html',
                {
                    'page_title': 'Class Sections',
                    'urls': {},
                    'menu': None,
                    'intro': portal_lang(request).from_db().get('classes_blurb', 'Change me'),
                    'class_sections_api': '/ce/api/class_section?format=datatables',
                    'academic_years': AcademicYear.objects.all().order_by('-name'),
                    'active_academic_year': None,
                })
        elif field_name in ['class_visits_blurb']:
            template = 'schedule/faculty/visits.html'
            return render(
                request,
                template, {
                    'menu': None,
                    'terms': None,
                    'active_term': None,
                    'courses': Course.objects.all(),
                    'visitors': None,
                    'page_title': 'Scheduled Class Visits',
                    'api_url': '/faculty/class_visits/api/visit_schedule/?format=datatables',
                    'intro': portal_lang(request).from_db().get('class_visits_blurb', 'Change me'),
                    'class_sections_api_url': '/faculty/class_visits/api/class_sections/?format=datatables',
                }
            )
        elif field_name in ['applications_blurb']:
            from cis.models.teacher_applicant import ApplicantSchoolCourse
            
            template = 'faculty/applications.html'
            return render(
                request,
                template, {
                    'page_title': 'Teacher Applications',
                    'menu': None,
                    'status': None,
                    'course_status': ApplicantSchoolCourse.STATUS_OPTIONS,
                    'intro': portal_lang(request).from_db().get('applications_blurb', 'Change me'),
                    'cohorts': Cohort.objects.filter().order_by('designator'),
                    'api_url': '/ce/api/teacher_application?format=datatables'
                }
            )
        elif field_name in ['home_blurb']:
            return render(
                request,
                'faculty/dashboard.html',
                {
                    'app_status': None,
                    'active_status': None,
                    'announcements': [],
                    'applications': [],
                    'intro': self.from_db().get('home_blurb', 'Change me'),
                    'nav_items': []
                })

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
