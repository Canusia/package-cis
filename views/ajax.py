from django.http import HttpResponse, JsonResponse

from cis.views.district import add_new as district_add_new
from cis.views.district_administrator import add_new_role as district_admin_role_add_new
from cis.views.hs_administrator import (
    add_new_role as hs_admin_role_add_new,
    get_password_reset_link as hs_administrator_pwd_reset_link
)

from ..views.users import (
    get_password_reset_link as user_pwd_reset_link
)

from cis.views.teacher import (
    add_new_highschool as teacher_hs_add_new,
    add_new_course_certificate  as teacher_course_certificate,
    delete_teacher_upload
)

from cis.views.course import delete_course_upload, manage_course_administrator_role

from cis.views.highschool import (
    add_new_college_advisor as add_new_college_advisor_to_highschool
)

from cis.views.faculty import add_new_course as fac_course_add_new
from cis.views.registration import manage_registration

from cis.views.section import (
    manage_courseoffering, edit_record as edit_class_section
)

from ..views.student import (
    edit_record as edit_student,
    edit_campus_id as edit_student_campus_id
)

from cis.views.event import (
    add_new_speaker as event_speaker_add_new,
    add_new_cohort as event_cohort_add_new
)
from cis.views.note import add_new_note
from cis.utils import user_has_cis_role
from cis.views.teacher_application import add_new_course_reviewer

from support_ticket.views.tickets import (
    add_new_support_request as manage_support_requests
)

def get_footer(request, page_type='non_logged'):
    from cis.settings.footer import footer
    from cis.utils import user_has_student_role, user_has_highschool_admin_role, user_has_cis_role, user_has_faculty_role

    try:
        if request.user.is_authenticated:
            if user_has_cis_role(request.user):
                page_type = "logged_staff"
            else:
                if user_has_student_role(request.user):
                    page_type = "logged_student"
                elif user_has_highschool_admin_role(request.user):
                    page_type = "logged_hsadmin"
                elif user_has_faculty_role(request.user):
                    page_type = "logged_faculty"
    except:
        ...
        
    setting = footer.from_db()

    return JsonResponse({'footer': setting.get(page_type, '')})
get_footer.login_required = False

def get_landing_page_text(request):
    page_type = request.GET.get('page', 'homepage') + '_text'

    from cis.settings.portal_content import portal_content
    setting = portal_content.from_db()

    return JsonResponse({'text': setting.get(page_type, '')})
get_landing_page_text.login_required = False

def pwd_reset_link(request):
    if request.method == 'POST':
        model = request.POST.get('model', None)
    else:
        model = request.GET.get('model', None)

    if model == 'hs_administrator':
        return hs_administrator_pwd_reset_link(request)

    if model == 'customuser':
        return user_pwd_reset_link(request)

def add_new(request):
    '''
    Add new page
    '''

    if request.method == 'POST':
        model = request.POST.get('model', None)
    else:
        model = request.GET.get('model', None)

    if model == 'studentplannote':
        return add_new_note(request, "studentplan")
        
    if model == 'district':
        return district_add_new(request)
    if model == 'districtadministratorrole':
        # PT-41: rendering/saving the District Administrator Position form is a
        # CE-only action. Its GET path renders DistrictAdministratorPositionForm,
        # whose `district` field is a ModelChoiceField over District.objects.all(),
        # disclosing every district name + UUID; its POST path creates a
        # DistrictAdministratorPosition. add_new is reachable from both
        # /ce/add_new_ajax/ (ungated at the URL in ewu) and /highschool_admin/ajax/,
        # so this per-branch guard is the sole defense; it covers POST + GET.
        if not user_has_cis_role(request.user):
            return JsonResponse({
                'status': 'error',
                'message': 'You are not authorized to perform this action.',
            }, status=403)
        return district_admin_role_add_new(request)
    if model == 'faculty_course_administrator':
        return fac_course_add_new(request)
    if model == 'course_administrator':
        return manage_course_administrator_role(request)
    if model == 'hsadministratorrole':
        return hs_admin_role_add_new(request)
    if model == 'highschoolcollegeadvisor':
        return add_new_college_advisor_to_highschool(request)
    if model == 'teacherhighschool':
        # PT-8: creating/updating a TeacherHighSchool also elevates the teacher
        # into the 'instructor' group (TeacherHighSchool.save), so it is a
        # CE-only action. add_new is reachable from both /ce/add_new_ajax/
        # (ungated at the URL in ewu) and /highschool_admin/ajax/, so this
        # per-branch guard is the sole defense; it covers POST + GET.
        if not user_has_cis_role(request.user):
            return JsonResponse({
                'status': 'error',
                'message': 'You are not authorized to perform this action.',
            }, status=403)
        return teacher_hs_add_new(request)
    if model == 'delete_teacher_upload':
        return delete_teacher_upload(request)
    if model == 'delete_course_upload':
        return delete_course_upload(request)
    if model == 'teachercoursecertificate':
        return teacher_course_certificate(request)
    if model == 'eventspeaker':
        return event_speaker_add_new(request)
    if model == 'eventcohort':
        return event_cohort_add_new(request)

    if model == 'teachernote':
        # PT-23: instructor (teacher) notes are a CE-only action.
        # add_new_ajax and add_new_note are both shared across roles, so the
        # guard lives on this single dispatch branch (covers POST + GET).
        if not user_has_cis_role(request.user):
            return JsonResponse({
                'status': 'error',
                'message': 'You are not authorized to perform this action.',
            }, status=403)
        return add_new_note(request, "teacher")
    if model == 'teacherapplicationnote':
        return add_new_note(request, 'teacherapplication')
    
    if model == 'visitreportnote':
        return add_new_note(request, 'visitreport')

    if model == 'coursenote':
        return add_new_note(request, "course")
    
    if model == 'eventnote':
        return add_new_note(request, "event")

    if model == 'hsadminnote':
        return add_new_note(request, "hsadmin")
    if model == 'highschoolnote':
        return add_new_note(request, "highschool")
    if model == 'classsectionnote':
        return add_new_note(request, "classsection")
    if model == 'ticketnote':
        return add_new_note(request, 'ticket')

    if model == 'studentnote':
        return add_new_note(request, "student")
    if model == 'student_replynote':
        return add_new_note(request, "student_reply")

    if model == 'studentcampusid':
        return edit_student_campus_id(request)

    if model == 'studentregistration':
        return manage_registration(request)
    if model == 'facultycoursecoordinator':
        return fac_course_add_new(request)

    if model == 'classsection':
        return edit_class_section(request)

    if model == 'student':
        return edit_student(request)

    if model == 'courseoffering':
        return manage_courseoffering(request)

    if model == 'supportrequest':
        return manage_support_requests(request)

    elif model == 'applicationcoursereviewer':
        return add_new_course_reviewer(request)

    return HttpResponse('')
