"""
Student Views
"""
import csv, io, logging, datetime, uuid
from itertools import chain

from django.conf import settings
from django.db import IntegrityError
from django.urls import reverse
from django.db.models import Q
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse, HttpResponse
from django.views.decorators.clickjacking import xframe_options_exempt
from django.utils.safestring import mark_safe
from django.template.loader import get_template, render_to_string

from cis.utils import (
    get_uploaded_file, active_term, get_default_campus,
    registration_terms, is_student_registration_open, YES_NO_OPTIONS, YES_NO_SELECT_OPTIONS,
    user_has_cis_role, user_has_faculty_role,
    user_has_highschool_admin_role, user_has_instructor_role,
)
from cis.campus_gate import (
    scope_students_by_campus, can_access_student,
    processable_student_ids, get_accessible_campuses,
    scope_records_by_student_campus,
)
from cis.models.student import (
    recommendation_required_q,
    Student, StudentRecommendation,
    StudentAgreement, ParentConsent,
    StudentCampusID,
    StudentSupportingDocument,
    StudentTuitionAssistance,
    StudentTuitionAssistanceDocument
)

from cis.models.section import Campus, ClassSection
from cis.models.term import Term
from cis.forms.student import (
    # StudentProfileForm,
    StudentExportForm,
    StudentCampusIDForm, MigrateStudentForm,
    StudentSupportingDocumentForm,
    StudentStateQForm,
    StudentTuitionAssistanceForm,
    # StudentTuitionAssistanceDocumentForm,
    ManageFAAForm
)
from cis.forms.student_profile import StudentCISForm as StudentProfileForm

from cis.models.settings import Setting
from cis.models.note import StudentNote

from cis.utils import registration_terms
from cis.menu import cis_menu, draw_menu
from cis.services.table_configs import get_table_config
build_registrations_table_config = get_table_config('registrations_table').build_config
build_students_table_config                = get_table_config('students_table').build_config
build_student_recommendations_table_config = get_table_config('student_recommendations_table').build_config
build_support_docs_table_config            = get_table_config('support_docs_table').build_config
build_student_notes_table_config           = get_table_config('student_notes_table').build_config
from myce.component_registry.student import student_actions, student_tabs
from myce.component_registry.support_docs import support_docs_actions
from cis.settings.registrations import RegistrationForm
from cis.forms.section import (
    AddNewStudentRegistrationForm, ClassSectionUploadForm,
    AddNewHighSchoolClassOfferingForm
)
from cis.forms.student_import import StudentImportUploadForm

logger = logging.getLogger(__name__)

from rest_framework import viewsets
from rest_framework.exceptions import ValidationError

from rest_framework.decorators import api_view 
from rest_framework.response import Response

from ..serializers.student import (
    StudentSerializer,
    StudentRecommendationSerializer,
    StudentAgreementSerializer,
    ParentConsentSerializer,
    StudentCampusIDSerializer,
    StudentSupportingDocumentSerializer,
    StudentTuitionAssistanceSerializer
    # StudentNoteSerializer
)

from cis.utils import CIS_user_only, FACULTY_user_only, INSTRUCTOR_user_only, STUDENT_user_only, user_has_student_role, HSADMIN_user_only

from ..serializers.note import StudentNoteSerializer
from ..serializers.history import HistorySerializer
from cis.models.customuser import CustomUser


# Slugs hidden from the dirty-profile-review tab on /ce/students/#dirty.
# These verification-related actions aren't relevant when a CE admin is
# reviewing edits a student made to their own profile.
_DIRTY_TAB_HIDDEN_ACTION_SLUGS = {
    'mark_as_unverified',
    'resend_verification_link',
    'get_verification_link',
    'send_password_reset_link',
    'bulk_delete',
}

# Slugs hidden from the default "All" tab on /ce/students/#all.
# These dirty-review actions only make sense in the Profile Changes tab.
_ALL_TAB_HIDDEN_ACTION_SLUGS = {
    'bulk_mark_not_dirty',
    'bulk_set_status_pending',
}


def _filter_bulk_actions(grouped, hidden_slugs):
    """Return a copy of for_scope('bulk') output with hidden slugs removed.

    Empty groups are dropped so the toolbar doesn't render empty sections.
    """
    from collections import OrderedDict
    out = OrderedDict()
    for group_key, group in grouped.items():
        kept = OrderedDict(
            (slug, action) for slug, action in group.get('actions', {}).items()
            if slug not in hidden_slugs
        )
        if kept:
            out[group_key] = {'actions': kept}
    return out


def _filter_dirty_tab_bulk_actions(grouped):
    return _filter_bulk_actions(grouped, _DIRTY_TAB_HIDDEN_ACTION_SLUGS)


def _filter_all_tab_bulk_actions(grouped):
    return _filter_bulk_actions(grouped, _ALL_TAB_HIDDEN_ACTION_SLUGS)


class StudentHistoryViewSet(viewsets.ViewSet):
    permission_classes = [CIS_user_only]

    def list(self, request):
        student_id = request.GET.get('student_id')
        try:
            student = Student.objects.get(pk=student_id)
        except Student.DoesNotExist:
            return Response({'data': []})

        student_history = list(
            Student.history.filter(id=student_id).order_by('-history_date')
        )
        user_history = list(
            CustomUser.history.filter(id=student.user_id).order_by('-history_date')
        )

        # Tag each record with its source model
        for rec in student_history:
            rec._source_model = 'Student'
        for rec in user_history:
            rec._source_model = 'User'

        combined = sorted(
            chain(student_history, user_history),
            key=lambda r: r.history_date,
            reverse=True
        )

        serializer = HistorySerializer(combined, many=True)
        return Response({'data': serializer.data})

class StudentTuitionAssistanceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StudentTuitionAssistanceSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        student_id = self.request.GET.get('student_id')
        term_id = self.request.GET.get('term_id')
        status = self.request.GET.get('status')
        campus = self.request.GET.get('campus', '').strip()

        records = StudentTuitionAssistance.objects.all()

        if student_id:
            records = records.filter(
                student__id=student_id
            )

        if term_id:
            records = records.filter(
                term__id=term_id
            )

        if status:
            records = records.filter(
                status=status
            )

        return scope_records_by_student_campus(
            records, self.request.user, selected_campus=campus or None)

class StudentNoteViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StudentNoteSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        student_id = self.request.GET.get('student_id')
        added_by = self.request.GET.get('added_by')
        campus = self.request.GET.get('campus', '').strip()

        records = StudentNote.objects.all()

        # StudentNote.student is nullable, so null-student notes stay visible to
        # every ce user (the null-campus analogue).
        def _scope(qs):
            return scope_records_by_student_campus(
                qs, self.request.user, include_null_student=True,
                selected_campus=campus or None)

        if added_by:
            records = records.filter(
                createdby__id=added_by
            )

            responses = StudentNote.objects.filter(
                parent__in=records.values_list('id', flat=True)
            )
            return _scope(records | responses)

        # get all notes for the student
        if student_id:
            return _scope(records.filter(
                student__id=student_id))
        return _scope(records)

from cis.models.section import StudentRegistration

class StudentCampusIDViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StudentCampusIDSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        student = self.request.GET.get('student', '').strip()

        records = StudentCampusID.objects.filter().all()

        if student:
            records = records.filter(
                student__id=student
            )

        return records

class ParentConsentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ParentConsentSerializer
    permission_classes = [CIS_user_only|FACULTY_user_only|INSTRUCTOR_user_only]

    def get_queryset(self):
        term = self.request.GET.get('term', '').strip()
        student = self.request.GET.get('student', '').strip()

        records = ParentConsent.objects.filter().all()

        if student:
            records = records.filter(
                student__id=student
            )

        return records

class StudentAgreementViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StudentAgreementSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        term = self.request.GET.get('term', '').strip()
        student = self.request.GET.get('student', '').strip()

        records = StudentAgreement.objects.filter().all()

        if student:
            records = records.filter(
                student__id=student
            )

        return records

class StudentRecommendationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StudentRecommendationSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        term = self.request.GET.get('term', '').strip()
        student = self.request.GET.get('student', '').strip()
        campus = self.request.GET.get('campus', '').strip()

        records = StudentRecommendation.objects.filter().all()

        if term:
            records = records.filter(
                term__id=term
            )

        if student:
            records = records.filter(
                student__id=student
            )

        return scope_records_by_student_campus(
            records, self.request.user, selected_campus=campus or None)

class StudentSupportingDocumentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StudentSupportingDocumentSerializer
    permission_classes = [CIS_user_only|STUDENT_user_only]

    def get_queryset(self):
        term = self.request.GET.get('term', '').strip()
        student = self.request.GET.get('student', '').strip()
        campus = self.request.GET.get('campus', '').strip()

        if user_has_student_role(self.request.user):
            student = str(self.request.user.student.id)

        records = StudentSupportingDocument.objects.filter().all()

        if term:
            records = records.filter(
                term__id=term
            )

        if student:
            records = records.filter(
                student__id=student
            )

        # No-op for the student role (self-scoped above); scopes ce staff to
        # their campuses, narrowed to the dropdown's `campus` when set.
        return scope_records_by_student_campus(
            records, self.request.user, selected_campus=campus or None)

class StudentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StudentSerializer
    permission_classes = [
        CIS_user_only | FACULTY_user_only | INSTRUCTOR_user_only | HSADMIN_user_only
    ]

    def get_queryset(self):
        term = None #self.request.GET.get('term', str(active_term().id)).strip()
        campus = self.request.GET.get('campus', '').strip()
        record_type = self.request.GET.get('record_type', '').strip()
        created_on = self.request.GET.get('created_on', '').strip()
        created_until = self.request.GET.get('created_until', '').strip()
        term_id = self.request.GET.get('term_id', '').strip()

        records = Student.objects.filter().all()

        if created_on:
            try:
                created_on = datetime.datetime.strptime(created_on, '%Y-%m-%d')
                records = records.filter(
                    user__created_at__gte=created_on
                )
            except:
                ...

        if created_until:
            try:
                created_until = datetime.datetime.strptime(created_until, '%Y-%m-%d')
                records = records.filter(
                    user__created_at__lt=created_until
                )
            except:
                ...

        if record_type:
            if record_type == 'missing_sis_send':
                records = records.filter(
                    user__psid = '-',
                    account_verified=True,
                    sis_applied_on__isnull=True
                )

            if record_type == 'dirty':
                records = records.filter(profile_dirty_at__isnull=False)

            if record_type == 'sis_error':
                records = records.filter(
                    user__psid__in=['-', ' ', None],
                    sis_applied_on__isnull=False
                )

            if record_type == 'missing_sis':
                records = records.filter(
                    sis_applied_on__isnull=True
                )
            
            if record_type == 'missing_recommendation':
                registration_term_id = self.request.GET.get('registration_term_id')

                applied_students = StudentRegistration.objects.filter(
                    Q(status__in=['applied', 'registered', 'approved']) &
                    Q(class_section__registration_term__id=registration_term_id) &
                    recommendation_required_q()
                ).values_list('student__id', flat=True)

                has_recommendation = StudentRecommendation.objects.filter(
                    term__id=registration_term_id
                ).values_list('student__id', flat=True)


                records = records.filter(
                    id__in=applied_students
                ).exclude(
                    id__in=has_recommendation
                )

                # skip_ids = []
                # for record in records:
                #     if f'{record.student.grade_level}*' not in record.class_section.course.registration_eligibility:
                #         skip_ids.append(record.id)
                # records = records.exclude(id__in=skip_ids)


            if record_type == 'missing_faa':
                term_id = self.request.GET.get('term_id')

                applied_students = StudentRegistration.objects.filter(
                    class_section__registration_term__id=term_id
                ).values_list('student__id', flat=True)

                has_faa = StudentTuitionAssistance.objects.filter(
                    term__id=term_id
                ).values_list('student__id', flat=True)

                records = records.filter(
                    meta__qualify_tuition_assistance='True',
                    id__in=applied_students
                ).exclude(
                    id__in=has_faa
                )

            if record_type == 'pending_admit':
                records = records.filter(
                    sis_admitted_on__isnull=True
                ).exclude(
                    sis_applied_on__isnull=True
                )

            if record_type == 'pending_matriculation':
                records = records.filter(
                    sis_matriculated_on__isnull=True
                ).exclude(
                    sis_applied_on__isnull=True,
                    sis_admitted_on__isnull=True
                )

            if record_type == 'not_verified':
                records = records.filter(
                    account_verified=False
                )

            if record_type == 'not_applied':
                not_applied = Student.objects.raw('select id from cis_Student where id not in (select distinct student_id from cis_StudentRegistration)')
                not_applied_ids = [ d.id for d in not_applied ]
                
                records = records.filter(
                    id__in=not_applied_ids
                )

            if record_type == 'not_applied':
                records = records.filter(
                    account_verified=False
                )

            if record_type == 'missing_ssn':
                records = records.filter(
                    user__ssn=''
                )

            if record_type.startswith('status_'):
                records = records.filter(
                    application_status=record_type[len('status_'):]
                )


        if term_id:
            # PT-1: reject anything that is not a well-formed UUID before it
            # reaches the database. This closes the SQL-injection vector (the
            # term_id was previously interpolated into a raw SQL string) and
            # avoids the ORM raising on a malformed filter value.
            try:
                uuid.UUID(term_id)
            except (ValueError, AttributeError, TypeError):
                return records.none()

            applied_in_term_ids = StudentRegistration.objects.filter(
                class_section__term__id=term_id
            ).values_list('student__id', flat=True).distinct()
            records = records.filter(
                id__in=applied_in_term_ids
            )

        # PT-4: object-level scoping (applied last, after all other filters).
        # CE/faculty staff see all students (multi-tenant); a highschool_admin
        # sees only students in the high schools they administer; an instructor
        # sees only students in their own class sections. DRF retrieve() runs
        # through this queryset, so out-of-scope detail lookups return 404.
        import importlib.util
        if importlib.util.find_spec('highschool_admin.highschool_admin'):
            from highschool_admin.highschool_admin.views.utils import get_user_highschools
        else:
            from highschool_admin.views.utils import get_user_highschools

        user = self.request.user
        if user_has_cis_role(user) or user_has_faculty_role(user):
            return scope_students_by_campus(records, user, selected_campus=campus)
        if user_has_highschool_admin_role(user):
            return records.filter(
                highschool__in=get_user_highschools(self.request)
            )
        if user_has_instructor_role(user):
            section_student_ids = StudentRegistration.objects.filter(
                class_section__teacher__user=user
            ).values_list('student__id', flat=True).distinct()
            return records.filter(id__in=section_student_ids)
        return records.none()

def add_new(request):
    '''
    Add new page
    '''
    base_template = 'cis/logged-base.html'
    template = 'cis/students/add_new.html'
    ajax = request.GET.get('ajax', None)

    upload_form = ClassSectionUploadForm()

    if request.method == 'POST':
        if request.POST.get('action') == "import_emplid":
            return import_emplid_from_file(request)
        elif request.POST.get('action') == "import_registrations":
            return import_registrations_from_file(request)
    else:
        upload_form = ClassSectionUploadForm()

    return render(
        request,
        template, {
            'upload_form': upload_form,
            'student_upload_form': StudentImportUploadForm(),
            'page_title': "Manage Students",
            'labels': {
                'all_items': 'All Students'
            },
            'urls': {
                'add_new': 'cis:student_add_new',
                'all_items': 'cis:students'
            },
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'students', 'students')
        })

def import_emplid_from_file(request, type='registrations'):
    form = ClassSectionUploadForm(request.POST, request.FILES)

    if form.is_valid():
        decoded_file = request.FILES.get('file').read().decode('utf-8')
        reader = csv.DictReader(io.StringIO(decoded_file))

        file_name = "emplid_import_results.csv"

        result = StudentCampusID.import_from_csv(reader)

        if result['status'] == 'success':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{file_name}"'

            writer = csv.writer(response)
            writer.writerow(result['records'][0].keys())
            for row in result['records']:
                writer.writerow(row.values())
            return response

        # there was an error processing file, print it
        messages.add_message(
            request,
            messages.SUCCESS,
            'There was an error processing the file.' + result['message'],
            'list-group-item-danger')

        return redirect('cis:student_add_new')

def import_students_from_file(request, type='registrations'):
    form = ClassSectionUploadForm(request.POST, request.FILES)

    if form.is_valid():
        decoded_file = request.FILES.get('file').read().decode('utf-8')
        reader = csv.DictReader(io.StringIO(decoded_file))

        file_name = "student_import_results.csv"

        result = Student.import_from_csv(reader)

        if result['status'] == 'success':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{file_name}"'

            writer = csv.writer(response)
            writer.writerow(result['records'][0].keys())
            for row in result['records']:
                writer.writerow(row.values())
            return response

        # there was an error processing file, print it
        messages.add_message(
            request,
            messages.SUCCESS,
            'There was an error processing the file.' + result['message'],
            'list-group-item-danger')

        return redirect('cis:student_add_new')

def import_registrations_from_file(request, type='registrations'):
    form = ClassSectionUploadForm(request.POST, request.FILES)

    if form.is_valid():
        decoded_file = request.FILES.get('file').read().decode('utf-8')
        reader = csv.DictReader(io.StringIO(decoded_file))

        file_name = "registration_import_results.csv"

        result = StudentRegistration.import_from_csv(reader)

        if result['status'] == 'success':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{file_name}"'

            writer = csv.writer(response)
            writer.writerow(result['records'][0].keys())
            for row in result['records']:
                writer.writerow(row.values())
            return response

        # there was an error processing file, print it
        messages.add_message(
            request,
            messages.SUCCESS,
            'There was an error processing the file.' + result['message'],
            'list-group-item-danger')

        return redirect('cis:student_add_new')

def import_from_s3(request):
    students = get_uploaded_file('student_export')

    if not students:
        logger.error('Unable to read student export')
    else:
        reader = csv.DictReader(io.StringIO(students))
        file_name = "student_import_results.csv"
        result = Student.import_from_csv(reader)
        if result['status'] == 'success':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{file_name}"'

            writer = csv.writer(response)
            writer.writerow(result['records'][0].keys())
            for row in result['records']:
                writer.writerow(row.values())
            return response
        else:
            logger.error(f'Error while processing student export {result}')
import_from_s3.login_required = False


@student_actions.action('bulk_only', label='Mark Waiver', scope=['detail'], method='form')
def mark_waiver(request):
    from cis.forms.student import MarkStudentWaiverForm
    ids = request.POST.getlist('ids[]')
    template = 'cis/students/bulk_delete.html'

    if request.POST.get('action_confirmed'):
        form = MarkStudentWaiverForm(recommendation_ids=ids, data=request.POST)
        if form.is_valid():
            form.save(request)
            return JsonResponse({
                'outcome': 'call',
                'fn': 'onActionComplete',
                'args': {'title': 'Done', 'message': 'Successfully marked recommendation waiver', 'status': 'success'},
            })
        return JsonResponse({
            'message': 'Please correct the errors and try again.',
            'errors': form.errors.as_json(),
        }, status=400)

    form = MarkStudentWaiverForm(recommendation_ids=ids)
    html = render_to_string(template, {
        'title': 'Recommendation Waiver',
        'form': form,
        'form_action': reverse('cis:student_bulk_actions'),
        'action_slug': 'mark_waiver',
        'ids': ids,
    }, request=request)
    return JsonResponse({'outcome': 'modal', 'html': html})

@student_actions.action('bulk_only', label='Update GPA', scope=['detail'], method='form')
def update_gpa(request):
    from cis.forms.student import UpdateGPAForm
    ids = request.POST.getlist('ids[]')
    template = 'cis/students/bulk_delete.html'

    if request.POST.get('action_confirmed'):
        form = UpdateGPAForm(recommendation_ids=ids, data=request.POST)
        if form.is_valid():
            form.save(request)
            return JsonResponse({
                'outcome': 'call',
                'fn': 'onActionComplete',
                'args': {'title': 'Done', 'message': 'Successfully updated GPA', 'status': 'success'},
            })
        return JsonResponse({
            'message': 'Please correct the errors and try again.',
            'errors': form.errors.as_json(),
        }, status=400)

    form = UpdateGPAForm(recommendation_ids=ids)
    html = render_to_string(template, {
        'title': 'Update GPA',
        'form': form,
        'form_action': reverse('cis:student_bulk_actions'),
        'action_slug': 'update_gpa',
        'ids': ids,
    }, request=request)
    return JsonResponse({'outcome': 'modal', 'html': html})

def import_registrations_from_s3(request):
    registrations = get_uploaded_file('registration_export')
    
    if not registrations:
        logger.error('Unable to read registration export')
    else:
        file_name = "registration_import_results.csv"

        #Reset registrations for the term
        reset_term_ids = Setting.get_value("cis_registrations", 'active_term')
        reset_terms = Term.objects.filter(
            id__in=reset_term_ids
        )
        StudentRegistration.reset_registrations(reset_terms)

        reader = csv.DictReader(io.StringIO(registrations))
        result = StudentRegistration.import_from_csv(reader)
        if result['status'] == 'success':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{file_name}"'

            writer = csv.writer(response)
            writer.writerow(result['records'][0].keys())
            for row in result['records']:
                writer.writerow(row.values())
            return response
        else:
            logger.error(f'Error while processing registration export {result}')
import_registrations_from_s3.login_required = False


def delete_note(request):
    note_id = request.GET.get('note_id')
    record = get_object_or_404(StudentNote, pk=note_id)

    if record.student and not can_access_student(request.user, record.student):
        return JsonResponse({'status': 'error',
            'message': 'You are not authorized to access this student.'}, status=403)

    if record.createdby != request.user and not request.user.is_superuser:
        data = {
            'status':'warning',
            'message':'You cannot delete this note. Contact the note author or the system administrator to delete it.',
            'action': ''
        }
        return JsonResponse(data)

    record.delete()

    data = {
        'status':'success',
        'message':'Successfully deleted record',
        'action': 'reload'
    }
    return JsonResponse(data)

def delete_record(request, record_id):
    record = get_object_or_404(Student, pk=record_id)
    if not can_access_student(request.user, record):
        return JsonResponse({'status': 'error',
            'message': 'You are not authorized to access this student.'}, status=403)
    try:
        Student.delete_record(record)

        data = {
            'status':'success',
            'message':'Successfully deleted record',
            'action': 'reload'
        }
    except Exception as e:
        data = {
            'status':'error',
            'message':'Unable to delete record. ' + str(e),
            'action': ''
        }
    return JsonResponse(data)

def data_export_import(request):
    """
    Record details page
    """
    template = 'cis/students/exports.html'

    if request.method == 'POST':
        if request.POST.get('export_data') == 'Export Data':
            export_form = StudentExportForm(request.POST)

        if export_form.is_valid():
            return Student.export_pplsoft_file(
                export_form.cleaned_data['start_date'],
                export_form.cleaned_data['end_date']
            )
    else:
        export_form = StudentExportForm()

    return render(
        request,
        template, {
            'page_title': "Student Export/Import",
            'labels': {
                'all_items': 'All Students'
            },
            'urls': {
                'all_items': 'cis:students'
            },
            'menu': draw_menu(cis_menu, 'students', 'student_exports'),
            'export_form': export_form,
            'reset_term': Setting.get_value("cis_registrations", 'terms')
        })

def mod_settings(request):
    '''
    Settings page
    '''
    template = 'cis/students/settings.html'
    key = "cis_registrations"

    try:
        setting = Setting.objects.get(key=key)
    except Setting.DoesNotExist:
        setting = Setting()
        setting.key = key
        setting.value = {}

    if request.method == 'POST':
        form = RegistrationForm(request.POST)

        if form.is_valid():
            try:
                setting.value = form._to_python()
                setting.save()

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully saved settings',
                    'list-group-item-success')
            except IntegrityError:
                form._errors['term'] = ['There was an error processing your request']
        else:
            messages.add_message(
                request,
                messages.SUCCESS,
                'Some of the required fields are missing, please try again.',
                'list-group-item-danger')

    form = RegistrationForm(initial={
        'active_term': setting.value.get('active_term'),
        'signature_term': setting.value.get('signature_term'),
        'registration_terms': setting.value.get('registration_terms'),
        'starting_date': setting.value.get('starting_date'),
        'ending_date': setting.value.get('ending_date'),
        'window_close_notice': setting.value.get('window_close_notice'),
        'academic_year': setting.value.get('academic_year')
        })

    return render(
        request,
        template, {
            'form': form,
            'page_title': "Settings",
            'labels': {
                'all_items': 'All Students'
            },
            'urls': {
                'all_items': 'cis:students'
            },
            'menu': draw_menu(cis_menu, 'students', 'students')
        })


def edit_campus_id(request):
    # PT-12: StudentCampusID create/update (and form prefill) is a CE-only
    # action. add_new_ajax is shared across roles, so the guard lives here.
    if not user_has_cis_role(request.user):
        return JsonResponse({
            'status': 'error',
            'message': 'You are not authorized to perform this action.',
        }, status=403)

    ajax = request.GET.get('ajax', None)
    base_template = 'cis/logged-base.html' if not ajax else 'cis/ajax-base.html'
    template = 'cis/students/edit.html'

    if request.method == 'POST':
        form = StudentCampusIDForm(request.POST)

        if form.is_valid():
            if form.cleaned_data['id'] == '-1':
                _gate_student = get_object_or_404(Student, pk=form.cleaned_data['student_id'])
            else:
                _cid = get_object_or_404(StudentCampusID, pk=form.cleaned_data['id'])
                _gate_student = _cid.student
            if not can_access_student(request.user, _gate_student):
                return JsonResponse({'status': 'error',
                    'message': 'You are not authorized to access this student.'}, status=403)
            form.save()

            data = {
                'status':'success',
                'message':'Successfully saved record',
                'new_record_id':form.cleaned_data['id'],
                'new_record_name':'',
                'action': 'reload'
            }
            return JsonResponse(data)
    else:
        record_id = request.GET.get('id')
        record = get_object_or_404(StudentCampusID, pk=record_id)
        if not can_access_student(request.user, record.student):
            return JsonResponse({'status': 'error',
                'message': 'You are not authorized to access this student.'}, status=403)
        form = StudentCampusIDForm(
            initial={
                'id':record.id,
                'student_id':record.student.id,
                'campus':record.campus,
                'username':record.username,
                'user_id':record.user_id,
                'email':record.email
            }
        )

    return render(
        request,
        template, {
            'form': form,
            'ajax': ajax,
            'model': 'studentcampusid',
            'base_template': base_template
        })

def edit_record(request):
    # PT-20: editing student records (model=student via add_new_ajax) is a
    # CE-only action. Combined with field sanitization in StudentCISForm, this
    # removes the stored-XSS vector behind {{record.asHTML|safe}}.
    if not user_has_cis_role(request.user):
        return JsonResponse({
            'status': 'error',
            'message': 'You are not authorized to perform this action.',
        }, status=403)

    ajax = request.GET.get('ajax', None)
    base_template = 'cis/logged-base.html' if not ajax else 'cis/ajax-base.html'
    template = 'cis/students/edit.html'

    if request.method == 'POST':
        record_id = request.POST.get('id')
        record = get_object_or_404(Student, pk=record_id)

        if not can_access_student(request.user, record):
            return JsonResponse({'status': 'error',
                'message': 'You are not authorized to access this student.'}, status=403)

        form = StudentProfileForm(record, request, request.POST)
        if form.is_valid():
            record = form.save(record)
                
            # record.update_profile(form)

            data = {
                'status':'success',
                'message':'Successfully saved record',
                'new_record_id':record.id,
                'new_record_name':'',
                'action': 'reload'
            }
            return JsonResponse(data)
        else:
            data = {
                    'status':'error',
                    'message':'Please correct the errors and try again.',
                    'new_record_id':record.id,
                    'new_record_name':'',
                    'errors': form.errors.as_json(),
                    'action': ''
                }
            return JsonResponse(data, status=400)
    else:
        record_id = request.GET.get('id')
        record = get_object_or_404(Student, pk=record_id)
        if not can_access_student(request.user, record):
            return JsonResponse({'status': 'error',
                'message': 'You are not authorized to access this student.'}, status=403)
        form = StudentProfileForm(
            student=record,
            request=request
        )

    request.session['record_key'] = str(record.id)
    request.session['record_type'] = '1'
    
    return render(
        request,
        template, {
            'form': form,
            'ajax': ajax,
            'model': 'student',
            'base_template': base_template
        })

def ajax_action(request):
    action = request.GET.get('action')

    if action == 'send_parent_consent_link':
        return send_parent_consent_link(request)
    
    if action == 'get_parent_consent_link':
        return get_parent_consent_link(request)
    
    if action == 'delete_student_agreement':
        return delete_student_agreement(request)

    if action == 'waive_parent_consent':
        return waive_parent_consent(request)

    if action == 'delete_parent_consent':
        return delete_parent_consent(request)

    if action == 'get_recommendation_link':
        return get_recommendation_link(request)

    if action == 'mark_student_consent_recv':
        return waive_student_consent(request)

    if action == 'get_payment_link':
        return get_payment_link(request)
    
    if action == 'email_payment_link':
        return email_payment_link(request)
    
    if action == 'delete_recommendation':
        return delete_recommendation(request)

def get_payment_link(request):
    from cis.utils import is_student_billpay_open
    student_id = request.GET.get('id')
    term_id = request.GET.get('term')

    student = get_object_or_404(Student, pk=student_id)
    if not can_access_student(request.user, student):
        return JsonResponse({'status': 'error',
            'message': 'You are not authorized to access this student.'}, status=403)
    term = get_object_or_404(Term, pk=term_id)

    url = student.get_payment_url(student_id, term_id)

    message = 'Please send the following link'
    if not is_student_billpay_open():
        student.enable_allow_late_billpay()
        message = 'Bill Pay is currently closed....turning on late bill pay for student<br><br>' + message

    data = {
        'message': f'{message}\r\n\r\n' + url,
        'status': 'success'
    }
    return JsonResponse(data)

def email_payment_link(request):
    from cis.utils import is_student_billpay_open
    student_id = request.GET.get('id')
    term_id = request.GET.get('term')

    student = get_object_or_404(Student, pk=student_id)
    if not can_access_student(request.user, student):
        return JsonResponse({'status': 'error',
            'message': 'You are not authorized to access this student.'}, status=403)
    term = get_object_or_404(Term, pk=term_id)

    message = ''
    if not is_student_billpay_open():
        student.enable_allow_late_billpay()
        message = 'Bill Pay is currently closed....turning on late bill pay for student<br><br>'
    
    url = student.send_payment_url(term_id)

    data = {
        'message': f'{message}Payment Link has been sent to the student and their parent',
        'status': 'success'
    }
    
    student.add_note(request.user, 'Sent payment link to student and parent')
    return JsonResponse(data)

def send_parent_consent_link(request):
    student_id = request.GET.get('id')
    term_id = request.GET.get('term')

    student = get_object_or_404(Student, pk=student_id)
    if not can_access_student(request.user, student):
        return JsonResponse({'status': 'error',
            'message': 'You are not authorized to access this student.'}, status=403)
    term = get_object_or_404(Term, pk=term_id)

    ParentConsent.send_notification(
        student=student,
        term_id=term.id,
        parent_name=student.parent_first_name,
        parent_email=student.parent_email
        # parent_email='kadaji@gmail.com'
    )

    student.add_note(request.user, 'Sent Parent consent request email')
    data = {
        'message': f'Successfully emailed link to parent at {student.parent_email}',
        'status': 'success'
    }
    return JsonResponse(data)

@student_actions.action('bulk_only', label='Delete Recommendation', scope=['detail'])
def delete_recommendation(request):
    ids = request.POST.getlist('ids[]') or [request.POST.get('record_id')]
    recommendations = StudentRecommendation.objects.filter(id__in=ids)

    # Campus gate: these ids[] are StudentRecommendation ids (not student ids),
    # so the central do_bulk_action filter skips this action — restrict here to
    # recommendations whose student the caller may access.
    accessible = [
        r.id for r in recommendations
        if can_access_student(request.user, r.student)
    ]
    recommendations = StudentRecommendation.objects.filter(id__in=accessible)

    try:
        recommendations.delete()
        return JsonResponse({
            'outcome': 'alert', 'status': 'success',
            'title': 'Delete Recommendation', 'message': 'Successfully deleted recommendation(s)',
        })
    except Exception as e:
        return JsonResponse({
            'outcome': 'alert', 'status': 'error',
            'title': 'Delete Recommendation',
            'message': 'Failed to delete one or more recommendation(s). ' + str(e),
        }, status=400)

def delete_parent_consent(request):
    record_id = request.GET.get('record_id')

    try:
        consent = ParentConsent.objects.get(
            pk=record_id
        )
        
        consent.delete()
        consent.student.add_note(request.user, 'Deleted parent consent')

        data = {
            'message': 'Successfully removed parent consent. Please update registrations appropriately.',
            'status': 'success'
        }
    except Exception as e:
        data = {
            'message': 'There was an error. ' + str(e),
            'status': 'error'
        }
    return JsonResponse(data)


def delete_student_agreement(request):
    record_id = request.GET.get('record_id')

    try:
        record = StudentAgreement.objects.get(
            pk=record_id
        )
        
        record.student.add_note(request.user, 'Deleted student agreement')
        record.delete()

        data = {
            'message': 'Successfully removed student agreement. Please update registrations appropriately.',
            'status': 'success'
        }
    except Exception as e:
        data = {
            'message': 'There was an error. ' + str(e),
            'status': 'error'
        }
    return JsonResponse(data)

def waive_student_consent(request):
    student_id = request.GET.get('id')
    term_id = request.GET.get('term')

    student = get_object_or_404(Student, pk=student_id)
    if not can_access_student(request.user, student):
        return JsonResponse({'status': 'error',
            'message': 'You are not authorized to access this student.'}, status=403)
    term = get_object_or_404(Term, pk=term_id)

    import datetime
    try:
        student_agreeement = StudentAgreement()
        student_agreeement.student = student
        student_agreeement.term = term #Term.objects.get(pk=cleaned_data['term'])

        student_agreeement.student_signature = f'Marked as received by {request.user}'
        student_agreeement.student_signed_on = datetime.datetime.now()

        student_agreeement.save()
        data = {
            'message': 'Successfully marked as received',
            'status': 'success'
        }
    except Exception as e:
        data = {
            'message': 'There was an error. ' + str(e),
            'status': 'error'
        }
    return JsonResponse(data)

def waive_parent_consent(request):
    student_id = request.GET.get('id')
    term_id = request.GET.get('term')

    student = get_object_or_404(Student, pk=student_id)
    if not can_access_student(request.user, student):
        return JsonResponse({'status': 'error',
            'message': 'You are not authorized to access this student.'}, status=403)
    term = get_object_or_404(Term, pk=term_id)

    import datetime
    try:
        parent_consent = ParentConsent()
        parent_consent.student = student
        parent_consent.term = term

        parent_consent.parent_signature = f'Marked as received by {request.user}'
        parent_consent.parent_signed_on = datetime.datetime.now()

        parent_consent.save()

        # The CE "mark as received" path writes the same row as the parent
        # signing it, so it must complete the same onboarding step (ewu#54).
        from student_onboarding.signals import onboarding_event
        from student_onboarding import events as onboarding_events

        onboarding_event.send(
            sender=__name__,
            event=onboarding_events.PARENT_CONSENT_SIGNED,
            student=student,
        )

        data = {
            'message': 'Successfully marked as received',
            'status': 'success'
        }
    except Exception as e:
        data = {
            'message': 'There was an error. ' + str(e),
            'status': 'error'
        }
    return JsonResponse(data)

def register_for_class(request, record_id):
    student = Student.objects.get(pk=record_id)
    if not can_access_student(request.user, student):
        return JsonResponse({'status': 'error',
            'message': 'You are not authorized to access this student.'}, status=403)
    selected_sections = request.POST.getlist('class_section', None)

    if not selected_sections:
        return JsonResponse({
            'status': 'error',
            'message': 'Please select a class and try again'})

    num_applied = 0
    mesg = []
    for section in selected_sections:
        try:
            class_section = ClassSection.objects.get(pk=section)
            if StudentRegistration.can_register(student, class_section):
                registration = StudentRegistration()
                registration.student = student
                registration.class_section = class_section
                registration.status = 'applied'
                registration.highschool = student.highschool
                registration.status_changed_on = {}

                registration.save()
                num_applied += 1

                mesg.append(
                    f'Successfully added {class_section.course} - {class_section.class_number}/{class_section.section_number}')
            else:
                mesg.append(
                        f'Unable to add {class_section.course}-{class_section.class_number}/{class_section.section_number}. Possible duplicate or you have already added a different section of the {class_section.course}.')
        except IntegrityError as e:
            mesg.append(
                    f'Unable to add {class_section.course}-{class_section.class_number}/{class_section.section_number}. You have already added it.' + str(e))
    return JsonResponse({
        'status': 'success',
        'message': '\n'.join(mesg)})

def get_parent_consent_link(request):
    student_id = request.GET.get('id')
    term_id = request.GET.get('term')

    student = get_object_or_404(Student, pk=student_id)
    if not can_access_student(request.user, student):
        return JsonResponse({'status': 'error',
            'message': 'You are not authorized to access this student.'}, status=403)
    term = get_object_or_404(Term, pk=term_id)

    url = ParentConsent.get_url(student_id, term_id)
    index = 1
    parent_consent_link = f'<span id=\'copy_to_{index}\'>{url}</span>&nbsp;&nbsp;<i title=\'copy to clipboard\' class=\'fas fa fa-paste copy-clipboard\' data-clipboard-target=\'#copy_to_{index}\' style=\'cursor: pointer\'></i>'
    data = {
        'message': 'Please send the following link\r\n\r\n' + parent_consent_link,
        'status': 'success'
    }
    return JsonResponse(data)

def get_recommendation_link(request):
    student_id = request.GET.get('id')
    term_id = request.GET.get('term')

    student = get_object_or_404(Student, pk=student_id)
    if not can_access_student(request.user, student):
        return JsonResponse({'status': 'error',
            'message': 'You are not authorized to access this student.'}, status=403)
    term = get_object_or_404(Term, pk=term_id)

    url = ParentConsent.get_url(student_id, term_id)
    data = {
        'message': 'Please send the following link\r\n\r\n' + url,
        'status': 'success'
    }
    return JsonResponse(data)

def get_student_details(request):
    from cis.utils import user_has_cis_role

    if not user_has_cis_role(request.user):
        data = {
            'message': "Hmmmm",
            'status': 'success'
        }
        return JsonResponse(data)
    
    student_id = request.GET.get('studentid')
    try:
        student = get_object_or_404(Student, pk=student_id)
    except Exception as e:
        data = {
            'message': "<h2>Destination Student Details</h2>" + str(e),
            'status': 'success'
        }
        return JsonResponse(data)
    if not can_access_student(request.user, student):
        return JsonResponse({'status': 'error',
            'message': 'You are not authorized to access this student.'}, status=403)
    data = {
        'message': "<h2>Destination Student Details</h2>" + student.asHTML(),
        'status': 'success'
    }
    return JsonResponse(data)

def tab(request, record_id, tab_slug):
    """Render a single Student detail-page tab fragment (lazy AJAX)."""
    record = get_object_or_404(Student, pk=record_id)
    if not can_access_student(request.user, record):
        return JsonResponse({'status': 'error',
            'message': 'You are not authorized to access this student.'}, status=403)
    return student_tabs.render_tab(request, record, tab_slug)


from django.views.decorators.clickjacking import xframe_options_exempt
@xframe_options_exempt
def detail(request, record_id):
    """
    Record details page
    """
    template = 'cis/students/detail.html'
    record = get_object_or_404(Student, pk=record_id)

    if not can_access_student(request.user, record):
        return render(request, 'cis/not_authorized.html',
            {'message': 'You are not authorized to access this student.'}, status=403)

    student_id_form = StudentCampusIDForm(
        initial={
            'id': '-1',
            'student_id': record.id
        }
    )

    support_doc_form = StudentSupportingDocumentForm(
        record
    )
    migration_form = MigrateStudentForm()

    if request.method == 'POST':
        if request.POST.get('action') == 'update_state_q':
            state_q_form = StudentStateQForm(
                student=record,
                data=request.POST
            )

            if state_q_form.is_valid():
                state_q_form.save(record)
                return JsonResponse({
                    'status': 'success',
                    'message': 'Successfully updated state Q'
                })
            else:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Please correct the errors and try again',
                    'errors': state_q_form.errors.as_json()
                }, status=400)
            
        if request.POST.get('action') == 'upload_support_doc':
            support_doc_form = StudentSupportingDocumentForm(
                record,
                data=request.POST,
                files=request.FILES
            )

            if support_doc_form.is_valid():
                support_doc = support_doc_form.save(commit=True)
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully uploaded file.',
                    'list-group-item-success')
            else:
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Please correct the errors and try again',
                    'list-group-item-danger')
        
        if request.POST.get('action') == 'migrate_student':
            migration_form = MigrateStudentForm(
                request.POST
            )

            if migration_form.is_valid():
                success, message = migration_form.save(request, record)

                if not success:
                    messages.add_message(
                        request,
                        messages.SUCCESS,
                        'Your request was processed with some errors.<br>' + '<br>'.join(message),
                        'list-group-item-warning')
                else:
                    messages.add_message(
                        request,
                        messages.SUCCESS,
                        'Successfully completed request. ' + ','.join(message),
                        'list-group-item-success')
            else:
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Please correct the errors and try again',
                    'list-group-item-danger')

    return render(
        request,
        template, {
            'page_title': "Student",
            'labels': {
                'all_items': 'All Students'
            },
            'urls': {
                'add_new': 'cis:student_add_new',
                'all_items': 'cis:students'
            },
            'menu': draw_menu(cis_menu, 'students', 'students'),
            'detail_actions': student_actions.for_scope('detail', request.user),
            'record': record,
            'active_term': active_term(),
            'terms': Term.objects.all(),
            'is_registration_open': True,
            'registration_terms': Term.objects.all(),
            'detail_tabs': student_tabs.for_record(
                request, record,
                url_for=lambda slug: reverse('cis:student_tab', args=[record.id, slug])),
        })

def delete_support_doc(request, support_doc_id):
    doc = get_object_or_404(StudentSupportingDocument, pk=support_doc_id)

    if not can_access_student(request.user, doc.student):
        return JsonResponse({'status': 'error',
            'message': 'You are not authorized to access this student.'}, status=403)

    doc.student.add_note(request.user, 'Deleting supporting doc ' + doc.filename)
    doc.delete()

    return JsonResponse({
        'status':"success"
    })

def notes(request):
    menu = draw_menu(cis_menu, 'students', 'notes')
    template = 'cis/notes/students/index.html'
    
    return render(
        request,
        template, {
            'menu': menu,
            'page_title': 'Student Notes',
            'accessible_campuses': get_accessible_campuses(request.user),
            'default_campus': get_default_campus(request.user),
            'student_notes_table': build_student_notes_table_config(
                variant='student_notes_index',
                api_url='/ce/api/student-note?format=datatables',
                details_prefix='/ce/student/',
                filter_form_selector='#notes_filter',
            ),
        }
    )

def index(request):
    from myce.component_registry.student import student_actions
    from cis.models.settings import Setting as _Setting

    menu = draw_menu(cis_menu, 'students', 'students')
    template = 'cis/students/index.html'

    regis_key = getattr(settings, 'CAMPUS_CODE_PREFIX', '') + '_cis_registrations'
    onboarding_timeline_start = _Setting.get_value(regis_key, 'starting_date') if hasattr(_Setting, 'get_value') else ''
    onboarding_timeline_end = _Setting.get_value(regis_key, 'tuition_pay_end_date') if hasattr(_Setting, 'get_value') else ''
    _active_term = active_term()
    onboarding_active_term_id = str(_active_term.id) if _active_term else ''

    return render(
        request,
        template, {
            'menu': menu,
            'page_title': 'Students',
            'terms': Term.objects.all().order_by('-code'),
            'accessible_campuses': get_accessible_campuses(request.user),
            'default_campus': get_default_campus(request.user),
            'onboarding_timeline_start': onboarding_timeline_start,
            'onboarding_timeline_end': onboarding_timeline_end,
            'onboarding_active_term_id': onboarding_active_term_id,
            'urls': {
                'add_new': 'cis:student_add_new'
            },
            'students_table': build_students_table_config(
                variant='students_index',
                api_url='/ce/api/student?format=datatables',
                details_prefix='/ce/student/',
                bulk_actions=_filter_all_tab_bulk_actions(
                    student_actions.for_scope('bulk', request.user)
                ),
                bulk_actions_url=reverse('cis:student_bulk_actions'),
                filter_form_selector='#class_section_filter',
            ),
            'dirty_students_table': build_students_table_config(
                variant='dirty_index',
                api_url='/ce/api/student?format=datatables&record_type=dirty',
                details_prefix='/ce/students/',
                bulk_actions=_filter_dirty_tab_bulk_actions(
                    student_actions.for_scope('bulk', request.user)
                ),
                bulk_actions_url=reverse('cis:student_bulk_actions'),
                filter_form_selector='#dirty_students_filter',
            ),
        }
    )


def as_pdf(request, record_id):
    
    import pdfkit
        
    template = 'cis/students/single-page.html'

    record = get_object_or_404(Student, pk=record_id)
    if not can_access_student(request.user, record):
        return JsonResponse({'status': 'error',
            'message': 'You are not authorized to access this student.'}, status=403)
    pdf = record.as_pdf()

    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="student-{record.user.last_name}-{record.user.first_name}.pdf"'

    return response

# Bulk actions whose ids[] are NOT Student ids, so the student campus filter
# must NOT be applied to them. delete_recommendation operates on
# StudentRecommendation ids (a child of an already page-gated student).
_NON_STUDENT_ID_BULK_ACTIONS = {'delete_recommendation'}


def do_bulk_action(request):
    action = request.POST.get('action')
    # Campus-gate the target students centrally: unverified students are always
    # actionable; verified students only if the staff processes a campus they
    # applied at. Filtering ids[] here protects every student-id bulk handler
    # (actions keyed on non-student ids are excluded above).
    ids = request.POST.getlist('ids[]')
    if ids and action not in _NON_STUDENT_ID_BULK_ACTIONS:
        data = request.POST.copy()
        data.setlist('ids[]', processable_student_ids(ids, request.user))
        request.POST = data
    return student_actions.dispatch(request, action)


@student_actions.action('download', label='Download as PDF', icon='fa fa-download', scope=['detail'], slug='download_pdf')
def download_student_pdf(request):
    ids = request.POST.getlist('ids[]')
    if not ids:
        return JsonResponse({'outcome': 'alert', 'status': 'error', 'title': 'Error', 'message': 'No record selected.'})
    return JsonResponse({'outcome': 'open', 'url': reverse('cis:student_pdf', args=[ids[0]])})


@student_actions.action('danger', label='Delete Record', icon='fa fa-trash-alt', scope=['detail'], slug='delete_record')
def delete_student(request):
    ids = request.POST.getlist('ids[]')
    if not ids:
        return JsonResponse({'outcome': 'alert', 'status': 'error', 'title': 'Error', 'message': 'No record selected.'})
    record = get_object_or_404(Student, pk=ids[0])
    try:
        Student.delete_record(record)
        # Not onActionComplete: that ends in location.reload(), which reloads
        # the detail page of a student that no longer exists — inside the
        # iframe, so the user gets a page-load error. onRecordDeleted closes
        # the modal and returns to the index instead, matching the
        # `a.delete` handler and common_methods.js.
        return JsonResponse({
            'outcome': 'call',
            'fn': 'onRecordDeleted',
            'args': {'title': 'Done', 'message': 'Record deleted.', 'status': 'success'},
        })
    except Exception as e:
        return JsonResponse({
            'outcome': 'alert', 'status': 'error', 'title': 'Error',
            'message': f'Unable to delete record. {e}',
        })


@student_actions.action(
    'bulk_only', label='Delete Selected', icon='fas fa-trash-alt', scope=['bulk'],
    btn_class='btn-danger',
    confirm='Are you sure? This will permanently delete selected UNVERIFIED accounts. Verified accounts will be skipped.',
)
def bulk_delete(request):
    ids = request.POST.getlist('ids[]')
    students = Student.objects.filter(id__in=ids)

    verified_count = students.filter(account_verified=True).count()
    unverified = students.filter(account_verified=False)
    deleted_count = 0

    for student in unverified:
        try:
            Student.delete_record(student)
            deleted_count += 1
        except Exception:
            pass

    message = f'Deleted {deleted_count} unverified account(s).'
    if verified_count > 0:
        message += f' Skipped {verified_count} verified account(s).'

    return JsonResponse({
        'outcome': 'call',
        'fn': 'onBulkActionComplete',
        'args': {'title': 'Bulk Delete', 'message': message, 'status': 'success'},
    })


@student_actions.action(
    'profile_review', label='Mark Not Dirty',
    icon='fas fa-check-square', scope=['bulk'], btn_class='btn-success',
)
def bulk_mark_not_dirty(request):
    ids = request.POST.getlist('ids[]')
    if not ids:
        return JsonResponse({'outcome': 'alert', 'status': 'error',
                             'title': 'Error', 'message': 'No record selected.'})
    updated = Student.objects.filter(
        id__in=ids, profile_dirty_at__isnull=False
    ).update(profile_dirty_at=None)
    return JsonResponse({
        'outcome': 'call',
        'fn': 'onBulkActionComplete',
        'args': {'title': 'Profile Reviewed',
                 'message': f'Marked {updated} student(s) as reviewed.',
                 'status': 'success'},
    })


@student_actions.action(
    'profile_review', label='Set Status: Pending',
    icon='fas fa-hourglass-half', scope=['bulk'], btn_class='btn-warning',
    confirm='Set application_status to "pending" for all selected students?',
)
def bulk_set_status_pending(request):
    ids = request.POST.getlist('ids[]')
    if not ids:
        return JsonResponse({'outcome': 'alert', 'status': 'error',
                             'title': 'Error', 'message': 'No record selected.'})
    updated = Student.objects.filter(id__in=ids).update(application_status='pending')
    return JsonResponse({
        'outcome': 'call',
        'fn': 'onBulkActionComplete',
        'args': {'title': 'Status Updated',
                 'message': f'Set status to pending for {updated} student(s).',
                 'status': 'success'},
    })


@student_actions.action(
    'profile_review', label='Change Application Status',
    icon='fas fa-exchange-alt', scope=['detail', 'bulk'], method='form',
)
def change_application_status(request):
    from cis.forms.student import ChangeApplicationStatusForm
    ids = request.POST.getlist('ids[]')
    template = 'cis/students/bulk_action.html'

    if request.POST.get('action_confirmed'):
        form = ChangeApplicationStatusForm(student_ids=ids, data=request.POST)
        if form.is_valid():
            updated = form.save(request)
            return JsonResponse({
                'outcome': 'call',
                'fn': 'onActionComplete',
                'args': {'title': 'Done',
                         'message': f'Updated application status for {updated} student(s).',
                         'status': 'success'},
            })
        return JsonResponse({
            'message': 'Please correct the errors and try again.',
            'errors': form.errors.as_json(),
        }, status=400)

    form = ChangeApplicationStatusForm(student_ids=ids)
    html = render_to_string(template, {
        'title': 'Change Application Status',
        'form': form,
        'form_action': reverse('cis:student_bulk_actions'),
        'action_slug': 'change_application_status',
        'ids': ids,
    }, request=request)
    return JsonResponse({'outcome': 'modal', 'html': html})


@student_actions.action('bulk_only', label='Add Payment', scope=['detail'], method='form')
def add_payment(request):
    from cis.forms.student import BulkPaymentForm
    ids = request.POST.getlist('ids[]')
    template = 'cis/students/bulk_action.html'

    if request.POST.get('action_confirmed'):
        form = BulkPaymentForm(data=request.POST)
        if form.is_valid():
            form.save(request)
            return JsonResponse({
                'outcome': 'call',
                'fn': 'onBulkActionComplete',
                'args': {'title': 'Done', 'message': 'Successfully added payment(s)', 'status': 'success'},
            })
        return JsonResponse({
            'message': 'Please correct the errors and try again.',
            'errors': form.errors.as_json(),
        }, status=400)

    form = BulkPaymentForm(ids)
    html = render_to_string(template, {
        'title': 'Add School Payment',
        'form': form,
        'form_action': reverse('cis:student_bulk_actions'),
        'action_slug': 'add_payment',
        'ids': ids,
    }, request=request)
    return JsonResponse({'outcome': 'modal', 'html': html})

@student_actions.action('verify_mark', label='Mark as Verified', icon='fa fa-check', scope=['detail'])
def mark_as_verified(request):
    ids = request.POST.getlist('ids[]')
    students = Student.objects.filter(id__in=ids)
    students.update(account_verified=True)
    students.update(verification_id=None)
    return JsonResponse({
        'outcome': 'call',
        'fn': 'onActionComplete',
        'args': {'title': 'Success', 'message': 'Successfully set account as verified.', 'status': 'success'},
    })

@student_actions.action('email', label='Send ID Assigned Email', icon='fa fa-envelope', scope=['detail'])
def send_id_assigned_email(request):
    ids = request.POST.getlist('ids[]')
    students = Student.objects.filter(id__in=ids)

    import re
    from cis.settings.registration_email import registration_email
    email_settings = registration_email.from_db()
    pattern = email_settings.get('id_verify_regex', r'^H\d{7}$')

    recipient_list = []
    for student in students:
        psid = student.user.psid
        try:
            if bool(re.match(pattern, str(psid))):
                student.send_psid_assigned_email()
                student.add_note(request.user, 'Sent ID assigned email')
                recipient_list.append(student.user.email)
        except Exception as e:
            print(e)

    status = 'success'
    message = f'Successfully sent email(s) to <br>' + '<br>'.join(recipient_list)
    if len(recipient_list) == 0:
        message = f'No student ID matched the pattern {pattern}.'
        status = 'warning'

    return JsonResponse({'outcome': 'alert', 'status': status, 'title': 'Send ID Assigned Email', 'message': message})

@student_actions.action('verification', label='Mark as UnVerified', icon='fa fa-edit', scope=['detail', 'bulk'])
def mark_as_unverified(request):
    ids = request.POST.getlist('ids[]')
    students = Student.objects.filter(id__in=ids, account_verified=True)
    students = students.filter(Q(user__psid__isnull=True) | Q(user__psid='-'))

    recipient_list = []
    for student in students:
        student.reset_verification_id()
        student.user.psid = None
        student.user.save()
        student.add_note(request.user, 'Marked account as un-verified')
        recipient_list.append(student.user.email)

    status = 'success'
    message = 'Successfully set account as \'unverified\' <br>' + '<br>'.join(recipient_list)
    if len(recipient_list) == 0:
        message = 'No students pending account verification found. Only students whose account has not been sent to SIS can be marked as unverified.'
        status = 'warning'

    return JsonResponse({'outcome': 'alert', 'status': status, 'title': 'Mark as UnVerified', 'message': message})

@student_actions.action('verification', label='Send Verification Link', icon='fa fa-envelope', scope=['detail', 'bulk'])
def resend_verification_link(request):
    ids = request.POST.getlist('ids[]')
    students = Student.objects.filter(id__in=ids, account_verified=False)

    recipient_list = []
    for student in students:
        student.send_verification_request_email()
        student.add_note(request.user, 'Resent account verification link')
        recipient_list.append(student.user.email)

    message = 'Successfully sent email(s) to <br>' + '<br>'.join(recipient_list)
    if students.count() == 0:
        message = 'No students pending account verification found.'

    return JsonResponse({'outcome': 'alert', 'status': 'success', 'title': 'Send Verification Link', 'message': message})

@student_actions.action('verification', label='Get Verification Link', icon='fa fa-link', scope=['detail', 'bulk'])
def get_verification_link(request):
    ids = request.POST.getlist('ids[]')
    students = Student.objects.filter(id__in=ids, account_verified=False)

    recipient_list = []
    index = 1
    for student in students:
        recipient_list.append(
            f'{student}<br><span id=\'copy_to_{index}\'>{student.verify_email}</span>&nbsp;&nbsp;<i title=\'copy to clipboard\' class=\'fas fa fa-paste copy-clipboard\' data-clipboard-target=\'#copy_to_{index}\' style=\'cursor: pointer\'></i>'
        )
        index += 1
        student.add_note(request.user, 'Generated account verification link')

    message = 'Verification Links are below<br><br>' + '<br>'.join(recipient_list)
    if students.count() == 0:
        message = 'No students pending account verification found.'

    return JsonResponse({'outcome': 'alert', 'status': 'success', 'title': 'Get Verification Link', 'message': message})

@student_actions.action('password', label='Get Password Reset Link', icon='fa fa-link', scope=['detail'])
def get_password_reset_link(request):
    ids = request.POST.getlist('ids[]')
    students = Student.objects.filter(id__in=ids, account_verified=True)

    recipient_list = []
    index = 1
    for student in students:
        recipient_list.append(
            f'{student}<br><span id=\'copy_to_{index}\'>{student.user.get_password_reset_link()}</span>&nbsp;&nbsp;<i title=\'copy to clipboard\' class=\'fas fa fa-paste copy-clipboard\' data-clipboard-target=\'#copy_to_{index}\' style=\'cursor: pointer\'></i>'
        )
        index += 1
        student.add_note(request.user, 'Generated password reset link')

    message = 'Password Reset Link(s) are below<br><br>' + '<br>'.join(recipient_list)
    if len(recipient_list) == 0:
        message = 'No students with verified account found.'

    return JsonResponse({'outcome': 'alert', 'status': 'success', 'title': 'Get Password Reset Link', 'message': message})

@student_actions.action('password', label='Send Password Reset Link', icon='fa fa-envelope', scope=['detail', 'bulk'])
def send_password_reset_link(request):
    ids = request.POST.getlist('ids[]')
    students = Student.objects.filter(id__in=ids, account_verified=True)

    recipient_list = []
    for student in students:
        if student.user.send_password_reset_email():
            recipient_list.append(f'Sent email to {student.user.email}')
        else:
            recipient_list.append(f'Failed to send email to {student.user.email}')
        student.add_note(request.user, 'Sent password reset link')

    message = 'Summary<br><br>' + '<br>'.join(recipient_list)
    if students.count() == 0:
        message = 'No students with verified account found.'

    return JsonResponse({'outcome': 'alert', 'status': 'success', 'title': 'Send Password Reset Link', 'message': message})

def recommendations(request):
    menu = draw_menu(cis_menu, 'students', 'recommendations')
    template = 'cis/students/recommendations.html'
    
    act_term = active_term()
    return render(
        request,
        template, {
            'menu': menu,
            'yes_no': YES_NO_OPTIONS,
            'active_term': act_term,
            'terms': Term.objects.all().order_by('-code'),
            'page_title': 'Student Recommendations',
            'accessible_campuses': get_accessible_campuses(request.user),
            'default_campus': get_default_campus(request.user),
            'recommendations_table': build_student_recommendations_table_config(
                variant='recommendations_index',
                api_url='/ce/api/student_recommendation?format=datatables',
                bulk_actions=student_actions.for_scope('bulk', request.user),
                bulk_actions_url=reverse('cis:student_bulk_actions'),
                filter_form_selector='#recommendations_filter',
            ),
            'missing_recommendation_table': build_students_table_config(
                variant='missing_recommendation_index',
                api_url='/ce/api/student?format=datatables&record_type=missing_recommendation&registration_term_id=' + str(act_term.id),
                details_prefix='/ce/student/',
                filter_form_selector='#missing_filter',
            ),
        }
    )

def support_docs(request):
    menu = draw_menu(cis_menu, 'students', 'support_docs')
    template = 'cis/students/support_docs.html'
    
    return render(
        request,
        template, {
            'menu': menu,
            'yes_no': YES_NO_OPTIONS,
            'page_title': 'Support Doc(s).',
            'terms': Term.objects.all().order_by('-code'),
            'accessible_campuses': get_accessible_campuses(request.user),
            'default_campus': get_default_campus(request.user),
            'support_docs_table': build_support_docs_table_config(
                variant='support_docs_index',
                api_url='/ce/api/student_support_docs?format=datatables',
                bulk_actions=support_docs_actions.for_scope('bulk', request.user),
                bulk_actions_url=reverse('cis:support_docs_bulk_actions'),
                filter_form_selector='#support_docs_filter',
            ),
        }
    )


def support_docs_bulk_actions(request):
    action = request.POST.get('action')
    return support_docs_actions.dispatch(request, action)


@support_docs_actions.action('status', label='Mark Status', icon='fas fa-edit', scope=['bulk'])
def mark_support_doc_status(request):
    from cis.forms.student import MarkSupportDocStatusForm
    template = 'cis/students/bulk_delete.html'
    ids = request.POST.getlist('ids[]')

    if request.POST.get('action_confirmed'):
        form = MarkSupportDocStatusForm(doc_ids=ids, data=request.POST)
        if form.is_valid():
            form.save(request)
            return JsonResponse({
                'outcome': 'call',
                'fn': 'onBulkActionComplete',
                'args': {'title': 'Done', 'message': 'Successfully updated document status', 'status': 'success'},
            })
        return JsonResponse({
            'message': 'Please correct the errors and try again.',
            'errors': form.errors.as_json(),
        }, status=400)

    form = MarkSupportDocStatusForm(doc_ids=ids)
    html = render_to_string(template, {
        'title': 'Mark Document Status',
        'form': form,
        'form_action': reverse('cis:support_docs_bulk_actions'),
        'action_slug': 'mark_support_doc_status',
        'ids': ids,
    }, request=request)
    return JsonResponse({'outcome': 'modal', 'html': html})

@student_actions.action('verification', label='Look up SIS ID', icon='fa fa-id-card', btn_class='btn-info', scope=['detail'], method='form')
def lookup_sis_id(request):
    from cis.services.tenant_services import get_tenant_service
    ethos_identity = get_tenant_service('ethos_identity')

    ids = request.POST.getlist('ids[]')
    if not ids:
        return JsonResponse({'outcome': 'alert', 'status': 'error', 'message': 'No student selected.'})

    try:
        student = Student.objects.select_related('user').get(pk=ids[0])
    except Student.DoesNotExist:
        return JsonResponse({'outcome': 'alert', 'status': 'error', 'message': 'Student not found.'})

    if request.POST.get('action_confirmed'):
        person = {
            'id': (request.POST.get('new_sis_id') or '').strip() or None,
            'bannerid': (request.POST.get('new_psid') or '').strip() or None,
            'username': (request.POST.get('new_username') or '').strip() or None,
        }

        changes, error = ethos_identity.apply_ethos_identity(student, person, actor=request.user)

        if error:
            return JsonResponse({
                'outcome': 'alert', 'status': 'error',
                'message': f'Could not save user — conflict with existing record: {error}',
            })

        if not changes:
            return JsonResponse({
                'outcome': 'alert', 'status': 'info',
                'message': 'No fields changed.',
            })

        return JsonResponse({
            'outcome': 'call', 'fn': 'onActionComplete',
            'args': {'title': 'Success', 'message': 'SIS identity updated from Ethos.', 'status': 'success'},
        })

    type_id = ethos_identity.get_alt_credential_type_id()
    if not type_id:
        return JsonResponse({
            'outcome': 'alert', 'status': 'error',
            'message': 'alternativeCredentials type UUID not configured in SIS settings.',
        })

    person = ethos_identity.lookup_ethos_person_for_student(student, type_id=type_id)
    if not person:
        return JsonResponse({
            'outcome': 'alert', 'status': 'warning',
            'message': 'No matching person found in Ethos.',
        })

    rows = [
        ('SIS ID', str(student.sis_id or ''), person.get('id') or ''),
        ('PSID', student.user.psid or '', person.get('bannerid') or ''),
        ('Username', student.user.username or '', person.get('username') or ''),
    ]
    has_changes = any(str(cur) != str(new) and new for _, cur, new in rows)

    html = render_to_string('cis/students/lookup_sis_id.html', {
        'title': 'Look up SIS ID',
        'student': student,
        'rows': rows,
        'has_changes': has_changes,
        'new_sis_id': person.get('id') or '',
        'new_psid': person.get('bannerid') or '',
        'new_username': person.get('username') or '',
        'form_action': reverse('cis:student_bulk_actions'),
        'action_slug': 'lookup_sis_id',
        'ids': [str(student.id)],
    }, request=request)
    return JsonResponse({'outcome': 'modal', 'html': html})


@student_actions.action('verification', label='Look up by Banner ID', icon='fa fa-search', btn_class='btn-info', scope=['detail'], method='form')
def lookup_by_banner_id(request):
    from cis.services.tenant_services import get_tenant_service
    ethos_identity = get_tenant_service('ethos_identity')

    ids = request.POST.getlist('ids[]')
    if not ids:
        return JsonResponse({'outcome': 'alert', 'status': 'error', 'message': 'No student selected.'})

    try:
        student = Student.objects.select_related('user').get(pk=ids[0])
    except Student.DoesNotExist:
        return JsonResponse({'outcome': 'alert', 'status': 'error', 'message': 'Student not found.'})

    if not (student.user.psid or '').strip():
        return JsonResponse({
            'outcome': 'alert', 'status': 'warning',
            'message': 'Student has no Banner ID set.',
        })

    if request.POST.get('action_confirmed'):
        person = {
            'id': (request.POST.get('new_sis_id') or '').strip() or None,
            'username': (request.POST.get('new_username') or '').strip() or None,
            'school_email': (request.POST.get('new_secondary_email') or '').strip() or None,
        }

        changes, error = ethos_identity.apply_ethos_identity_by_psid(student, person, actor=request.user)

        if error:
            return JsonResponse({
                'outcome': 'alert', 'status': 'error',
                'message': f'Could not save user — conflict with existing record: {error}',
            })

        if not changes:
            return JsonResponse({
                'outcome': 'alert', 'status': 'info',
                'message': 'No fields changed.',
            })

        return JsonResponse({
            'outcome': 'call', 'fn': 'onActionComplete',
            'args': {'title': 'Success', 'message': 'SIS identity updated from Ethos.', 'status': 'success'},
        })

    person = ethos_identity.lookup_ethos_person_by_psid(student)
    if not person:
        return JsonResponse({
            'outcome': 'alert', 'status': 'warning',
            'message': 'No matching person found in Ethos.',
        })

    rows = [
        ('SIS ID', str(student.sis_id or ''), person.get('id') or ''),
        ('Username (alt)', student.user.alt_username or '', person.get('username') or ''),
        ('Secondary email', student.user.secondary_email or '', person.get('school_email') or ''),
    ]
    has_changes = any(str(cur) != str(new) and new for _, cur, new in rows)

    html = render_to_string('cis/students/lookup_by_psid.html', {
        'title': 'Look up by Banner ID',
        'student': student,
        'rows': rows,
        'has_changes': has_changes,
        'new_sis_id': person.get('id') or '',
        'new_username': person.get('username') or '',
        'new_secondary_email': person.get('school_email') or '',
        'form_action': reverse('cis:student_bulk_actions'),
        'action_slug': 'lookup_by_banner_id',
        'ids': [str(student.id)],
    }, request=request)
    return JsonResponse({'outcome': 'modal', 'html': html})


def faa_index(request):
    menu = draw_menu(cis_menu, 'students', 'faas')
    template = 'cis/students/faa_index.html'
    
    act_term = active_term()
    return render(
        request,
        template, {
            'menu': menu,
            'active_term': act_term,
            'terms': Term.objects.all().order_by('-code'),
            'page_title': 'Scholarship Requests',
            'accessible_campuses': get_accessible_campuses(request.user),
            'default_campus': get_default_campus(request.user),
            'api_url': '/ce/api/student_tuitionassistance?format=datatables',
            'missing_faa_api_url': mark_safe(
                '/ce/api/student?format=datatables&record_type=missing_faa&term_id=' + str(act_term.id)
            )
        }
    )

def delete_faa(request, record_id):
    record = get_object_or_404(StudentTuitionAssistance, pk=record_id)

    if not can_access_student(request.user, record.student):
        return JsonResponse({'status': 'error',
            'message': 'You are not authorized to access this student.'}, status=403)

    if True:
        note_text = f'Deleted TA request for {record.term} in {record.status}'
        try:
            record.delete()
            record.student.add_note(request.user, note_text)
            
            data = {
                'status':'success',
                'message':'Success deleted TA request',
            }
        except Exception as e:
            data = {
                'status':'warning',
                'message':f'Unable to delete TA request {e}',
            }
    return JsonResponse(data)

@xframe_options_exempt
def faa(request, record_id):
    """
    Record details page
    """
    template = 'cis/students/faa.html'
    record = get_object_or_404(StudentTuitionAssistance, pk=record_id)

    if not can_access_student(request.user, record.student):
        return render(request, 'cis/not_authorized.html',
            {'message': 'You are not authorized to access this student.'}, status=403)

    if request.GET.get('delete_taa_file'):
        file_id = request.GET.get('delete_taa_file')

        file = StudentTuitionAssistanceDocument.objects.filter(
            tuition_assistance=record,
            id=file_id
        )

        if not file.exists():
            messages.add_message(
                request,
                messages.SUCCESS,
                f'Unable to complete request',
                'list-group-item-danger'
            )
        else:
            file.delete()
            messages.add_message(
                request,
                messages.SUCCESS,
                f'Successfully deleted file',
                'list-group-item-success'
            )
            return redirect('cis:faa', record_id=record.id)

    form = ManageFAAForm(record)
    if request.method == 'POST':
        form = ManageFAAForm(record, request.POST)

        if form.is_valid():
            try:
                record = form.save(request)
                if request.FILES:
                    faa_file = StudentTuitionAssistanceDocument(
                        tuition_assistance=record,
                        media=request.FILES['file']
                    )

                    faa_file.save()
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully updated FAA Request',
                    'list-group-item-success')                
                return redirect('cis:faa', record_id=record.id)
            except Exception as e:
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Please fix the error and try again - ' + str(e),
                    'list-group-item-danger')
        else:
            messages.add_message(
                request,
                messages.SUCCESS,
                'Please fix the error and try again',
                'list-group-item-danger')

    return render(
        request,
        template, {
            'page_title': "Student Tuition Assistance",
            'labels': {
                'all_items': 'All Requests'
            },
            'menu': draw_menu(cis_menu, 'students', 'faas'),
            'record': record.student,
            'form': form,
            'faa': record,
            'faas': StudentTuitionAssistance.objects.filter(
                student=record.student
            ).order_by(
                '-created_on'
            ),
            'registrations_url': mark_safe(f'/ce/api/registration?format=datatables&student={record.student.id}'),
            'registrations_table': build_registrations_table_config(
                variant='student_detail',
                api_url=f'/ce/api/registration?format=datatables&student={record.student.id}',
            ),
            'recommendations_url': mark_safe(f'/ce/api/student_recommendation?format=datatables&student={record.student.id}'),
            'agreements_url': mark_safe(f'/ce/api/student_agreement?format=datatables&student={record.student.id}'),
            'parent_consents_url': mark_safe(f'/ce/api/parent_consent?format=datatables&student={record.student.id}'),
            'note_api_url': mark_safe('/ce/api/student-note/?student_id='+str(record.student.id)+'&format=datatables'),
            'transactions_api_url': mark_safe('/ce/student_transactions/api/transactions/?format=datatables&student_id='+str(record.student.id)),
            'active_term': active_term(),
            'terms': Term.objects.all(),
            'is_registration_open': True,
            'registration_terms': Term.objects.all()
        })


def _history_diffs(history_manager, since):
    """Walk history records >= since and yield per-field diffs."""
    records = list(history_manager.filter(history_date__gte=since)
                                  .order_by('history_date'))
    if not records:
        return []
    out = []
    for rec in records:
        prior = rec.prev_record
        if prior is None:
            continue
        delta = rec.diff_against(prior)
        for change in delta.changes:
            out.append({
                'history_date': rec.history_date,
                'field': change.field,
                'old': change.old,
                'new': change.new,
            })
    return out


@xframe_options_exempt
def student_profile_changes(request, pk):
    """Render the change-history modal: all field deltas in Student + CustomUser
    history records dated at or after ``student.profile_dirty_at``.

    Loaded inside an iframe by the `.record-details` modal handler in main.js,
    hence ``@xframe_options_exempt``.
    """
    student = get_object_or_404(Student, pk=pk)
    if not can_access_student(request.user, student):
        return render(request, 'cis/not_authorized.html',
            {'message': 'You are not authorized to access this student.'}, status=403)
    since = student.profile_dirty_at

    diffs = []
    if since:
        diffs.extend(_history_diffs(student.history, since))
        diffs.extend(_history_diffs(student.user.history, since))
        diffs.sort(key=lambda d: d['history_date'])

    return render(request, 'cis/students/_dirty_changes_modal.html', {
        'student': student,
        'since': since,
        'diffs': diffs,
    })
