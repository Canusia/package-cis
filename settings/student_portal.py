import json
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError

from django_ckeditor_5.widgets import CKEditor5Widget as CKEditorWidget

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from ..models.term import Term, AcademicYear
from ..models.settings import Setting

class SettingForm(forms.Form):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        import json
        from cis.settings.menu import menu as menu_settings
        
        role_name = 'student'
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
                        # widget=CKEditorWidget(
                        #     # attrs={"class": "django_ckeditor_5"}
                        # ),
                        help_text=f'Displayed at the top of {sub_menu["label"]} page',
                        label=sub_menu['label']
                    )
            else:        
                self.fields[
                    f'{menu_item["name"]}_blurb'
                ] = forms.CharField(
                    widget=forms.Textarea,
                    # widget=CKEditorWidget(
                    #     attrs={"class": "django_ckeditor_5"}
                    # ),
                    help_text=f'Displayed at the top of {menu_item["label"]} page. <a href="#" class="float-right" onClick="do_bulk_action(\'student_portal\', \'{menu_item["name"]}_blurb\')" >See Preview</a>',
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

class student_portal(SettingForm):
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
        from cis.settings.student_portal import student_portal as portal_lang

        template = 'student/dashboard.html',

        from django.template import Context, Template
        template = Template(portal_lang(request).from_db().get(field_name, 'Change me'))
        context = Context({
            'request': request
        })
        intro = template.render(context)

        if field_name in ['home_blurb']:
            template = 'student/dashboard.html',
        elif field_name in ['classes_blurb']:
            template = 'student/classes.html'
        elif field_name in ['grades_blurb']:
            template = 'student/grades.html'
        elif field_name in ['degree_plan_blurb']:
            template = 'degree_plan/student/index.html'
        elif field_name in ['ferpa_blurb']:
            from cis.services.tenant_services import get_tenant_service
            template = get_tenant_service('ferpa_form').form_template()
        elif field_name in ['parent_consent_blurb']:
            template = 'student/parent_consent.html'
        elif field_name in ['profile_blurb']:
            template = 'student/profile.html'
        elif field_name in ['manage_password_blurb']:
            template = 'student/manage_password.html'
        return render(
            request,
            template,
            {
                'menu': None,
                'form': '',
                'intro': intro,
                'announcements': [],
                'nav_items': None
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
