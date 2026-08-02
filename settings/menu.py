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

class SettingForm(forms.Form):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        roles = getattr(settings, "MY_CE")['roles']
        for role_name, role_info in roles.items():
            self.fields[
                f'{role_name}_menu'
            ] = forms.CharField(
                widget=forms.Textarea,
                help_text=f'',
                label=role_info['nice_name'] + ' Menu'
            )

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        result = {}
        for key, value in self.cleaned_data.items():
            result[key] = value
        
        return result

class menu(SettingForm):
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
        from cis.settings.menu import menu as portal_lang

        if field_name in ['home_blurb']:
            template = 'student/dashboard.html',
        elif field_name in ['classes_blurb']:
            template = 'student/classes.html'
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
                'intro': portal_lang(request).from_db().get(field_name, 'Change me'),
                'announcements': [],
                'nav_items': None
            })

    def install(self):
        defaults = {"ce_menu": "[\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-tachometer-alt\",\r\n      \"name\":\"dashboard\",\r\n      \"label\":\"Dashboard\",\r\n      \"url\":\"cis:dashboard\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-user\",\r\n      \"label\":\"Announcements\",\r\n      \"name\":\"announcements\",\r\n      \"sub_menu\":[\r\n         {\r\n            \"label\":\"All\",\r\n            \"name\":\"all\",\r\n            \"url\":\"announcements:all\"\r\n         },\r\n         {\r\n            \"label\":\"Bulk Messages\",\r\n            \"name\":\"bulk_messages\",\r\n            \"url\":\"announcements:bulk_messages\"\r\n         },\r\n         {\r\n            \"label\":\"Bulk Message Logs\",\r\n            \"name\":\"bulk_message_logs\",\r\n            \"url\":\"announcements:bulk_message_logs\"\r\n         }\r\n      ]\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-user\",\r\n      \"label\":\"Degree Pathways\",\r\n      \"name\":\"degree_pathways\",\r\n      \"sub_menu\":[\r\n         {\r\n            \"label\":\"All Pathways\",\r\n            \"name\":\"degree_pathways\",\r\n            \"url\":\"academic_plan_ce:degree_pathways\"\r\n         },\r\n         {\r\n            \"label\":\"Areas of Interest\",\r\n            \"name\":\"areas_of_interest\",\r\n            \"url\":\"academic_plan_ce:areas_of_interest\"\r\n         },\r\n         {\r\n            \"label\":\"Academic Plans\",\r\n            \"name\":\"academic_plans\",\r\n            \"url\":\"academic_plan_ce:academic_plans\"\r\n         }\r\n      ]\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-user\",\r\n      \"label\":\"Students\",\r\n      \"name\":\"students\",\r\n      \"sub_menu\":[\r\n         {\r\n            \"label\":\"All Students\",\r\n            \"name\":\"students\",\r\n            \"url\":\"cis:students\"\r\n         },\r\n         {\r\n            \"label\":\"Recommendations\",\r\n            \"name\":\"recommendations\",\r\n            \"url\":\"cis:recommendations\"\r\n         },\r\n         {\r\n            \"label\":\"Certs. Of Residence\",\r\n            \"name\":\"support_docs\",\r\n            \"url\":\"cis:support_docs\"\r\n         },\r\n         {\r\n            \"label\":\"Registrations\",\r\n            \"name\":\"registrations\",\r\n            \"url\":\"cis:registrations\"\r\n         },\r\n         {\r\n            \"label\":\"Transactions\",\r\n            \"name\":\"transactions\",\r\n            \"url\":\"student_transactions:index\"\r\n         },\r\n         {\r\n            \"label\":\"Drop/WD Requests\",\r\n            \"name\":\"drop_wd_requests\",\r\n            \"url\":\"ce_drop_wd:requests\"\r\n         },\r\n         {\r\n            \"label\":\"Notes\",\r\n            \"name\":\"notes\",\r\n            \"url\":\"cis:students_notes\"\r\n         },\r\n         {\r\n            \"label\":\"SIS Messages\",\r\n            \"name\":\"sis_messages\",\r\n            \"url\":\"cis:sis_messages\"\r\n         },\r\n         {\r\n            \"label\":\"SIS Logs\",\r\n            \"name\":\"sis_logs\",\r\n            \"url\":\"cis:sis_logs\"\r\n         }\r\n      ]\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-vihara\",\r\n      \"label\":\"Campus\",\r\n      \"name\":\"campus\",\r\n      \"sub_menu\":[\r\n         {\r\n            \"label\":\"All Campus\",\r\n            \"name\":\"campuses\",\r\n            \"url\":\"cis:campuses\"\r\n         }\r\n      ]\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-vihara\",\r\n      \"label\":\"High Schools\",\r\n      \"name\":\"highschools\",\r\n      \"sub_menu\":[\r\n         {\r\n            \"label\":\"All High Schools\",\r\n            \"name\":\"all_highschools\",\r\n            \"url\":\"cis:highschools\"\r\n         },\r\n         {\r\n            \"label\":\"School Admin.\",\r\n            \"name\":\"school_administrators\",\r\n            \"url\":\"cis:hs_admins\"\r\n         },\r\n         {\r\n            \"label\":\"Access Requests\",\r\n            \"name\":\"access_requests\",\r\n            \"url\":\"cis:hs_admin_access_requests\"\r\n         },\r\n         {\r\n            \"label\":\"Admin. Roles\",\r\n            \"name\":\"school_roles\",\r\n            \"url\":\"cis:hs_roles\"\r\n         },\r\n         {\r\n            \"label\":\"All Districts\",\r\n            \"name\":\"all_districts\",\r\n            \"url\":\"cis:districts\"\r\n         }\r\n      ]\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-align-left\",\r\n      \"label\":\"Classes\",\r\n      \"name\":\"classes\",\r\n      \"sub_menu\":[\r\n         {\r\n            \"label\":\"Sections\",\r\n            \"name\":\"sections\",\r\n            \"url\":\"cis:sections\"\r\n         },\r\n         {\r\n            \"label\":\"Course Projections\",\r\n            \"name\":\"future_sections\",\r\n            \"url\":\"cis:future_sections\"\r\n         },\r\n         {\r\n            \"label\":\"Class Visits/Reports\",\r\n            \"name\":\"class_visits\",\r\n            \"url\":\"class_visit:visits\"\r\n         },\r\n         {\r\n            \"type\":\"nav-item\",\r\n            \"icon\":\"fas fa-fw fa-box\",\r\n            \"name\":\"course_search\",\r\n            \"label\":\"Course Search\",\r\n            \"url\":\"cis:course_search\"\r\n         },\r\n         {\r\n            \"label\":\"\",\r\n            \"type\":\"separator\"\r\n         },\r\n         {\r\n            \"label\":\"Courses\",\r\n            \"name\":\"courses\",\r\n            \"url\":\"cis:courses\"\r\n         },\r\n         {\r\n            \"label\":\"Subjects\",\r\n            \"name\":\"cohorts\",\r\n            \"url\":\"cis:cohorts\"\r\n         },\r\n         {\r\n            \"label\":\"\",\r\n            \"type\":\"separator\"\r\n         },\r\n         {\r\n            \"label\":\"Academic Years\",\r\n            \"name\":\"academic_years\",\r\n            \"url\":\"cis:academic_years\"\r\n         },\r\n         {\r\n            \"label\":\"Terms\",\r\n            \"name\":\"terms\",\r\n            \"url\":\"cis:terms\"\r\n         }\r\n      ]\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-user-shield\",\r\n      \"label\":\"Instructors\",\r\n      \"name\":\"instructors\",\r\n      \"sub_menu\":[\r\n         {\r\n            \"label\":\"All Instructors\",\r\n            \"name\":\"instructors\",\r\n            \"url\":\"cis:instructors\"\r\n         },\r\n         {\r\n            \"label\":\"Instructor Applicants\",\r\n            \"name\":\"all_applicants\",\r\n            \"url\":\"cis:teacher_applications\"\r\n         },\r\n         {\r\n            \"label\":\"Teacher Course Certificates\",\r\n            \"name\":\"credentials\",\r\n            \"url\":\"cis:credentials\"\r\n         }\r\n      ]\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-users\",\r\n      \"label\":\"Faculty\",\r\n      \"name\":\"fac_coords\",\r\n      \"url\":\"cis:faculty_coordinators\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-box\",\r\n      \"label\":\"Events\",\r\n      \"name\":\"events\",\r\n      \"sub_menu\":[\r\n         {\r\n            \"label\":\"Events\",\r\n            \"name\":\"event_list\",\r\n            \"url\":\"pd_event:events\"\r\n         },\r\n         {\r\n            \"label\":\"Event Types\",\r\n            \"name\":\"event_types\",\r\n            \"url\":\"pd_event:event_types\"\r\n         }\r\n      ]\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-file-alt\",\r\n      \"name\":\"reports\",\r\n      \"label\":\"Reports\",\r\n      \"url\":\"report:reports\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-cog\",\r\n      \"name\":\"settings\",\r\n      \"label\":\"Settings\",\r\n      \"url\":\"setting:records\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-folder\",\r\n      \"label\":\"Documents\",\r\n      \"name\":\"docrepo\",\r\n      \"url\":\"docrepo:all\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-users\",\r\n      \"label\":\"Staff\",\r\n      \"name\":\"users\",\r\n      \"sub_menu\":[\r\n         {\r\n            \"label\":\"All Staff\",\r\n            \"name\":\"users\",\r\n            \"url\":\"cis:users\"\r\n         },\r\n         {\r\n            \"label\":\"Scheduled Tasks\",\r\n            \"name\":\"cron\",\r\n            \"url\":\"cis:cronlog\"\r\n         }\r\n      ]\r\n   }\r\n]", "faculty_menu": "[\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-tachometer-alt\",\r\n      \"name\":\"home\",\r\n      \"label\":\"Home\",\r\n      \"url\":\"faculty:dashboard\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-users\",\r\n      \"name\":\"teachers\",\r\n      \"image\":\"icn-adjunct-teacher.svg\",\r\n      \"label\":\"View All Teachers\",\r\n      \"url\":\"faculty:teachers\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-route\",\r\n      \"label\":\"Class Observations\",\r\n      \"name\":\"class_visits\",\r\n      \"url\":\"faculty_class_visit:visits\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-box\",\r\n      \"name\":\"classes\",\r\n      \"label\":\"Syllabi Review\",\r\n      \"url\":\"faculty:classes\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-box\",\r\n      \"label\":\"Teacher Applications\",\r\n      \"name\":\"applications\",\r\n      \"url\":\"faculty:applications\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-file-alt\",\r\n      \"name\":\"syllabi_templates\",\r\n      \"image\":\"icn-course-syllabi.svg\",\r\n      \"label\":\"Course Resources\",\r\n      \"url\":\"faculty:syllabi_templates\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-folder\",\r\n      \"name\":\"docrepo\",\r\n      \"label\":\"Documents Library\",\r\n      \"url\":\"faculty_docrepo:docs\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-sign-out-alt\",\r\n      \"name\":\"logout\",\r\n      \"label\":\"Logout\",\r\n      \"url\":\"logout\"\r\n   }\r\n]", "speaker_menu": "123", "student_menu": "[\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-tachometer-alt\",\r\n      \"name\":\"home\",\r\n      \"label\":\"Home\",\r\n      \"url\":\"student:dashboard\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-clipboard-check\",\r\n      \"name\":\"ferpa\",\r\n      \"label\":\"FERPA Consent\",\r\n      \"url\":\"student:ferpa\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-book\",\r\n      \"name\":\"classes\",\r\n      \"label\":\"Apply for Classes\",\r\n      \"url\":\"student:classes\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-book\",\r\n      \"name\":\"degree_plan\",\r\n      \"image\":\"icn-academic-plan.svg\",\r\n      \"label\":\"My Academic Plan(s)\",\r\n      \"url\":\"academic_plan_student:step_1\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-file\",\r\n      \"name\":\"drop_wd_requests\",\r\n      \"label\":\"Drop/WD Requests\",\r\n      \"url\":\"student_drop_wd:requests\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-user\",\r\n      \"name\":\"profile\",\r\n      \"label\":\"My Profile\",\r\n      \"url\":\"student:profile\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-key\",\r\n      \"name\":\"manage_password\",\r\n      \"label\":\"Manage Password\",\r\n      \"url\":\"student:manage_password\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-sign-out-alt\",\r\n      \"name\":\"logout\",\r\n      \"label\":\"Logout\",\r\n      \"url\":\"logout\"\r\n   }\r\n]", "applicant_menu": "[\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-tachometer-alt\",\r\n      \"name\":\"home\",\r\n      \"label\":\"Home\",\r\n      \"url\":\"instructor_app:dashboard\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-box\",\r\n      \"label\":\"Manage Application\",\r\n      \"name\":\"manage_app\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-user\",\r\n      \"name\":\"profile\",\r\n      \"label\":\"My Profile\",\r\n      \"url\":\"instructor_app:profile\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-key\",\r\n      \"name\":\"manage_password\",\r\n      \"label\":\"Manage Password\",\r\n      \"url\":\"instructor_app:manage_password\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-sign-out-alt\",\r\n      \"name\":\"logout\",\r\n      \"label\":\"Logout\",\r\n      \"url\":\"logout\"\r\n   }\r\n]", "instructor_menu": "[\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-tachometer-alt\",\r\n      \"name\":\"home\",\r\n      \"label\":\"Home\",\r\n      \"url\":\"instructor:dashboard\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-box\",\r\n      \"name\":\"classes\",\r\n      \"sub_menu\":[\r\n         {\r\n            \"label\":\"All My Classes\",\r\n            \"name\":\"classes\",\r\n            \"url\":\"instructor:classes\"\r\n         },\r\n         {\r\n            \"label\":\"Class Section\",\r\n            \"name\":\"class\"\r\n         }\r\n      ],\r\n      \"label\":\"Class Section(s)\",\r\n      \"url\":\"instructor:classes\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-users\",\r\n      \"label\":\"My Students\",\r\n      \"name\":\"students\",\r\n      \"url\":\"instructor:students\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-certificate\",\r\n      \"name\":\"certificates\",\r\n      \"label\":\"My Certificates\",\r\n      \"url\":\"instructor:certificates\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-file\",\r\n      \"name\":\"drop_wd_requests\",\r\n      \"label\":\"Drop/WD Requests\",\r\n      \"url\":\"instructor_drop_wd:requests\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-file\",\r\n      \"name\":\"uploads\",\r\n      \"label\":\"My Files\",\r\n      \"url\":\"instructor:uploads\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-file-alt\",\r\n      \"name\":\"course_resources\",\r\n      \"label\":\"Course Resources\",\r\n      \"url\":\"instructor:course_resources\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-folder\",\r\n      \"name\":\"docrepo\",\r\n      \"label\":\"Shared Docs.\",\r\n      \"url\":\"instructor_docrepo:docs\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-sign-out-alt\",\r\n      \"name\":\"logout\",\r\n      \"label\":\"Logout\",\r\n      \"url\":\"logout\"\r\n   }\r\n]", "district_admin_menu": "123", "highschool_admin_menu": "[\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-tachometer-alt\",\r\n      \"name\":\"home\",\r\n      \"label\":\"Home\",\r\n      \"url\":\"highschool_admin:dashboard\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-user\",\r\n      \"label\":\"Students\",\r\n      \"name\":\"students\",\r\n      \"url\":\"highschool_admin:students\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-file-upload\",\r\n      \"label\":\"Import Students\",\r\n      \"name\":\"student_import\",\r\n      \"url\":\"highschool_admin:student_import\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-user-plus\",\r\n      \"label\":\"Bulk Enroll\",\r\n      \"name\":\"bulk_enroll\",\r\n      \"url\":\"highschool_admin:bulk_enroll\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-edit\",\r\n      \"label\":\"Student Notes\",\r\n      \"name\":\"notes\",\r\n      \"url\":\"highschool_admin:student_notes\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-file\",\r\n      \"name\":\"transcripts\",\r\n      \"label\":\"Transcripts\",\r\n      \"url\":\"highschool_admin:transcripts\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-file\",\r\n      \"name\":\"section_requests\",\r\n      \"label\":\"Course Projections\",\r\n      \"url\":\"highschool_admin:section_requests\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-certificate\",\r\n      \"name\":\"certificates\",\r\n      \"label\":\"Course Certificates\",\r\n      \"url\":\"highschool_admin:certificates\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-file\",\r\n      \"name\":\"drop_wd_requests\",\r\n      \"label\":\"Drop/WD Requests\",\r\n      \"url\":\"highschool_admin_drop_wd:requests\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-file-alt\",\r\n      \"name\":\"reports\",\r\n      \"label\":\"Reports\",\r\n      \"url\":\"highschool_admin_report:reports\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-users\",\r\n      \"name\":\"administrators\",\r\n      \"label\":\"School Personnel\",\r\n      \"url\":\"highschool_admin:personnel\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-key\",\r\n      \"name\":\"manage_password\",\r\n      \"label\":\"Manage Password\",\r\n      \"url\":\"highschool_admin:manage_password\"\r\n   },\r\n   {\r\n      \"type\":\"nav-item\",\r\n      \"icon\":\"fas fa-fw fa-sign-out-alt\",\r\n      \"name\":\"logout\",\r\n      \"label\":\"Logout\",\r\n      \"url\":\"logout\"\r\n   }\r\n]"}

        try:
            setting = Setting.objects.get(key=self.key)
        except Setting.DoesNotExist:
            setting = Setting()
            setting.key = self.key

        # Inject support-ticket nav entries into each role's default menu so
        # fresh tenants (where the data migration is a no-op) also get them.
        _support_entries = {
            "ce_menu": {
                "type": "nav-item",
                "icon": "fas fa-fw fa-ticket-alt",
                "name": "support_reqs",
                "label": "Support Requests",
                "sub_menu": [
                    {"label": "All Requests", "name": "all_requests", "url": "support_ticket:requests"},
                    {"label": "Summary",      "name": "summary",      "url": "support_ticket:summary"},
                    {"label": "Manage Types", "name": "types",        "url": "support_ticket:types"},
                ],
            },
            "student_menu": {
                "type": "nav-item",
                "icon": "fas fa-fw fa-question-circle",
                "name": "support",
                "label": "Support Requests",
                "url": "student_support_ticket:requests",
            },
            "instructor_menu": {
                "type": "nav-item",
                "icon": "fas fa-fw fa-question-circle",
                "name": "support",
                "label": "Support Requests",
                "url": "instructor_support_ticket:requests",
            },
            "highschool_admin_menu": {
                "type": "nav-item",
                "icon": "fas fa-fw fa-question-circle",
                "name": "support",
                "label": "Support Requests",
                "url": "hs_admin_support_ticket:requests",
            },
        }
        for role_key, entry in _support_entries.items():
            if role_key in defaults:
                items = json.loads(defaults[role_key])
                if not any(i.get("name") == entry["name"] for i in items):
                    items.append(entry)
                defaults[role_key] = json.dumps(items)

        setting.value = defaults
        setting.save()

    @classmethod
    def from_db(cls):

        try:
            setting = Setting.objects.get(key=cls.key)
            # print(setting.value)
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
