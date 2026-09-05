"""
Class Sections
"""

import csv, io, logging, uuid

from django.db.models.functions import TruncDate
from django.conf import settings
from django.db.models import Q, Count
from django.contrib import messages
from django.utils.safestring import mark_safe
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.http import JsonResponse, HttpResponse

from django.views.decorators.clickjacking import xframe_options_exempt
from django.template.context_processors import csrf

from crispy_forms.utils import render_crispy_form
from paramiko import SSHClient, AutoAddPolicy, RSAKey

from rest_framework import viewsets
from rest_framework.exceptions import ValidationError

from rest_framework.decorators import api_view 
from rest_framework.response import Response

from cis.utils import (
    get_uploaded_file,
    get_default_campus,
    registration_terms as get_registration_terms,
    can_edit_campus_section,
    user_has_faculty_role
)
from cis.campus_gate import scope_queryset_by_campus, campus_gate, get_accessible_campuses, processable_ids

from ..models.customuser import CustomUser
from cis.models.term import Term
from cis.models.course import CourseAdministrator
from cis.models.section import (
    ClassSection, ClassSectionSyllabi,
    StudentRegistration
)
from ..models.course import Campus
from cis.forms.section import (
    ClassSectionForm, ClassSectionUploadForm,
    SectionSyllabiForm, HighSchoolClassOfferingForm
)

from cis.models.highschool import HighSchool, HighSchoolClassOffering
from cis.models.teacher import Teacher
from cis.models.note import ClassSectionNote

from cis.forms.section import AddNewHighSchoolClassOfferingForm

from cis.menu import cis_menu, draw_menu
from cis.services.importers.class_section_schema import ClassSectionRow
from cis.services.table_configs import get_table_config
build_registrations_table_config = get_table_config('registrations_table').build_config
build_sections_table_config = get_table_config('sections_table').build_config

from myce.component_registry.class_section_index import class_section_index_tabs

logger = logging.getLogger(__name__)

from ..serializers.class_section import (
    ClassSectionSerializer,
    ClassSectionSyllabiSerializer
)
from ..serializers.note import ClassSectionNoteSerializer
from ..serializers.registration import RegistrationSummarySerializer

from cis.utils import CIS_user_only, active_term, user_has_cis_role, registration_terms

from cis.views.eager import (
    eager_queryset,
    with_class_section_note_related,
    with_class_section_related,
    with_class_section_syllabi_related,
)


class RegistrationSummaryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RegistrationSummarySerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        course_id = self.request.GET.get('course_id')
        subject_id = self.request.GET.get('subject_id')
        highschool_id = self.request.GET.get('highschool_id')
        term_id = self.request.GET.get('term_id')
        academic_year_id = self.request.GET.get('academic_year_id')
        records_type = self.request.GET.get('records_type')

        records = StudentRegistration.objects.all()

        if course_id:
            records = records.filter(
                class_section__course__id=course_id
            )

        if subject_id:
            records = records.filter(
                class_section__course__cohort__id=subject_id
            )

        if highschool_id:
            records = records.filter(
                class_section__highschool__id=highschool_id
            )

        if term_id:
            if term_id == '-2':
                records = records.filter(
                    class_section__term__in=registration_terms()
                )
            else:
                records = records.filter(
                    class_section__term__id=term_id
                )
        
        if academic_year_id:
            records = records.filter(
                class_section__term__academic_year__id=academic_year_id
            )

        if records_type == 'by_registration_status':
            records = records.values(
                'status'
            ).order_by(
                'status'
            ).annotate(
                count=Count('status')
            )
            return records

        if records_type == 'by_date':
            records = records.values(
                'created_on__date'
            ).annotate(
                count=Count('id')
            )
            return records
        
        if records_type == 'by_students':
            records = records.annotate(
                created_on__date=TruncDate('created_on')
            ).values('created_on__date').annotate(
                count=Count('student', distinct=True)
            ).order_by('created_on__date')
            return records
        
        if records_type == 'by_student_created':
            records = records.annotate(
                created_on__date=TruncDate('student__user__created_at')
            ).values('created_on__date').annotate(
                count=Count('student', distinct=True)
            ).order_by('created_on__date')
            return records
        
        if records_type == 'by_highschool_student_created':
            records = records.annotate(
                created_on__date=TruncDate('student__user__created_at')
            ).values(
                'student__highschool__name'
            ).annotate(
                count=Count('student', distinct=True)
            ).order_by('student__highschool__name')
            return records
                    
        if records_type == 'by_highschool_registration_created':
            records = records.annotate(
                created_on__date=TruncDate('student__user__created_at')
            ).values(
                'status',
                'student__highschool__name'
            ).annotate(
                count=Count('id')
            ).order_by('student__highschool__name')
            return records
            
        return records.values(
                'status'
            ).order_by(
                'status'
            ).annotate(
                count=Count('status')
            ).values(
                'status',
                'count',
                'class_section__course__name',
                'student__highschool__name',
                'class_section__term__label',
                'class_section__term__code',
                'class_section__term__academic_year__name'
            )

@eager_queryset(with_class_section_syllabi_related)
class ClassSectionSyllabiViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ClassSectionSyllabiSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        class_id = self.request.GET.get('class_id')
        term = self.request.GET.get('term', str(active_term().id)).strip()
        roster_status = self.request.GET.get('roster_status', None)

        if class_id:
            return ClassSectionSyllabi.objects.filter(
                class_sections__id=class_id
            )
        
        if term:
            records = ClassSectionSyllabi.objects.filter(
                class_sections__term__id=term
            )
        
            if roster_status:
                records = records.filter(
                    class_sections__roster_status=roster_status
                )

            return records
        return ClassSectionSyllabi.objects.none()


@eager_queryset(with_class_section_note_related)
class ClassSectionNoteViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ClassSectionNoteSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        class_id = self.request.GET.get('class_id')
        term = self.request.GET.get('term', str(active_term().id)).strip()
        roster_status = self.request.GET.get('roster_status', None)
        grade_status = self.request.GET.get('grade_status', None)

        if class_id:
            return ClassSectionNote.objects.filter(
                class_section__id=class_id
            )
        
        if term:
            records = ClassSectionNote.objects.filter(
                class_section__term__id=term
            )
        
            if roster_status:
                records = records.filter(
                    class_section__roster_status=roster_status
                )
            
            if grade_status:
                records = records.filter(
                    class_section__grade_status=grade_status
                )

            return records
        return ClassSectionNote.objects.none()

@eager_queryset(with_class_section_related)
class ClassesRegisteredByCampusViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ClassSectionSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        campus_id = self.request.GET.get('campus_id', '').strip()
        term_id = self.request.GET.get('term_id', '').strip()

        if not term_id:
            term_id = active_term().id

        class_section_ids = StudentRegistration.objects.filter(
            class_section__course__campus__id=campus_id,
            class_section__term__id=term_id
        ).distinct(
            'class_section__id'
        ).values_list(
            'class_section__id', flat=True
        )

        records = ClassSection.objects.filter(
            id__in=class_section_ids
        )
        return records

@eager_queryset(with_class_section_related)
class ClassSectionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ClassSectionSerializer

    def get_queryset(self):
        try:
            term = self.request.GET.get('term', str(active_term().id)).strip()
            campus = self.request.GET.get('campus', '').strip()
            academic_year_id = self.request.GET.get('academic_year_id', '').strip()
            course = self.request.GET.getlist('course', None)
            subject = self.request.GET.getlist('subject', None)
            class_number = self.request.GET.get('class_number', None)
            location = self.request.GET.get('location', None)
            roster_status = self.request.GET.get('roster_status', None)
            grade_status = self.request.GET.get('grade_status', None)
            highschool_id = self.request.GET.get('highschool_id')
            cte_id = self.request.GET.get('cte_id')
            teacher_id = self.request.GET.get('teacher_id')
            status = self.request.GET.get('status')
            instruction_mode = self.request.GET.get('instruction_mode')

            record_type = self.request.GET.get('type')

            current_grade_level = self.request.GET.get('current_grade_level', None)

            records = None
            if class_number:
                records = ClassSection.objects.filter(
                    class_number=class_number,
                    term__id=term
                )
            else:
                if term == 'registration_terms':
                    regis_terms = get_registration_terms()
                    records = ClassSection.objects.filter(
                        term__in=regis_terms
                    )
                    term = '-1'

                # PT-fuzz: at this point `term` is either the active-term UUID
                # (default), the '-1' "all terms" sentinel, or a caller-supplied
                # value. Any non-UUID, non-'-1' value (e.g. a term *code* like
                # '202630') must not reach the UUID-typed `term__id` filter, which
                # raises django.core.exceptions.ValidationError -> HTTP 500 (the
                # method's `except ValueError` does NOT catch it). Mirror the PT-1
                # idiom (cis/views/student.py): invalid term -> empty result set.
                # The 'registration_terms' branch above already rewrote term to
                # '-1', so it is preserved and skips this guard.
                if term and term != '-1':
                    try:
                        uuid.UUID(str(term))
                    except (ValueError, AttributeError, TypeError):
                        return ClassSection.objects.none()

                if term and term != '-1':

                    if subject:
                        records = ClassSection.objects.filter(
                            term__id=term,
                            course__cohort__id__in=subject
                        ).all()
                    else:
                        records = ClassSection.objects.filter(
                            term__id=term
                        ).all()

                    if status:
                        records = records.filter(
                            status__iexact=status
                        )

                    if course:
                        course_ids = course
                        records = records.filter(course__id__in=course_ids)
                    else:
                        if not user_has_cis_role(self.request.user):
                            records = records.filter(
                                # course__catalog_number__lt=300
                            )

                    if not user_has_cis_role(self.request.user):
                        # remove sections that have a high school
                        if records:
                            if not highschool_id:
                                records = records.exclude(
                                    highschool__isnull=False
                                )
                else:
                    if not records:
                        records = ClassSection.objects.all()

                if status:
                    records = records.filter(
                        status__iexact=status
                    )

                if current_grade_level:
                    records = records.filter(
                        course__registration_eligibility__contains=current_grade_level
                    )

                if instruction_mode:
                    records = records.filter(
                        instruction_mode__iexact=instruction_mode
                    )

                if highschool_id:
                    if cte_id:
                        records = records.filter(
                            Q(highschool__id=highschool_id) | Q(highschool__id=cte_id)
                        )
                    else:
                        records = records.filter(
                            highschool__id=highschool_id
                        )

                if academic_year_id:
                    records = records.filter(
                        term__academic_year__id=academic_year_id
                    )
                    
                if teacher_id:
                    # Same PT-1 idiom as the `term` guard above: teacher__id is
                    # UUID-typed, so a malformed client value raises
                    # ValidationError (an HTTP 500 the enclosing `except
                    # ValueError` does not catch) before any role scoping below
                    # gets a chance to run. Treat it as "no match".
                    try:
                        uuid.UUID(str(teacher_id))
                    except (ValueError, AttributeError, TypeError):
                        return ClassSection.objects.none()
                    records = records.filter(
                        teacher__id=teacher_id
                    )

                try:
                    if roster_status:
                        records = records.filter(
                            roster_status=roster_status
                        )

                    if grade_status:
                        records = records.filter(
                            grade_status=grade_status
                        )

                    if campus and campus != '-1':
                        records = records.filter(course__campus__id=campus)

                    if location:
                        records = records.filter(location__id=location)

                    if course:
                        course_ids = course
                        records = records.filter(course__id__in=course_ids)
                except:
                    pass

            if record_type:
                if record_type in ['has_visit_to_other_section', 'missing_visit']:
                    from class_visit.models import VisitSchedule
                    classes_with_visits = VisitSchedule.objects.filter()

                    if term:
                        classes_with_visits = classes_with_visits.filter(
                            class_sections__term__id=term
                        )
                    if course:
                        classes_with_visits = classes_with_visits.filter(
                            class_sections__course__id=course
                        )

                    records = records.exclude(
                        id__in=classes_with_visits.values_list(
                            'class_sections__id', flat=True
                        )
                    )
                
                if record_type == 'non-web':
                    records = records.exclude(
                        Q(instruction_mode__iexact='web')
                    )
                    
                if record_type == 'has_visit_to_other_section':
                    for record in records:
                        if not record.has_visit_to_other_section:
                            records = records.exclude(
                                id=record.id
                            )

            
            # Scope to the courses a given user actively administers
            # (CourseAdministrator). Used by the Faculty Coordinator detail
            # page's Class Sections tab.
            #
            # Implemented as a subquery rather than a join
            # (course__courseadministrator__user__id=...) on purpose: a join
            # multiplies section rows by matching admin rows, which would both
            # duplicate sections and inflate the num_students /
            # registered_students Count() annotations added just below.
            #
            # NOTE: despite most PKs in this app being UUIDs, CustomUser.id is
            # a plain integer AutoField — CustomUser subclasses AbstractUser
            # without a custom PK. Guard it as an int, NOT with uuid.UUID()
            # (which would reject every legitimate call). The PT-1 uuid guard
            # earlier in this method is on `term`, which really is a UUID.
            #
            # Fails closed: an unparseable id, or a user who administers
            # nothing, yields an empty queryset — never an unfiltered one.
            course_admin_user_id = self.request.GET.get(
                'course_administrator_user_id')
            if course_admin_user_id:
                try:
                    course_admin_user_id = int(course_admin_user_id)
                except (ValueError, TypeError):
                    return ClassSection.objects.none()
                administered_course_ids = CourseAdministrator.objects.filter(
                    user__id=course_admin_user_id,
                    status__iexact='active',
                ).exclude(course__isnull=True).values('course')
                records = records.filter(course__in=administered_course_ids)

            records = records.annotate(
                num_students=Count('studentregistration'),
                applied_students=Count('studentregistration', filter=Q(studentregistration__status__in=['applied', 'approved'])),
                registered_students=Count('studentregistration', filter=Q(studentregistration__status='registered')),
            )

            # PT-25: role-based ownership checks. The endpoint stays reachable by
            # all roles (it is even whitelisted in LoginRequiredMiddleware); scoping
            # is enforced here at the end of the queryset.
            #  - CIS ('ce') staff: unrestricted (multi-tenant listing).
            #  - highschool_admin: may only pass a highschool_id they administer.
            #  - instructor: scoped to the sections they teach.
            #  - faculty: a teacher_id must be one of their visible instructors.
            user = self.request.user
            if not user_has_cis_role(user):
                from cis.utils import (
                    user_has_highschool_admin_role,
                    user_has_instructor_role,
                )
                from cis.services.faculty_scope import visible_teachers
                if user_has_highschool_admin_role(user):
                    if highschool_id:
                        # Imported locally: highschool_admin.views.utils ->
                        # cis.views.ajax -> ... -> cis.views.section would be a
                        # circular import at module load.
                        import importlib.util
                        if importlib.util.find_spec('highschool_admin.highschool_admin'):
                            from highschool_admin.highschool_admin.views.utils import get_user_highschools
                        else:
                            from highschool_admin.views.utils import get_user_highschools
                        if not get_user_highschools(self.request).filter(
                            id=highschool_id
                        ).exists():
                            from rest_framework.exceptions import PermissionDenied
                            raise PermissionDenied('High school not in your scope.')
                elif user_has_instructor_role(user):
                    records = records.filter(teacher__user=user)
                elif user_has_faculty_role(user):
                    # Faculty -> teacher assignment (spec 2026-08-11): the
                    # faculty teacher-detail page loads this endpoint with a
                    # teacher_id, so a teacher_id outside the caller's visible
                    # set must yield nothing.
                    #
                    # Only the teacher_id path is scoped. The same endpoint
                    # backs the faculty portal's Class Sections and Offered
                    # Classes pages, which pass no teacher_id; narrowing those
                    # by visible_teachers() would change what faculty see
                    # before any assignment row exists, which the spec's
                    # rollout ("purely additive") rules out. Sections with no
                    # instructor yet would disappear from Offered Classes too.
                    if teacher_id:
                        try:
                            uuid.UUID(str(teacher_id))
                        except (ValueError, AttributeError, TypeError):
                            # Same idiom as the PT-1 term guard above: a
                            # malformed id is "no match", not a 500.
                            return ClassSection.objects.none()
                        if not visible_teachers(user).filter(
                                id=teacher_id).exists():
                            return ClassSection.objects.none()

            records = scope_queryset_by_campus(records, self.request.user)
            return records
        except ValueError as e:
            print(e)
            return ClassSection.objects.none()
        
def manage_courseoffering(request):
    
    if request.method == 'GET':
        """
        Remove offering from high school
        """
        if request.GET.get('action') == 'remove_class_offering':
            try:
                offering = HighSchoolClassOffering.objects.get(
                    class_section__id=request.GET.get('section_id'),
                    highschool__id=request.GET.get('highschool_id')
                )
                if offering.remove_offerings():
                    return JsonResponse({
                        'status': 'success',
                        'message': 'Successfully removed offering'
                        })
                else:
                    return JsonResponse({
                        'status': 'error',
                        'message': 'Unable to remove offering. There could be students registered in the class.'
                        })
            except HighSchoolClassOffering.DoesNotExist:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Unable to find associated offering, looks like invalid information was sent or the class is F2F section'
                    })

        # PT-35: the `highschoolclassoffering_roomalias` action was removed.
        # It performed a CSRF-unprotected GET write to `room_alias`. The
        # room_alias field is now edited only through the section edit form
        # (cis/forms/section.py), which is CSRF-protected.
        return JsonResponse({
            'status': 'error',
            'message': 'invalid action passed'
        })

    if request.method == 'POST':
        """
        Refresh add new offering form when term is changed
        """
        if request.POST.get('action') == 'refresh_add_new_offering_form':
            form = AddNewHighSchoolClassOfferingForm(initial=request.POST)

            ctx = {}
            ctx.update(csrf(request))
            form_html = render_crispy_form(form, context=ctx)

            data = {
                'status':'status',
                'form_html':form_html,
            }
            return JsonResponse(data)

        """
        Add New Offering to high school
        """
        if request.POST.get('action') == 'add_new_offering':
            form = AddNewHighSchoolClassOfferingForm(data=request.POST)

            if form.is_valid():
                highschool = HighSchool.objects.filter(
                    pk=form.cleaned_data['highschool']
                )
                class_sections = form.cleaned_data['class_section']

                for section in class_sections:
                    section.add_offerings(highschool)

                data = {
                    'status':'success',
                    'message':'Successfully completed your request'
                }
                return JsonResponse(data)

            ctx = {}
            ctx.update(csrf(request))
            form_html = render_crispy_form(form, context=ctx)

            data = {
                'status':'error',
                'form_html':form_html,
                'message':'There was an error while completing your request. Please try again'
            }
            return JsonResponse(data)

        # Default for any unmatched POST action — mirrors the GET default and
        # the do_bulk_action convention, so the view always returns an
        # HttpResponse instead of falling through to None (a 500).
        return JsonResponse({
            'status': 'error',
            'message': 'invalid action passed'
        })

def do_bulk_action(request):
    action = request.GET.get('action')

    if request.method == 'POST':
        action = request.POST.get('action')
        
    if action == 'change_roster_status':
        return change_roster_status(request)

    if action == 'change_registration_term':
        return change_registration_term(request)

    if action == 'mark_syllabi_as_reviewed':
        return mark_syllabi_as_reviewed(request)

    data = {
        'status': 'success',
        'message': 'invalid action passed'
    }
    return JsonResponse(data)

def change_roster_status(request):
    from cis.forms.section import BulkRosterStatusChangeForm
    template = 'cis/sections/bulk_action.html'
    ids = processable_ids(ClassSection, request.POST.getlist('ids[]'), request.user)

    if request.POST.get('action_confirmed'):
        form = BulkRosterStatusChangeForm(data=request.POST)
        if form.is_valid():
            form.save(request)
            return JsonResponse({
                'outcome': 'call',
                'fn': 'onBulkActionComplete',
                'args': {'message': 'Successfully updated records', 'status': 'success'},
            })
        return JsonResponse({
            'message': 'Please correct the errors and try again.',
            'errors': form.errors.as_json(),
        }, status=400)

    form = BulkRosterStatusChangeForm(ids)
    html = render_to_string(template, {
        'title': 'Change Roster Status',
        'form': form,
        'form_action': reverse('cis:section_bulk_actions'),
    }, request=request)
    return JsonResponse({'outcome': 'modal', 'html': html})

def change_registration_term(request):
    from cis.forms.section import BulkRegistrationTermChangeForm
    template = 'cis/sections/bulk_action.html'
    ids = processable_ids(ClassSection, request.POST.getlist('ids[]'), request.user)

    if request.POST.get('action_confirmed'):
        form = BulkRegistrationTermChangeForm(data=request.POST)
        if form.is_valid():
            form.save(request)
            return JsonResponse({
                'outcome': 'call',
                'fn': 'onBulkActionComplete',
                'args': {'message': 'Successfully updated records', 'status': 'success'},
            })
        return JsonResponse({
            'message': 'Please correct the errors and try again.',
            'errors': form.errors.as_json(),
        }, status=400)

    form = BulkRegistrationTermChangeForm(ids)
    html = render_to_string(template, {
        'title': 'Change Term',
        'form': form,
        'form_action': reverse('cis:section_bulk_actions'),
    }, request=request)
    return JsonResponse({'outcome': 'modal', 'html': html})
    
def mark_syllabi_as_reviewed(request):
    class_section_id = request.GET.get('id')

    class_section = get_object_or_404(ClassSection, pk=class_section_id)
    class_section.syllabi_status = 'reviewed'

    class_section.save()

    data = {
        'status':'success',
        'message':'Successfully saved review',
        'action': 'reload_table'
    }
    return JsonResponse(data)

def delete_syllabi(request, record_id):
    record = get_object_or_404(ClassSectionSyllabi, pk=record_id)
    try:
        record.delete()

        data = {
            'status':'success',
            'message':'Successfully deleted record',
            'action': 'reload'
        }
    except Exception as e:
        data = {
            'status':'error',
            'message':'Unable to complete request.' + str(e),
        }
    return JsonResponse(data)

@campus_gate(ClassSection, mode='json')
def delete_record(request, record_id):
    record = get_object_or_404(ClassSection, pk=record_id)
    try:
        ClassSection.delete_record(record)

        data = {
            'status':'success',
            'message':'Successfully deleted record',
            'action': 'reload'
        }
    except Exception as e:
        data = {
            'status':'error',
            'message':'Unable to complete request.' + str(e),
        }
    return JsonResponse(data)

def course_search(request):
    return render(
        request,
        'cis/sections/course_search.html',
        {
            'page_title': 'Course Search',
            'is_registration_open': True,
            'registration_terms': get_registration_terms(),
            'menu': draw_menu(cis_menu, 'classes', 'course_search')
        })

def ajax(request):
    action = request.GET.get('action')

    if action == 'delete_highschool_class_offering':
        return _delete_class_offering_from_highschool(
            request.GET.get('id', None)
        )
    if action == 'get_teachers_in_highschool':
        return _get_teachers_in_highschool(request.GET.get('highschool', None))
    if action == 'get_courses_for_teacher':
        return _get_courses_for_teacher(
            request.GET.get('teacher'),
            request.GET.get('highschool'))

def _delete_class_offering_from_highschool(offering_id):
    try:
        offering =  HighSchoolClassOffering.objects.get(
            pk=offering_id
        )

        if offering.has_students_from_highschool():
            return JsonResponse({
                'status': 'error',
                'message': 'Unable to delete offering. There are registered students from the high school'
            })

        offering.delete()
        return JsonResponse({
                'status': 'success',
                'message': 'Successfully removed offering'
            })
    except HighSchoolClassOffering.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Invalid ID received'
        })
 
def _get_courses_for_teacher(
        teacher,
        highschool,
        status=['Approved', 'Certified', 'Contingent'],
        format="JSON"):
    try:
        teacher = Teacher.objects.get(pk=teacher)
    except Teacher.DoesNotExist:
        return JsonResponse({
            'message': 'Unable to find teacher',
            'status': 'error'})

    course_certificates = teacher.get_course_certificates().distinct('course')
    if len(course_certificates) <= 0:
        return JsonResponse({'status': 'success', 'records': []})

    course_certificates = course_certificates.filter(
        teacher_highschool__highschool=highschool,
        status__in=status
    )
    result = []
    for certificate in course_certificates:
        result.append(
            {'id': certificate.course.id,
            'name': certificate.course.cohort.designator + ' ' + certificate.course.catalog_number}
        )
    return JsonResponse({'status': 'success', 'records': result})

def _get_teachers_in_highschool(highschool, format="JSON"):
    try:
        highschool = HighSchool.objects.get(pk=highschool)
    except HighSchool.DoesNotExist:
        return JsonResponse({
            'message': 'Unable to find high school',
            'status': 'error'})

    teachers = highschool.teachers_in_highschool()
    result = []
    for teacher in teachers:
        result.append(
            {
                'name': teacher.user.first_name + " " + teacher.user.last_name,
                'id': teacher.id
            }
        )
    return JsonResponse({'status': 'success', 'records': result})

def edit_record(request):
    ajax = request.GET.get('ajax', None)
    base_template = 'cis/logged-base.html' if not ajax else 'cis/ajax-base.html'
    template = 'cis/sections/edit.html'

    if request.method == 'POST':
        record_id = request.POST.get('id')
        record = get_object_or_404(ClassSection, pk=record_id)

        if not can_edit_campus_section(request.user, record):
            data = {
                'status':'error',
                'message':'You cannot edit class sections for this campus',
                'new_record_id':record.id,
                'new_record_name':'',
                'action': ''
            }
            return JsonResponse(data)
        
        form = ClassSectionForm(request.POST, instance=record)
        if form.is_valid():
            record = form.save(commit=False)
            record.save()

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
                'message':'Unable to complete request. ' + str(form.errors),
                'new_record_id':record.id,
                'new_record_name':'',
                'action': ''
            }
            return JsonResponse(data)
    else:
        record_id = request.GET.get('id')
        record = get_object_or_404(ClassSection, pk=record_id)
        form = ClassSectionForm(
            instance=record,
            initial={
                'id':record_id
            }
        )

    return render(
        request,
        template, {
            'form': form,
            'ajax': ajax,
            'base_template': base_template
        })

from myce.component_registry.class_section import class_section_tabs


def tab(request, record_id, tab_slug):
    record = get_object_or_404(ClassSection, pk=record_id)
    return class_section_tabs.render_tab(request, record, tab_slug)


@campus_gate(ClassSection, mode='page')
@xframe_options_exempt
def detail(request, record_id):
    """
    Record details page
    """
    template = 'cis/sections/detail.html'
    record = get_object_or_404(ClassSection, pk=record_id)

    notes = ClassSectionNote.objects.filter(class_section=record).order_by('-createdon')
    syllabi_form = SectionSyllabiForm(
        term=record.term,
        teacher=record.teacher,
        course=record.course
    )

    if request.GET.get('action') == 'download_roster_pdf':
        return record.download_roster_pdf()

    if request.method == 'POST':
        if request.POST.get('add_syllabi', None):
            form = SectionSyllabiForm(
                record.term,
                record.teacher,
                record.course,
                request.POST,
                request.FILES
                )

            if form.is_valid():
                syllabus = form.save()
                for class_section in form.cleaned_data['class_sections']:
                    syllabus.class_sections.add(class_section)

                return redirect('cis:section', record_id=record_id)
            syllabi_form = form
        elif request.POST.get('add_offerings', None):
            form = HighSchoolClassOfferingForm(request.POST)

            if form.is_valid():
                record.add_offerings(form.cleaned_data['highschool'])

                return redirect('cis:section', record_id=record_id)
            add_offerings_form = form
        else:
            form = ClassSectionForm(request.POST, request.FILES, instance=record)

            if form.is_valid():
                record = form.save(commit=False)
                record.save()

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully updated record',
                    'list-group-item-success') 
                return redirect('cis:section', record_id=record_id)
            else:
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Unable to complete request. ' + form.errors,
                    'list-group-item-danger')
                print(form.errors)
    
    return render(
        request,
        template, {
            # 'form': form,
            'page_title': "Section",
            'labels': {
                'all_items': 'All Sections'
            },
            'urls': {
                'add_new': 'cis:section_add_new',
                'all_items': 'cis:sections'
            },
            'menu': draw_menu(cis_menu, 'classes', 'sections'),
            'record': record,
            'detail_tabs': class_section_tabs.for_record(
                request, record,
                url_for=lambda slug: reverse('cis:section_tab', args=[record.id, slug]),
            ),
        })

def import_from_s3(request):
    classes = get_uploaded_file('class_export')

    if not classes:
        logger.error('Unable to read classes export')
        messages.add_message(
            request,
            messages.WARNING,
            'No class export file was found to import.',
            'list-group-item-warning')
        return redirect('cis:section_add_new')

    reader = csv.DictReader(io.StringIO(classes))
    result = ClassSection.import_from_csv(reader)

    if result['status'] == 'success':
        if not result['records']:
            messages.add_message(
                request,
                messages.WARNING,
                'The class export contained no data rows.',
                'list-group-item-warning')
            return redirect('cis:section_add_new')

        file_name = "class_section_import_results.csv"
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{file_name}"'

        writer = csv.writer(response)
        writer.writerow(result['records'][0].keys())
        for row in result['records']:
            writer.writerow(row.values())
        return response

    logger.error(f'Error while processing classes export {result}')
    messages.add_message(
        request,
        messages.WARNING,
        'Unable to import the class export. The administrator has been notified.',
        'list-group-item-danger')
    return redirect('cis:section_add_new')

def import_from_file(request):
    form = ClassSectionUploadForm(request.POST, request.FILES)

    if form.is_valid():
        decoded_file = request.FILES.get('file').read().decode('utf-8-sig', errors='ignore')
        reader = csv.DictReader(io.StringIO(decoded_file))

        result = ClassSection.import_from_csv(reader)
        if result['status'] == 'success':
            if not result['records']:
                messages.add_message(
                    request,
                    messages.WARNING,
                    'The uploaded file contained no data rows.',
                    'list-group-item-warning')
                return redirect('cis:section_add_new')

            file_name = "class_section_import_results.csv"
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
        return redirect('cis:section_add_new')

def update_roster_verification(request):
    form = ClassSectionUploadForm(request.POST, request.FILES)

    if form.is_valid():
        decoded_file = request.FILES.get('file').read().decode('utf-8')
        reader = csv.DictReader(io.StringIO(decoded_file))

        result = ClassSection.update_roster_verification_from_csv(reader)
        if result['status'] == 'success':
            file_name = "roster_verif_results.csv"
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
        return redirect('cis:section_add_new')

def download_section_template(request):
    """Download a blank CSV template with the correct headers for section import."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="section_import_template.csv"'
    writer = csv.writer(response)
    writer.writerow(ClassSectionRow.csv_headers())
    return response

def add_new(request):
    '''
    Add new page
    '''
    base_template = 'cis/logged-base.html'
    template = 'cis/sections/add_new.html'
    ajax = request.GET.get('ajax', None)

    upload_form = ClassSectionUploadForm()

    if request.method == 'POST':
        if request.POST.get('upload_file') == "Import Sections":
            return import_from_file(request)

        form = ClassSectionForm(request.POST)
        ajax = request.POST.get('ajax', None)

        if form.is_valid():
            record = form.save(commit=False)
            record.save()

            if ajax == '1':
                data = {
                    'status':'success',
                    'message':'Successfully added new record',
                    'new_record_id':record.id,
                    'new_record_name':record.name
                }
                return JsonResponse(data)

            messages.add_message(
                request,
                messages.SUCCESS,
                'Successfully added record',
                'list-group-item-success') 
            return redirect('cis:section', record_id=record.id)

        if ajax == '1':
            data = {
                'status':'error',
                'message': ''.join([' '.join(x for x in l) for l in list(form.errors.values())])
            }
            return JsonResponse(data)
    else:
        # form = ClassSectionForm()
        upload_form = ClassSectionUploadForm()

    if ajax == '1':
        base_template = 'cis/ajax-base.html'

    return render(
        request,
        template, {
            # 'form': form,
            'upload_form': upload_form,
            'required_header': ClassSectionRow.csv_headers(),
            'schema_fields': ClassSectionRow.field_definitions(),
            'page_title': "Add New Section",
            'labels': {
                'all_items': 'All Sections'
            },
            'urls': {
                'add_new': 'cis:section_add_new',
                'all_items': 'cis:sections'
            },
            'ajax': ajax,
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'classes', 'sections')
        })

def test_import(request):
    pass
    
def index(request):
    '''
     search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'classes', 'sections')
    template = 'cis/sections/index.html'

    # Tabs contributed by other apps (e.g. the optional `grades` package).
    # Rendered eagerly (lazy=False) — this page has no per-tab AJAX route, so
    # `url_for` is a no-op. With no app registering, this is empty and the
    # template emits no extra nav item or pane.
    extra_tabs = class_section_index_tabs.for_record(request, None, lambda slug: '#')
    for slug, tab in extra_tabs.items():
        # This page has no per-tab AJAX route, so a tab registered as lazy
        # would leave a permanently empty pane. Render it now regardless.
        if tab['html'] is None:
            resp = class_section_index_tabs.render_tab(request, None, slug)
            tab['html'] = resp.content.decode(resp.charset)
            tab['lazy'] = False

    return render(
        request,
        template, {
            'menu': menu,
            'page_title': 'Class Sections',
            'api_url': '/ce/api/class_section?format=datatables',
            'sections_table': build_sections_table_config(
                variant='sections_index',
                api_url='/ce/api/class_section?format=datatables',
                filter_form_selector='#class_section_filter',
                bulk_actions={
                    'default': {
                        'actions': {
                            'change_roster_status': {
                                'label': 'Change Roster Status',
                                'icon': 'fas fa-edit',
                                'btn_class': 'btn-primary',
                                'confirm': None,
                            },
                        },
                    },
                },
                bulk_actions_url=reverse('cis:section_bulk_actions'),
                details_prefix='/ce/section/',
            ),
            'notes_api_url': '/ce/api/class_section_notes?format=datatables',
            'syllabi_api_url': '/ce/api/class_section_syllabi?format=datatables',
            'urls': {
                'details_prefix': '/ce/section/',
                'add_new': 'cis:section_add_new'
            },
            'active_term': active_term,
            'roster_status': ClassSection.ROSTER_STATUS,
            'grade_status': ClassSection.GRADE_STATUS,
            'campus': get_accessible_campuses(request.user),
            'default_campus': get_default_campus(request.user),
            'terms': Term.objects.all(),
            'extra_tabs': extra_tabs,
        }
    )


class ClassSectionHistoryViewSet(viewsets.ViewSet):
    permission_classes = [CIS_user_only]

    def list(self, request):
        from ..serializers.history import HistorySerializer
        class_section_id = request.GET.get('class_section_id')
        try:
            ClassSection.objects.get(pk=class_section_id)
        except ClassSection.DoesNotExist:
            return Response({'data': []})

        history = ClassSection.history.filter(id=class_section_id).order_by('-history_date')
        serializer = HistorySerializer(history, many=True)
        return Response({'data': serializer.data})
