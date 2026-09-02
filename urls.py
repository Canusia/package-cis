"""
    cis URL Configuration
"""
from django.urls import path, include
from django.contrib.auth.decorators import user_passes_test

from rest_framework import routers

from cis.views.highschool import (
    index as hs_home, detail as hs_detail,
    ajax_search as hs_ajax_search, add_new as hs_add_new,
    download_transcript, download_highschool_template,
    highschool_map_data, highschool_map_courses,
    HighSchoolViewSet, HighSchoolTeacherViewSet,
    HighSchoolHistoryViewSet,
    HighSchoolAdministratorViewSet,
    HighSchoolNoteViewSet,
    HighSchoolServedByCampusViewSet,
    HighSchoolTranscriptViewSet,
    do_bulk_action as hs_bulk_actions,
    delete as delete_highschool,
    tab as highschool_tab,
)

from cis.api.student import (
    StudentSISAPI,
    StudentIDViewSet
)

from cis.views.comparison import comparison_data


from cis.views.sis_logs import (
    SIS_LogViewSet,
    detail as sis_log_details,
    index as sis_logs_index
)
from cis.views.cron import (
    CronLogViewSet,
    index as cronlog_index
)


from cis.views.teacher_application import (
    index as teacher_applications,
    detail as teacher_application,
    TeacherApplicationViewSet,
    TeacherApplicationReviewerViewSet,
    remove_upload as tapp_remove_file,
    view_approval_email,
    send_approval_email,
    remove_recommendation as tapp_remove_recommendation,
    delete_record as delete_teacher_application,
    reply_to_note as teacher_app_note_reply,
    remind_reviewer as remind_reviewer,

    delete_course as delete_teacher_course,
    download_files as download_tapp_files,
    download_as_pdf as download_tapp,
    do_action as do_teacher_app_action
)

from cis.views.district import (
    index as district_home, detail as district_detail,
    add_new as district_add_new, ajax_search as district_ajax_search,
    delete_record as delete_district,
    DistrictViewSet,
)

from cis.views.district_position import (
    index as district_role_home, add_new as district_role_add_new,
    detail as district_role_detail
)

from cis.views.district_administrator import (
    index as district_admin_home, detail as district_admin_detail,
    add_new as district_admin_add_new
)

from cis.views.hs_position import (
    index as hs_roles, add_new as hs_role_add_new,
    detail as hs_role,
    HSPositionViewSet,
    delete_record as delete_hs_position
)

from cis.views.hs_administrator import (
    index as hs_admins, detail as hs_admin,
    tab as hs_admin_tab,
    add_new as hs_admin_add_new,
    download_hs_member_template,
    delete_record as delete_hs_admin,
    delete_role as delete_hs_admin_role,
    revoke_hs_admin_role,
    access_requests as hs_admin_access_requests,
    access_request as hs_admin_access_request,
    access_request_tab,
    delete_access_request,
    do_bulk_action,
    do_person_bulk_action,
    do_dangling_bulk_action,
    HSAdministratorViewSet,
    HSAdministratorAccessRequestViewSet,
    HSAdministratorPositionViewSet,
    DanglingHSAdminViewSet
)

from cis.views.academic_year import (
    index as academic_years, detail as academic_year,
    add_new as academic_year_add_new,
    tab as academic_year_tab,
    AcademicYearViewSet,
    delete_record as delete_academic_year,
    download_academic_year_template,
    do_bulk_action as academic_year_bulk_actions,
)

from cis.views.term import (
    index as terms, detail as term, add_new as term_add_new,
    tab as term_tab,
    TermViewSet,
    delete_record as delete_term,
    download_term_template,
    do_bulk_action as term_bulk_actions,
)

from cis.views.course_category import (
    index as categories, detail as category, add_new as category_add_new
)

from cis.views.course_cohort import (
    index as cohorts, detail as cohort, add_new as cohort_add_new,
    CohortViewSet,
    delete_record as delete_cohort,
    download_cohort_template,
)

from cis.views.campus import (
    index as campuses,
    detail as campus, add_new as campus_add_new,
    CampusViewSet
)

from cis.views.tech_center_staff import (
    index as tech_center_staffs,
    detail as tech_center_staff, add_new as tech_center_staff_add_new,
    TechCenterStaffViewSet
)

from cis.views.tech_center import (
    index as tech_centers,
    detail as tech_center, add_new as tech_center_add_new,
    TechCenterViewSet
)

from cis.views.location import (
    index as locations,
    detail as location, add_new as location_add_new,
    LocationViewSet
)

from cis.views.college import (
    index as colleges, detail as college, add_new as college_add_new
)

from cis.views.department import (
    index as departments, detail as department, add_new as department_add_new
)

from cis.views.course import (
    index as courses, detail as course, add_new as course_add_new,
    tab as course_tab,
    CourseViewSet,
    CourseHistoryViewSet,
    CourseAppRequirementViewSet,
    CourseUploadViewSet,
    CourseNoteViewSet,
    delete_course_administrator_role,
    do_bulk_action as course_bulk_actions,
    delete as delete_course,
    download_course_template,
)

from cis.views.teacher import (
    index as instructors, detail as instructor,
    add_new as instructor_add_new,
    tab as instructor_tab,
    TeacherViewSet,
    delete_record as delete_teacher,
    revoke_instructor_role,
    do_bulk_action as teacher_bulk_actions,
    delete_course_certificate,
    delete_teacher_highschool,
    TeacherCourseViewSet,
    TeacherNotesViewSet,
    TeacherUploadViewSet,
    AllTeacherUploadViewSet,
    download_instructor_template,
    DanglingInstructorViewSet,
    do_dangling_bulk_action as instructor_do_dangling_bulk_action,
)

from cis.views.college_instructor import (
    index as college_instructors,
    detail as college_instructor
)


from cis.views.faculty import (
    index as faculty_coordinators,
    detail as faculty_coordinator,
    tab as faculty_coordinator_tab,
    add_new as faculty_coordinator_add_new,
    download_faculty_template,
    do_bulk_action as faculty_bulk_actions,
    FacultyViewSet,
    CourseAdministratorViewSet,
    DanglingFacultyViewSet,
    do_dangling_bulk_action as faculty_do_dangling_bulk_action,
)


# CE Future Sections - views moved to future_sections app
# ViewSets now in future_sections.urls.ce router

from cis.views.section import (
    index as sections, detail as section,
    tab as section_tab,
    course_search as course_search,
    add_new as section_add_new,
    download_section_template,
    ajax as section_ajax,
    import_from_s3 as import_sections_from_s3,
    # test_import as test_sftp,
    delete_record as delete_class_section,
    ClassSectionViewSet,
    ClassSectionHistoryViewSet,
    ClassSectionNoteViewSet,
    ClassSectionSyllabiViewSet,
    ClassesRegisteredByCampusViewSet,
    RegistrationSummaryViewSet,
    do_bulk_action as section_bulk_actions,
    delete_syllabi
)

from cis.views.settings_overview import settings_overview_page

from cis.views.student import (
    index as students, detail as student,
    tab as student_tab,
    as_pdf as student_pdf,
    add_new as student_add_new,
    mod_settings as student_settings,
    data_export_import as student_exports,
    delete_record as student_delete,
    revoke_student_role,
    delete_support_doc,
    faa_index,
    delete_faa,
    faa,
    notes as student_notes,
    delete_note as delete_student_note,
    import_from_s3 as import_students_from_s3,
    import_registrations_from_s3,
    register_for_class,
    recommendations,
    support_docs,
    support_docs_bulk_actions,
    get_student_details,
    ajax_action as student_ajax_action,
    StudentViewSet, StudentRecommendationViewSet,
    StudentAgreementViewSet, ParentConsentViewSet,
    StudentCampusIDViewSet, StudentNoteViewSet,
    StudentSupportingDocumentViewSet,
    StudentTuitionAssistanceViewSet,
    StudentHistoryViewSet,
    DanglingStudentViewSet,
    do_bulk_action as student_bulk_actions,
    do_dangling_bulk_action as student_do_dangling_bulk_action,
    student_profile_changes,
)

from cis.views.registration import (
    index as registrations,
    detail as registration,
    delete as delete_registration,
    do_bulk_action as registration_bulk_actions,
    tab as registration_tab,
    RegistrationViewSet,
    StudentRegistrationHistoryViewSet,
)

from cis.views.registration_failed_mirror import (
    failed_mirror_page,
    failed_mirror_export,
    FailedMirrorRegistrationViewSet,
)

from cis.views.registration_pending_mirror import (
    pending_mirror_page,
    PendingSisMirrorRegistrationViewSet,
)

from cis.views import credentials as credentials_views
from cis.views import student_import as student_import_views
from cis.views.credentials import (
    CredentialExpiryViewSet,
    CredentialSummaryViewSet,
)

from cis.views.drop_request import (
    index as drop_wd_reqs, detail as drop_wd_req,
    delete as delete_drop_wd_req,
    StudentDropViewSet
)

from cis.views.venue import (
    index as venues, detail as venue,
    add_new as venue_add_new
)

from cis.views.speaker import (
    index as speakers, detail as speaker,
    add_new as speaker_add_new
)

from cis.views.event import (
    index as events, detail as event,
    add_new as event_add_new,
    delete_record_from_event,
    edit_event_item
)

from cis.views.section_number import (
    index as section_numbers, detail as section_number,
    add_new as section_number_add_new,
    delete_record as delete_section_number
)

from cis.views.users import (
    index as users, detail as user,
    add_new as user_add_new
)

from cis.views.ajax import (
    add_new as add_new_ajax,
    pwd_reset_link,
    get_footer,
    get_landing_page_text
)

from cis.views.home import dashboard, export_to_excel
from cis.views.ldap_login import ldap_login

def user_has_cis_role(user):
    """
    Returns True if current user has a 'cis' role. False otherwise
    """
    if user.is_anonymous:
        return False
    
    roles = user.get_roles()
    return True if 'ce' in roles else False

app_name = 'cis'

router = routers.DefaultRouter()
router_viewsets = {
    'highschool': HighSchoolViewSet,
    'district': DistrictViewSet,
    'highschool-teacher': HighSchoolTeacherViewSet,
    'highschool-administrator': HighSchoolAdministratorViewSet,
    'highschool-note': HighSchoolNoteViewSet,
    'highschool-transcript': HighSchoolTranscriptViewSet,
    'highschool-history': HighSchoolHistoryViewSet,

    'hs-administrator': HSAdministratorViewSet,
    'hs-administrator-position': HSAdministratorPositionViewSet,
    'hs-position': HSPositionViewSet,
    'hs-administrator-access-request': HSAdministratorAccessRequestViewSet,
    'hs-administrator-dangling': DanglingHSAdminViewSet,

    'term': TermViewSet,
    'academic-year': AcademicYearViewSet,

    'class_section': ClassSectionViewSet,
    'class-section-history': ClassSectionHistoryViewSet,
    'class_section_notes': ClassSectionNoteViewSet,
    'class_section_syllabi': ClassSectionSyllabiViewSet,

    # future_sections ViewSets moved to future_sections.urls.ce

    'course': CourseViewSet,
    'course-history': CourseHistoryViewSet,
    'course-app-requirement': CourseAppRequirementViewSet,
    'course-uploads': CourseUploadViewSet,
    'course-notes': CourseNoteViewSet,
    
    'cohort': CohortViewSet,
    'teacher': TeacherViewSet,
    'teacher-course': TeacherCourseViewSet,
    'teacher-notes': TeacherNotesViewSet,
    'teacher-uploads': TeacherUploadViewSet,
    'all-teacher-uploads': AllTeacherUploadViewSet,
    'instructor-dangling': DanglingInstructorViewSet,

    'campus': CampusViewSet,
    'highschool-served': HighSchoolServedByCampusViewSet,
    'class-registered': ClassesRegisteredByCampusViewSet,
    'registration-summary': RegistrationSummaryViewSet,

    'teacher_application': TeacherApplicationViewSet,
    'teacher_application_reviewers': TeacherApplicationReviewerViewSet,

    'location': LocationViewSet,
    'tech_center': TechCenterViewSet,
    'tech_center_staff': TechCenterStaffViewSet,

    'student': StudentViewSet,
    'student_recommendation': StudentRecommendationViewSet,
    'student_agreement': StudentAgreementViewSet,
    'student_support_docs': StudentSupportingDocumentViewSet,
    'student_tuitionassistance': StudentTuitionAssistanceViewSet,
    'parent_consent': ParentConsentViewSet,
    'registration': RegistrationViewSet,
    'registration-history': StudentRegistrationHistoryViewSet,
    'failed_mirror_registrations': FailedMirrorRegistrationViewSet,
    'pending_sis_mirror_registrations': PendingSisMirrorRegistrationViewSet,
    'drop_wd_req': StudentDropViewSet,
    'campus_id': StudentCampusIDViewSet,
    'student-note': StudentNoteViewSet,
    'student-history': StudentHistoryViewSet,
    'student-dangling': DanglingStudentViewSet,
    
    'faculty': FacultyViewSet,
    'faculty-dangling': DanglingFacultyViewSet,
    'course_administrator': CourseAdministratorViewSet,

    'cronlog': CronLogViewSet,

    'sis_logs': SIS_LogViewSet,

    'credential-expiry': CredentialExpiryViewSet,
    'credential-summary': CredentialSummaryViewSet,
}

for router_key in router_viewsets.keys():
    router.register(
        router_key,
        router_viewsets[router_key],
        basename=router_key
    )

urlpatterns = [

    path('api/', include(router.urls)),

    path(
        'api/comparison/<slug:dimension>/',
        user_passes_test(user_has_cis_role, login_url='/')(comparison_data),
        name='comparison_data'
    ),

    path('ldap/', ldap_login, name="ldap_login"),
    path(
        'dashboard/',
        user_passes_test(user_has_cis_role, login_url='/')(dashboard),
        name='dashboard'
    ),

    path(
        'add_new_ajax/',
        add_new_ajax,
        name='add_new_ajax'
    ),

    path(
        'student/bulk_actions',
        user_passes_test(user_has_cis_role, login_url='/')(student_bulk_actions),
        name='student_bulk_actions'
    ),
    path(
        'student/sis_logs',
        user_passes_test(user_has_cis_role, login_url='/')(sis_logs_index),
        name='sis_logs'
    ),
    path(
        'student/sis_log/<int:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(sis_log_details),
        name='sis_log_details'
    ),
    path(
        'pwd_reset_link/',
        user_passes_test(user_has_cis_role, login_url='/')(pwd_reset_link),
        name='pwd_reset_link'
    ),
    path(
        'footer/<str:page_type>',
        get_footer,
        name='footer'
    ),
    path(
        'landing_page_content/',
        get_landing_page_text,
        name='landing_page_content'
    ),
    path('export_to_excel/<str:model_type>/<uuid:parent>', user_passes_test(user_has_cis_role, login_url='/')(export_to_excel), name='export_to_excel'),
    path(
        'teacher/course_certificate/delete/<int:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(delete_course_certificate),
        name='delete_course_certificate'
    ),
    path(
        'teacher/highschool/delete/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(delete_teacher_highschool),
        name='delete_teacher_highschool'
    ),

    path(
        'teacher_applications/',
        user_passes_test(user_has_cis_role, login_url='/')(teacher_applications),
        name='teacher_applications'),
    path(
        'teacher_application/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(teacher_application),
        name='teacher_application'),
    path(
        'teacher_application/remove_file/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(tapp_remove_file),
        name='tapp_remove_file'),

    path(
        'teacher_application/delete/course/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(delete_teacher_course),
        name='delete_teacher_course'),
    path(
        'teacher_application/download_files/<uuid:record_id>',
        download_tapp_files,
        name='download_tapp_files'
    ),
    path(
        'teacher_application/download/<uuid:record_id>',
        download_tapp,
        name='download_tapp'
    ),
    path(
        'teacher_application/remind_reviewer',
        remind_reviewer,
        name='remind_reviewer'
    ),
    path(
        'teacher_application/<uuid:record_id>/action',
        do_teacher_app_action,
        name='teacher_app_action'
    ),
    path(
        'teacher_application/remove_recommendation/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(tapp_remove_recommendation),
        name='tapp_remove_recommendation'),
    path(
        'teacher_application/delete/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(delete_teacher_application),
        name='delete_teacher_application'),
    path(
        'teacher_application/note/reply/<uuid:note_id>',
        teacher_app_note_reply,
        name='teacher_app_note_reply'
    ),
    path(
        'teacher_application/view_approval_email/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(view_approval_email),
        name='view_approval_email'
    ),
    path(
        'teacher_application/send_approval_email/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(send_approval_email),
        name='send_approval_email'
    ),

    path('districts/', user_passes_test(user_has_cis_role, login_url='/')(district_home), name='districts'),
    path('district/add_new', user_passes_test(user_has_cis_role, login_url='/')(district_add_new), name='district_add_new'),
    path('district/<uuid:record_id>', user_passes_test(user_has_cis_role, login_url='/')(district_detail), name='district_detail'),
    path('district/delete/<uuid:record_id>', user_passes_test(user_has_cis_role, login_url='/')(delete_district), name='delete_district'),
    path('district/ajax', user_passes_test(user_has_cis_role, login_url='/')(district_ajax_search), name='district_ajax_search'),

    path('district_roles/', user_passes_test(user_has_cis_role, login_url='/')(district_role_home), name='district_roles'),
    path('district_role/add_new', user_passes_test(user_has_cis_role, login_url='/')(district_role_add_new), name='district_role_add_new'),
    path('district_role/<uuid:record_id>', user_passes_test(user_has_cis_role, login_url='/')(district_role_detail), name='district_role_detail'),
    #path('district_role/ajax', district_role_ajax_search, name='district_role_ajax_search'),

    path('district_admins/', user_passes_test(user_has_cis_role, login_url='/')(district_admin_home), name='district_admins'),
    path('district_admin/<uuid:record_id>', user_passes_test(user_has_cis_role, login_url='/')(district_admin_detail), name='district_admin_detail'),
    path('district_admin/add_new', user_passes_test(user_has_cis_role, login_url='/')(district_admin_add_new), name='district_admin_add_new'),
    
    path('highschools/', user_passes_test(user_has_cis_role, login_url='/')(hs_home), name='highschools'),
    path('highschool/add_new', user_passes_test(user_has_cis_role, login_url='/')(hs_add_new), name='hs_add_new'),
    path('highschool/download_template', user_passes_test(user_has_cis_role, login_url='/')(download_highschool_template), name='hs_download_template'),
    path(
        'highschool/transcript/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(download_transcript),
        name='download_transcript'
    ),
    path('highschool/<uuid:record_id>', user_passes_test(user_has_cis_role, login_url='/')(hs_detail), name='hs_detail'),
    path('highschool/<uuid:record_id>/tab/<slug:tab_slug>/', user_passes_test(user_has_cis_role, login_url='/')(highschool_tab), name='highschool_tab'),
    path('highschool/delete/<uuid:record_id>', user_passes_test(user_has_cis_role, login_url='/')(delete_highschool), name='delete_highschool'),
    path('highschool/ajax', user_passes_test(user_has_cis_role, login_url='/')(hs_ajax_search), name='hs_ajax_search'),
    path('api/highschool-map/', user_passes_test(user_has_cis_role, login_url='/')(highschool_map_data), name='highschool_map_data'),
    path('api/highschool-map-courses/', user_passes_test(user_has_cis_role, login_url='/')(highschool_map_courses), name='highschool_map_courses'),
    path(
        'highschool/bulk_actions',
        user_passes_test(user_has_cis_role, login_url='/')(hs_bulk_actions),
        name='highschool_bulk_actions'
    ),
    path('highschool_roles/', user_passes_test(user_has_cis_role, login_url='/')(hs_roles), name='hs_roles'),
    path('highschool_role/add_new', user_passes_test(user_has_cis_role, login_url='/')(hs_role_add_new), name='hs_role_add_new'),
    path('highschool_role/<uuid:record_id>', user_passes_test(user_has_cis_role, login_url='/')(hs_role), name='hs_role'),
    path('highschool_role/delete/<uuid:record_id>', user_passes_test(user_has_cis_role, login_url='/')(delete_hs_position), name='delete_hs_position'),

    path('highschool_admins/', user_passes_test(user_has_cis_role, login_url='/')(hs_admins), name='hs_admins'),
    path('highschool_admin/<uuid:record_id>', user_passes_test(user_has_cis_role, login_url='/')(hs_admin), name='hs_admin'),
    path('highschool_admin/<uuid:record_id>/tab/<slug:tab_slug>/', user_passes_test(user_has_cis_role, login_url='/')(hs_admin_tab), name='hs_admin_tab'),
    path('highschool_admin/add_new', user_passes_test(user_has_cis_role, login_url='/')(hs_admin_add_new), name='hs_admin_add_new'),
    path('highschool_admin/download_template', user_passes_test(user_has_cis_role, login_url='/')(download_hs_member_template), name='hs_admin_download_template'),
    path(
        'highschool_admin/delete/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(delete_hs_admin),
        name='delete_hs_admin'
    ),
    path(
        'highschool_admin/role/delete/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(delete_hs_admin_role),
        name='delete_hs_admin_role'
    ),
    path(
        'highschool_admin/revoke_role/<int:user_id>',
        user_passes_test(user_has_cis_role, login_url='/')(revoke_hs_admin_role),
        name='revoke_hs_admin_role'
    ),
    path(
        'highschool_admin/access_requests',
        user_passes_test(user_has_cis_role, login_url='/')(hs_admin_access_requests), name='hs_admin_access_requests'
    ),
    path(
        'highschool_admin/access_request/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(hs_admin_access_request), name='hs_admin_access_request'
    ),
    path(
        'highschool_admin/access_request/<uuid:record_id>/tab/<slug:tab_slug>/',
        user_passes_test(user_has_cis_role, login_url='/')(access_request_tab), name='access_request_tab'
    ),
    path(
        'highschool_admin/access_request/delete/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(delete_access_request), name='delete_access_request'
    ),
    path(
        'highschool_admin/do_bulk_action/',
        user_passes_test(user_has_cis_role, login_url='/')(do_bulk_action), name='hs_admin_do_bulk_action'
    ),
    path(
        'highschool_admin/do_person_bulk_action',
        user_passes_test(user_has_cis_role, login_url='/')(do_person_bulk_action),
        name='hs_admin_do_person_bulk_action'
    ),
    path(
        'highschool_admin/do_dangling_bulk_action',
        user_passes_test(user_has_cis_role, login_url='/')(do_dangling_bulk_action),
        name='hs_admin_do_dangling_bulk_action'
    ),
    path(
        'academic_years/',
        user_passes_test(user_has_cis_role, login_url='/')(academic_years), name='academic_years'
    ),
    path('academic_year/<uuid:record_id>', user_passes_test(user_has_cis_role, login_url='/')(academic_year), name='academic_year'),
    path('academic_year/<uuid:record_id>/tab/<slug:tab_slug>/', user_passes_test(user_has_cis_role, login_url='/')(academic_year_tab), name='academic_year_tab'),
    path('academic_year/delete/<uuid:record_id>', user_passes_test(user_has_cis_role, login_url='/')(delete_academic_year), name='delete_academic_year'),
    path('academic_year/add_new', user_passes_test(user_has_cis_role, login_url='/')(academic_year_add_new), name='academic_year_add_new'),
    path('academic_year/download_template', user_passes_test(user_has_cis_role, login_url='/')(download_academic_year_template), name='academic_year_download_template'),
    path('academic_year/bulk_actions', user_passes_test(user_has_cis_role, login_url='/')(academic_year_bulk_actions), name='academic_year_bulk_actions'),

    path('terms/', user_passes_test(user_has_cis_role, login_url='/')(terms), name='terms'),
    path('term/<uuid:record_id>', user_passes_test(user_has_cis_role, login_url='/')(term), name='term'),
    path('term/<uuid:record_id>/tab/<slug:tab_slug>/', user_passes_test(user_has_cis_role, login_url='/')(term_tab), name='term_tab'),
    path('term/delete/<uuid:record_id>', user_passes_test(user_has_cis_role, login_url='/')(delete_term), name='delete_term'),
    path('term/add_new', user_passes_test(user_has_cis_role, login_url='/')(term_add_new), name='term_add_new'),
    path('term/download_template', user_passes_test(user_has_cis_role, login_url='/')(download_term_template), name='term_download_template'),
    path('term/bulk_actions', user_passes_test(user_has_cis_role, login_url='/')(term_bulk_actions), name='term_bulk_actions'),

    path('categories/', user_passes_test(user_has_cis_role, login_url='/')(categories), name='categories'),
    path('category/<uuid:record_id>', user_passes_test(user_has_cis_role, login_url='/')(category), name='category'),
    path('category/add_new', user_passes_test(user_has_cis_role, login_url='/')(category_add_new), name='category_add_new'),

    path('cohorts/', user_passes_test(user_has_cis_role, login_url='/')(cohorts), name='cohorts'),
    path('cohort/<uuid:record_id>', user_passes_test(user_has_cis_role, login_url='/')(cohort), name='cohort'),
    path('cohort/delete/<uuid:record_id>', user_passes_test(user_has_cis_role, login_url='/')(delete_cohort), name='delete_cohort'),
    path('cohort/add_new', user_passes_test(user_has_cis_role, login_url='/')(cohort_add_new), name='cohort_add_new'),
    path('cohort/download_template', user_passes_test(user_has_cis_role, login_url='/')(download_cohort_template), name='cohort_download_template'),

    path(
        'locations/',
        user_passes_test(user_has_cis_role, login_url='/')(locations),
        name='locations'),
    path(
        'location/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(location),
        name='location'),
    path(
        'location/add_new',
        user_passes_test(user_has_cis_role, login_url='/')(location_add_new),
        name='location_add_new'),

    path(
        'tech_center_staffs/',
        user_passes_test(user_has_cis_role, login_url='/')(tech_center_staffs),
        name='tech_center_staffs'),
    path(
        'tech_center_staff/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(tech_center_staff),
        name='tech_center_staff'),
    path(
        'tech_center_staff/add_new',
        user_passes_test(user_has_cis_role, login_url='/')(tech_center_staff_add_new),
        name='tech_center_staff_add_new'),

    path(
        'tech_centers/',
        user_passes_test(user_has_cis_role, login_url='/')(tech_centers),
        name='tech_centers'),
    path(
        'tech_center/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(tech_center),
        name='tech_center'),
    path(
        'tech_center/add_new',
        user_passes_test(user_has_cis_role, login_url='/')(tech_center_add_new),
        name='tech_center_add_new'),

    path(
        'campuses/',
        user_passes_test(user_has_cis_role, login_url='/')(campuses),
        name='campuses'),
    path(
        'campus/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(campus),
        name='campus'),
    path(
        'campus/add_new',
        user_passes_test(user_has_cis_role, login_url='/')(campus_add_new),
        name='campus_add_new'),

    path(
        'cronlog/',
        user_passes_test(user_has_cis_role, login_url='/')(cronlog_index),
        name='cronlog'),
    path(
        'users/',
        user_passes_test(user_has_cis_role, login_url='/')(users),
        name='users'),
    path(
        'user/<int:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(user),
        name='user'),
    path(
        'user/add_new',
        user_passes_test(user_has_cis_role, login_url='/')(user_add_new),
        name='user_add_new'),
    
    path(
        'section_numbers/',
        user_passes_test(user_has_cis_role, login_url='/')(section_numbers),
        name='section_numbers'),

    path(
        'section_number/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(section_number),
        name='section_number'),

    path(
        'section_number/delete/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(delete_section_number),
        name='delete_section_number'),

    path(
        'section_number/add_new',
        user_passes_test(user_has_cis_role, login_url='/')(section_number_add_new),
        name='section_number_add_new'),

    path('colleges/', user_passes_test(user_has_cis_role, login_url='/')(colleges), name='colleges'),
    path('college/<uuid:record_id>', user_passes_test(user_has_cis_role, login_url='/')(college), name='college'),
    path('college/add_new', user_passes_test(user_has_cis_role, login_url='/')(college_add_new), name='college_add_new'),

    path('departments/', user_passes_test(user_has_cis_role, login_url='/')(departments), name='departments'),
    path('department/<uuid:record_id>', user_passes_test(user_has_cis_role, login_url='/')(department), name='department'),
    path('department/add_new', user_passes_test(user_has_cis_role, login_url='/')(department_add_new), name='department_add_new'),

    path('courses/', user_passes_test(user_has_cis_role, login_url='/')(courses), name='courses'),
    path(
        'courses/bulk_actions',
        user_passes_test(user_has_cis_role, login_url='/')(course_bulk_actions), 
        name='course_bulk_actions'
    ),
    path('course/<uuid:record_id>', user_passes_test(user_has_cis_role, login_url='/')(course), name='course'),
    path('course/<uuid:record_id>/tab/<slug:tab_slug>/', user_passes_test(user_has_cis_role, login_url='/')(course_tab), name='course_tab'),
    path('course/delete/<uuid:record_id>', user_passes_test(user_has_cis_role, login_url='/')(delete_course), name='delete_course'),
    path('course/add_new', user_passes_test(user_has_cis_role, login_url='/')(course_add_new), name='course_add_new'),
    path('course/download_template', user_passes_test(user_has_cis_role, login_url='/')(download_course_template), name='course_download_template'),
    path(
        'course/administrator/delete/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(delete_course_administrator_role),
        name='delete_course_administrator_role'
    ),

    path(
        'college_instructors/',
        user_passes_test(user_has_cis_role, login_url='/')(college_instructors),
        name='college_instructors'),
    path(
        'college_instructor/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(college_instructor),
        name='college_instructor'),

    path(
        'instructors/',
        user_passes_test(user_has_cis_role, login_url='/')(instructors),
        name='instructors'),
    path(
        'instructors/bulk_actions/',
        user_passes_test(user_has_cis_role, login_url='/')(teacher_bulk_actions),
        name='teacher_bulk_actions'),
    path(
        'instructor/delete/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(delete_teacher),
        name='instructor_delete'
    ),
    path(
        'instructor/revoke_role/<int:user_id>',
        user_passes_test(user_has_cis_role, login_url='/')(revoke_instructor_role),
        name='revoke_instructor_role'
    ),
    path(
        'instructor/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(instructor),
        name='instructor'),
    path('instructor/<uuid:record_id>/tab/<slug:tab_slug>/', user_passes_test(user_has_cis_role, login_url='/')(instructor_tab), name='instructor_tab'),
    path('instructor/add_new', user_passes_test(user_has_cis_role, login_url='/')(instructor_add_new), name='instructor_add_new'),
    path('instructor/download_template', user_passes_test(user_has_cis_role, login_url='/')(download_instructor_template), name='instructor_download_template'),
    path(
        'instructor/do_dangling_bulk_action',
        user_passes_test(user_has_cis_role, login_url='/')(instructor_do_dangling_bulk_action),
        name='instructor_do_dangling_bulk_action'
    ),

    path(
        'credentials/',
        credentials_views.index,
        name='credentials'),
    path(
        'credentials/bulk_actions/',
        credentials_views.bulk_actions,
        name='credential_bulk_actions'),

    path('faculty_coordinators/', user_passes_test(user_has_cis_role, login_url='/')(faculty_coordinators), name='faculty_coordinators'),
    path('faculty_coordinator/<uuid:record_id>', user_passes_test(user_has_cis_role, login_url='/')(faculty_coordinator), name='faculty_coordinator'),
    path(
        'faculty_coordinator/<uuid:record_id>/tab/<slug:tab_slug>/',
        user_passes_test(user_has_cis_role, login_url='/')(faculty_coordinator_tab),
        name='faculty_coordinator_tab',
    ),
    path('faculty_coordinator/add_new', user_passes_test(user_has_cis_role, login_url='/')(faculty_coordinator_add_new), name='faculty_coordinator_add_new'),
    path('faculty_coordinator/download_template', user_passes_test(user_has_cis_role, login_url='/')(download_faculty_template), name='faculty_coordinator_download_template'),
    path(
        'faculty_coordinators/bulk_actions',
        user_passes_test(user_has_cis_role, login_url='/')(faculty_bulk_actions),
        name='faculty_bulk_actions'
    ),
    path(
        'faculty/do_dangling_bulk_action',
        user_passes_test(user_has_cis_role, login_url='/')(faculty_do_dangling_bulk_action),
        name='faculty_do_dangling_bulk_action'
    ),

    # Future sections - views moved to future_sections app
    # URL now included directly in myce/urls.py at path('ce/future_sections/', ...)
    path(
        'sections/',
        user_passes_test(user_has_cis_role, login_url='/')(sections),
        name='sections'
    ),
    path(
        'sections/bulk_actions',
        user_passes_test(user_has_cis_role, login_url='/')(section_bulk_actions),
        name='section_bulk_actions'
    ),
    path(
        'sections/delete_syllabi/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(delete_syllabi),
        name='delete_syllabi'
    ),
    path(
        'sections/course_search/',
        user_passes_test(user_has_cis_role, login_url='/')(course_search),
        name='course_search'
    ),
    path(
        'section/delete/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(delete_class_section),
        name='delete_class_section'
    ),
    path(
        'section/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(section),
        name='section'
    ),
    path(
        'section/<uuid:record_id>/tab/<slug:tab_slug>/',
        user_passes_test(user_has_cis_role, login_url='/')(section_tab),
        name='section_tab'
    ),
    path('section/add_new', user_passes_test(user_has_cis_role, login_url='/')(section_add_new), name='section_add_new'),
    path('section/download_template', user_passes_test(user_has_cis_role, login_url='/')(download_section_template), name='section_download_template'),
    path(
        'section/import_from_s3',
        user_passes_test(user_has_cis_role, login_url='/')(import_sections_from_s3),
        name='import_sections_from_s3'
    ),
    # path(
    #     'sections/test_sftp',
    #     test_sftp,
    #     name='test_sftp'
    # ),
    path('section/ajax', user_passes_test(user_has_cis_role, login_url='/')(section_ajax), name='section_ajax'),

    path(
        'student/ajax',
        user_passes_test(user_has_cis_role, login_url='/')(student_ajax_action),
        name='student_ajax'),
    path(
        'student/details',
        user_passes_test(user_has_cis_role, login_url='/')(get_student_details),
        name='student_details'),
    path(
        'students/<uuid:pk>/profile-changes/',
        user_passes_test(user_has_cis_role, login_url='/')(student_profile_changes),
        name='student_profile_changes'),
    path(
        'students/',
        user_passes_test(user_has_cis_role, login_url='/')(students),
        name='students'),
    path(
        'students/recommendations',
        user_passes_test(user_has_cis_role, login_url='/')(recommendations),
        name='recommendations'),

    path(
        'students/support_docs/',
        user_passes_test(user_has_cis_role, login_url='/')(support_docs),
        name='support_docs'),
    path(
        'students/support_docs/bulk_actions',
        user_passes_test(user_has_cis_role, login_url='/')(support_docs_bulk_actions),
        name='support_docs_bulk_actions'),
    path(
        'students/notes/',
        user_passes_test(user_has_cis_role, login_url='/')(student_notes),
        name='students_notes'),
    path('student/import/template',
         user_passes_test(user_has_cis_role, login_url='/')(student_import_views.download_template),
         name='student_import_template'),
    path('student/import/upload',
         user_passes_test(user_has_cis_role, login_url='/')(student_import_views.upload),
         name='student_import_upload'),
    path('student/import/<uuid:batch_id>/preview',
         user_passes_test(user_has_cis_role, login_url='/')(student_import_views.preview),
         name='student_import_preview'),
    path('student/import/<uuid:batch_id>/confirm',
         user_passes_test(user_has_cis_role, login_url='/')(student_import_views.confirm),
         name='student_import_confirm'),
    path(
        'student/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(student),
        name='student'),
    path(
        'student/<uuid:record_id>/tab/<slug:tab_slug>/',
        user_passes_test(user_has_cis_role, login_url='/')(student_tab),
        name='student_tab'),
    path(
        'student/add_new',
        user_passes_test(user_has_cis_role, login_url='/')(student_add_new),
        name='student_add_new'),
    path(
        'student/as_pdf/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(student_pdf),
        name='student_pdf'),
    path(
        'student/register_for_class/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(register_for_class), 
        name='register_for_class'
    ),
    path(
        'student/settings/',
        user_passes_test(user_has_cis_role, login_url='/')(student_settings),
        name='student_settings'),
    path(
        'settings-overview/<str:profile>/',
        settings_overview_page,
        name='settings_overview'),
    path(
        'student/export_import/',
        user_passes_test(user_has_cis_role, login_url='/')(student_exports),
        name='student_exports'
    ),
    path(
        'students/faas/',
        user_passes_test(user_has_cis_role, login_url='/')(faa_index),
        name='faa_index'
    ),
    path(
        'students/faa/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(faa),
        name='faa'
    ),
    path(
        'students/faa/delete/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(delete_faa),
        name='delete_faa_request'
    ),
    path(
        'student/delete/support_doc/<uuid:support_doc_id>',
        user_passes_test(user_has_cis_role, login_url='/')(delete_support_doc),
        name='delete_support_doc'
    ),
    path(
        'student/delete/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(student_delete),
        name='student_delete'
    ),
    path(
        'student/revoke_role/<int:user_id>',
        user_passes_test(user_has_cis_role, login_url='/')(revoke_student_role),
        name='revoke_student_role'
    ),
    path(
        'student/do_dangling_bulk_action',
        user_passes_test(user_has_cis_role, login_url='/')(student_do_dangling_bulk_action),
        name='student_do_dangling_bulk_action'
    ),
    path(
        'student/note/delete',
        user_passes_test(user_has_cis_role, login_url='/')(delete_student_note),
        name='delete_student_note'
    ),
    path(
        'students/import_from_s3',
        import_students_from_s3,
        name='import_students_from_s3'
    ),
    path(
        'students/import_registrations_from_s3',
        import_registrations_from_s3,
        name='import_registrations_from_s3'
    ),
    path(
        'registrations/',
        user_passes_test(user_has_cis_role, login_url='/')(registrations),
        name='registrations'),
    path(
        'registrations/failed-mirror/',
        failed_mirror_page,
        name='registrations_failed_mirror'),
    path(
        'registrations/failed-mirror/export/',
        failed_mirror_export,
        name='registrations_failed_mirror_export'),
    path(
        'registrations/pending-mirror/',
        pending_mirror_page,
        name='registrations_pending_mirror'),
    path(
        'registration/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(registration),
        name='registration'),
    path(
        'registration/<uuid:record_id>/tab/<slug:tab_slug>/',
        user_passes_test(user_has_cis_role, login_url='/')(registration_tab),
        name='registration_tab'),
    path(
        'registration/delete/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(delete_registration),
        name='delete_registration'),
    path(
        'registration/bulk_actions',
        user_passes_test(user_has_cis_role, login_url='/')(registration_bulk_actions),
        name='registration_bulk_actions'
    ),
    path(
        'drop_wd_reqs/',
        user_passes_test(user_has_cis_role, login_url='/')(drop_wd_reqs),
        name='drop_wd_reqs'),
    path(
        'drop_wd_req/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(drop_wd_req),
        name='drop_wd_req'),
    path(
        'drop_wd_req/delete/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(delete_drop_wd_req),
        name='delete_drop_wd_req'),
    path(
        'venues/',
        user_passes_test(user_has_cis_role, login_url='/')(venues),
        name='venues'
    ),
    path(
        'venue/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(venue),
        name='venue'),
    path(
        'venue/add_new',
        user_passes_test(user_has_cis_role, login_url='/')(venue_add_new), 
        name='venue_add_new'),
    path(
        'speakers/',
        user_passes_test(user_has_cis_role, login_url='/')(speakers),
        name='speakers'
    ),
    path(
        'speaker/<uuid:record_id>',
        user_passes_test(user_has_cis_role, login_url='/')(speaker),
        name='speaker'),
    path(
        'speaker/add_new',
        user_passes_test(user_has_cis_role, login_url='/')(speaker_add_new), 
        name='speaker_add_new'),
    # path(
    #     'events/',
    #     user_passes_test(user_has_cis_role, login_url='/')(events),
    #     name='events'
    # ),
    # path(
    #     'event/<uuid:record_id>',
    #     user_passes_test(user_has_cis_role, login_url='/')(event),
    #     name='event'),
    # path(
    #     'event/add_new',
    #     user_passes_test(user_has_cis_role, login_url='/')(event_add_new),
    #     name='event_add_new'),
    # path(
    #     'event/delete_record',
    #     user_passes_test(user_has_cis_role, login_url='/')(delete_record_from_event),
    #     name='delete_record_from_event'),
    # path(
    #     'event/edit_item',
    #     user_passes_test(user_has_cis_role, login_url='/')(edit_event_item),
    #     name='edit_event_item'),
]
