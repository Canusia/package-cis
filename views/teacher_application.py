from django.db.models import Q
from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse
from django.urls import reverse_lazy, reverse

from django.views.decorators.clickjacking import xframe_options_exempt

from ..models.teacher_applicant import (
    TeacherApplication,
    ApplicantRecommendation,
    ApplicantCourseReviewer,
    ApplicantSchoolCourse,
    ApplicationUpload
)
from cis.models.note import TeacherApplicationNote
from cis.models.course import Cohort, Course
from cis.models.term import AcademicYear

from cis.menu import cis_menu, draw_menu
from cis.forms.teacher_applicant import (
    RecommendationRequestForm,
    RecommondationForm,
    EdBgForm,
    AppUploadForm,
    StaffRecUploadForm,
    EditTeacherApplicationForm,
    ApplicantCourseReviewerForm,
    ApplicantCourseFinalStatusForm,
    TeacherApplicantProfileForm,
    NoteReplyForm,
    EditSchoolCourseForm,
    AddCourseForm,
    MigrateForm
)

from cis.utils import (
    CIS_user_only,
    FACULTY_user_only,
    HSADMIN_user_only
)

from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..serializers.teacher_application import (
    TeacherApplicationSerializer,
    ApplicantCourseReviewerSerializer
)

from cis.utils import CIS_user_only

from cis.views.eager import (
    eager_queryset,
    with_applicant_course_reviewer_related,
)

@eager_queryset(with_applicant_course_reviewer_related)
class TeacherApplicationReviewerViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ApplicantCourseReviewerSerializer
    permission_classes = [CIS_user_only|FACULTY_user_only|HSADMIN_user_only]

    def get_queryset(self):
        teacher_application_status = self.request.GET.get('status', '').strip()
        review_status = self.request.GET.get('course_review_status', '').strip()
        course_id = self.request.GET.get('course', '').strip()
        
        records = ApplicantCourseReviewer.objects.all()

        if teacher_application_status:
            records = records.filter(
                application_course__teacherapplication__status__iexact=teacher_application_status
            )

        if review_status:
            records = records.filter(
                status__iexact=review_status
            )

        if course_id:
            if course_id == '-2':
                # get all courses for the current user
                course_ids = self.request.user.get_courses_overseeing()

                cohort_apps = ApplicantSchoolCourse.objects.filter(
                    course__id__in=course_ids
                ).values_list('teacherapplication__id', flat=True)
            else:
                cohort_apps = ApplicantSchoolCourse.objects.filter(
                    course__id=course_id
                ).values_list('teacherapplication__id', flat=True)

            records = records.filter(
                application_course__teacherapplication__id__in=cohort_apps
            )
        return records

class TeacherApplicationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TeacherApplicationSerializer
    permission_classes = [CIS_user_only|FACULTY_user_only|HSADMIN_user_only]

    def get_queryset(self):
        status = self.request.GET.get('status', '').strip()
        course_status = self.request.GET.get('course_status', '').strip()
        cohort_id = self.request.GET.get('cohort', '').strip()
        course_id = self.request.GET.get('course', '').strip()
        active_only = self.request.GET.get('active_only', '').strip()
        reviewer = self.request.GET.get('reviewer')
        academic_year_id = self.request.GET.get('academic_year', '').strip()

        records = TeacherApplication.objects.none()
        if active_only:
            active_status = []
            for app_status, label in TeacherApplication.STATUS_OPTIONS:
                if app_status not in ['Withdrawn', 'Closed']:
                    active_status.append(app_status)
            records = TeacherApplication.objects.filter(
                status__in=active_status
            )
        else:
            records = TeacherApplication.objects.all()

        if academic_year_id:
            records = records.filter(
                Q(misc_info__participating_acad_year=academic_year_id) |
                Q(misc_info__participating_acad_year__isnull=True)
            )

        if reviewer:
            assigned_to = ApplicantCourseReviewer.objects.filter(
                reviewer__id=reviewer
            ).distinct(
                'application_course__teacherapplication__id'
            ).values_list(
                'application_course__teacherapplication__id', flat=True
            )
            records = records.filter(
                id__in=assigned_to
            )

        if course_status:
            app_ids = ApplicantSchoolCourse.objects.filter(
                status=course_status
            ).distinct('teacherapplication').values_list('teacherapplication__id', flat=True)

            records = records.filter(
                pk__in=app_ids
            )

        if status:
            records = records.filter(
                status=status
            )

        if cohort_id:
            cohort_apps = ApplicantSchoolCourse.objects.filter(
                course__cohort__id=cohort_id
            ).values_list('teacherapplication__id', flat=True)

            records = records.filter(
                id__in=cohort_apps
            )

        if course_id:
            if course_id == '-2':
                # get all courses for the current user
                course_ids = self.request.user.get_courses_overseeing()

                cohort_apps = ApplicantSchoolCourse.objects.filter(
                    course__id__in=course_ids
                ).values_list('teacherapplication__id', flat=True)
            else:
                cohort_apps = ApplicantSchoolCourse.objects.filter(
                    course__id=course_id
                ).values_list('teacherapplication__id', flat=True)

            records = records.filter(
                id__in=cohort_apps
            )
        return records

def delete_course(request, record_id):
    record = get_object_or_404(
        ApplicantSchoolCourse,
        pk=record_id
    )

    ApplicantCourseReviewer.objects.filter(
        application_course=record
    ).delete()

    application_id = record.teacherapplication.id
    record.delete()

    return JsonResponse({
        'status': 'success',
        'message': 'Successfully deleted course',
        'redirect': reverse_lazy(
            'cis:teacher_application', kwargs={
                'record_id': application_id
            }
        )
    })

def view_approval_email(request, record_id):
    template = 'cis/ajax-base.html'

    record = get_object_or_404(TeacherApplication, pk=record_id)

    html_body, text_body = record.get_approval_notification_email()
    return render(
        request,
        template, {
            'ajax_content': html_body,
        }
    )

def send_approval_email(request, record_id):

    record = get_object_or_404(TeacherApplication, pk=record_id)
    record.notify_application_approved()
    record.mark_as_approval_notification(request)
    
    return JsonResponse({
        'status': 'success',
        'message': 'Successfully sent approval notification',
        'action': 'reload'
    })
from django.http import HttpResponse
def download_as_pdf(request, record_id):

    record = get_object_or_404(TeacherApplication, pk=record_id)

    pdf = record.as_pdf(request)

    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="teacher-application.pdf"'

    return response

def download_files(request, record_id):
    import os
    import zipfile
    from io import BytesIO
    from cis.storage_backend import PrivateMediaStorage

    record = get_object_or_404(TeacherApplication, pk=record_id)

    pdf = record.as_pdf()

    ZIPFILE_NAME = f"{record.user.last_name}-{record.user.first_name}.zip"

    files = ApplicationUpload.objects.filter(
        teacher_application=record
    )

    recommendations = ApplicantRecommendation.objects.filter(
        teacher_application=record
    )
    
    b =  BytesIO()
    with zipfile.ZipFile(b, 'w') as zf:
        zf.writestr('teacher_application.pdf', pdf)
        
        for current_file in files:
            fh = PrivateMediaStorage().open(current_file.upload.name, "rb")
            zf.writestr(current_file.filename, bytes(fh.read()))

        for current_file in recommendations:
            fh = PrivateMediaStorage().open(current_file.upload.name, "rb")
            zf.writestr(current_file.filename, bytes(fh.read()))

        zf.close()

        response = HttpResponse(b.getvalue(), content_type="application/x-zip-compressed")
        response['Content-Disposition'] = f'attachment; filename={ZIPFILE_NAME}'
        return response

def remind_reviewer(request):
    reviewer_id = request.GET.get('reviewer_id')

    course_review = get_object_or_404(ApplicantCourseReviewer, pk=reviewer_id)
    course_review.notify_reviewer()

    data = {
        'status':'success',
        'message':'Successfully processed your request'
    }
    return JsonResponse(data)

def do_action(request, record_id):
    action = request.GET.get('action')

    if request.method == 'POST':
        action = request.POST.get('action')
        
    if action == 'edit_teacher_application_highschool':
        return edit_teacher_application_highschool(request, record_id)

    if action == 'edit_teacher_application_upload':
        return edit_teacher_application_upload(request, record_id)

    if action == 'add_teacher_application_course':
        return add_teacher_application_course(request, record_id)

    if action == 'delete_teacher_application_course':
        return delete_teacher_application_course(request, record_id)

    data = {
        'status': 'success',
        'message': 'invalid action passed'
    }
    return JsonResponse(data)

def edit_teacher_application_upload(request, record_id):
    template = 'cis/teacher_applications/edit_teacher_application_highschool.html'
    teacher_application = get_object_or_404(TeacherApplication, pk=record_id)

    upload_id = request.GET.get('upload_id')

    if request.method == 'POST':

        upload_id = request.POST.get('id')
        form = EditTeacherAppCourseUploadForm(
            teacher_application=teacher_application,
            upload_id=upload_id,
            data=request.POST
        )

        if form.is_valid():
            status = form.save(teacher_application)

            data = {
                'status':'success',
                'message':'Successfully updated record',
                'action': 'reload_page'
            }
            return JsonResponse(data)
        else:
            data = {
                'status':'error',
                'message':'Please correct the errors and try again.',
                'errors': form.errors.as_json()
            }
        return JsonResponse(data, status=400)

    form = EditTeacherAppCourseUploadForm(
        teacher_application=teacher_application, upload_id=upload_id
    )
    context = {
        'title': 'Update Upload',
        'form': form,
        'form_action': str(reverse_lazy('cis:teacher_app_action', kwargs={'record_id': record_id}))
    }
    
    return render(request, template, context)

def delete_teacher_application_course(request, record_id):
    application_course = get_object_or_404(ApplicantSchoolCourse, pk=record_id)

    ApplicantCourseReviewer.objects.filter(
        application_course=application_course
    ).delete()

    application_course.delete()

    data = {
        'status':'success',
        'message':'Successfully removed course',
        'action': 'reload_page'
    }
    return JsonResponse(data)

def add_teacher_application_course(request, record_id):
    template = 'cis/teacher_applications/edit_teacher_application_highschool.html'
    teacher_application = get_object_or_404(TeacherApplication, pk=record_id)

    if request.method == 'POST':

        form = AddCourseForm(
            teacher_application=teacher_application,
            data=request.POST
        )

        if form.is_valid():
            status = form.save(teacher_application)

            data = {
                'status':'success',
                'message':'Successfully added record',
                'action': 'reload_page'
            }
            return JsonResponse(data)
        else:
            data = {
                'status':'error',
                'message':'Please correct the errors and try again.',
                'errors': form.errors.as_json()
            }
        return JsonResponse(data, status=400)

    form = AddCourseForm(teacher_application=teacher_application)
    context = {
        'title': 'Add Course',
        'form': form,
        'form_action': str(reverse_lazy('cis:teacher_app_action', kwargs={'record_id': record_id}))
    }
    
    return render(request, template, context)

def edit_teacher_application_highschool(request, record_id):
    template = 'cis/teacher_applications/edit_teacher_application_highschool.html'
    teacher_application = get_object_or_404(TeacherApplication, pk=record_id)

    if request.method == 'POST':

        form = EditSchoolCourseForm(
            teacher_application=teacher_application,
            data=request.POST
        )

        if form.is_valid():
            status = form.save(teacher_application)

            data = {
                'status':'success',
                'message':'Successfully updated record',
                'action': 'reload_page'
            }
            return JsonResponse(data)
        else:
            data = {
                'status':'error',
                'message':'Please correct the errors and try again.',
                'errors': form.errors.as_json()
            }
        return JsonResponse(data, status=400)

    form = EditSchoolCourseForm(teacher_application=teacher_application)
    context = {
        'title': 'Change High School',
        'form': form,
        'form_action': str(reverse_lazy('cis:teacher_app_action', kwargs={'record_id': record_id}))
    }
    
    return render(request, template, context)

def add_new_course_reviewer(request):
    '''
    Add new reviewer
    '''
    ajax = request.GET.get('ajax', None)
    base_template = 'cis/logged-base.html' if not ajax else 'cis/ajax-base.html'
    template = 'cis/teacher_applications/manage_reviewer.html'

    if request.method == 'POST':
        application_course_id = request.POST.get('application_course_id')
        application_course = get_object_or_404(
            ApplicantSchoolCourse,
            pk=application_course_id)

        form = ApplicantCourseReviewerForm(
            application_course,
            request.POST)
        if form.is_valid():
            try:
                course_reviewer = form.save(commit=False)
                course_reviewer.application_course = application_course
                course_reviewer.save()

                data = {
                    'status':'success',
                    'message':'Successfully saved record',
                    'new_record_id': course_reviewer.id,
                    'new_record_name':'',
                    'action': 'reload'
                }
                return JsonResponse(data)

            except ValueError as e:
                print(e)
                data = {
                    'status':'error',
                    'message':'Looks like a duplicate entry'
                }
                return JsonResponse(data)

            except Exception as e:
                data = {
                    'status':'error',
                    'message':'Looks like a duplicate entry'
                }
                return JsonResponse(data)

    else:
        application_course_id = request.GET.get('parent')
        application_course = get_object_or_404(ApplicantSchoolCourse, pk=application_course_id)

        initial = {
            'id': '-1',
            'ajax': 1
        }

        form = ApplicantCourseReviewerForm(
            application_course=application_course,
            initial=initial
        )

    return render(
        request,
        template, {
            'form': form,
            'ajax': ajax,
            'record': application_course,
            'base_template': base_template
        })

def reply_to_note(request, note_id):
    note = get_object_or_404(
        TeacherApplicationNote,
        pk=note_id
    )

    replies = TeacherApplicationNote.objects.filter(
        parent=note.id,
        meta__type__in=['public', 'response', 'to_instructor']
    ).order_by(
        '-createdon'
    )

    teacher_application = note.teacher_application
    template = 'cis/teacher_applications/note_reply.html'
    form = NoteReplyForm(
        note=note
    )

    if request.method == 'POST':
        form = NoteReplyForm(
            note,
            request.POST
        )

        if form.is_valid():
            reply = form.save(request, note)

            messages.add_message(
                request,
                messages.SUCCESS,
                f'The note has been successfully added.',
                'list-group-item-success'
            )
            return redirect(
                'cis:teacher_app_note_reply',
                note_id=note.id
            )
        messages.add_message(
            request,
            messages.SUCCESS,
            f'Please fix the errors and try again',
            'list-group-item-danger'
        )

    return render(
        request,
        template,
        {
            'form': form,
            'note': note,
            'replies': replies
        })
reply_to_note.login_required=False

def remove_recommendation(request, record_id):
    try:
        rec = ApplicantRecommendation.objects.get(
            pk=record_id
        )
        teacher_application = rec.teacher_application
        rec.delete()

        messages.add_message(
            request,
            messages.SUCCESS,
            f'Successfully removed recommendation.',
            'list-group-item-success')
        return redirect(
            'cis:teacher_application',
            record_id=teacher_application.id
        )
    except:
        messages.add_message(
            request,
            messages.SUCCESS,
            f'Unable to remove recommendation.',
            'list-group-item-error')
        return redirect(
            'cis:teacher_application',
            record_id=teacher_application.id
        )

def remove_upload(request, record_id):
    try:
        upload = ApplicationUpload.objects.get(
            pk=record_id
        )
        teacher_application = upload.teacher_application
        upload.delete()

        messages.add_message(
            request,
            messages.SUCCESS,
            f'Successfully removed file.',
            'list-group-item-success')
        return redirect(
            'cis:teacher_application',
            record_id=teacher_application.id
        )
    except:
        messages.add_message(
            request,
            messages.SUCCESS,
            f'Unable to remove file.',
            'list-group-item-error')
        return redirect(
            'cis:teacher_application',
            record_id=teacher_application.id
        )

def add_new_course_reviewer(request):
    '''
    Add new reviewer
    '''
    ajax = request.GET.get('ajax', None)
    base_template = 'cis/logged-base.html' if not ajax else 'cis/ajax-base.html'
    template = 'cis/teacher_applications/manage_reviewer.html'

    if request.method == 'POST':
        application_course_id = request.POST.get('application_course_id')
        application_course = get_object_or_404(
            ApplicantSchoolCourse,
            pk=application_course_id)

        form = ApplicantCourseReviewerForm(
            application_course,
            request.POST)
        if form.is_valid():
            try:
                course_reviewer = form.save(commit=False)
                course_reviewer.application_course = application_course
                course_reviewer.save()

                data = {
                    'status':'success',
                    'message':'Successfully saved record',
                    'new_record_id': course_reviewer.id,
                    'new_record_name':'',
                    'action': 'reload'
                }
                return JsonResponse(data)

            except ValueError as e:
                print(e)
                data = {
                    'status':'error',
                    'message':'Looks like a duplicate entry'
                }
                return JsonResponse(data)

            except Exception as e:
                data = {
                    'status':'error',
                    'message':'Looks like a duplicate entry'
                }
                return JsonResponse(data)

    else:
        application_course_id = request.GET.get('parent')
        application_course = get_object_or_404(ApplicantSchoolCourse, pk=application_course_id)

        initial = {
            'id': '-1',
            'ajax': 1
        }

        form = ApplicantCourseReviewerForm(
            application_course=application_course,
            initial=initial
        )

    return render(
        request,
        template, {
            'form': form,
            'ajax': ajax,
            'record': application_course,
            'base_template': base_template
        })

def delete_record(request, record_id):
    record = get_object_or_404(
        TeacherApplication,
        pk=record_id
    )

    TeacherApplicationNote.objects.filter(
        teacher_application=record
    ).delete()

    ApplicantRecommendation.objects.filter(
        teacher_application=record
    ).delete()

    ApplicationUpload.objects.filter(
        teacher_application=record
    ).delete()

    ApplicantCourseReviewer.objects.filter(
        application_course__teacherapplication=record
    ).delete()
    
    ApplicantSchoolCourse.objects.filter(
        teacherapplication=record
    ).delete()
    
    user = record.user
    record.delete()

    # try to remove base user account if this was the only role
    try:
        user.delete()
    except:
        pass

    return JsonResponse({
        'status': 'success',
        'message': 'Successfully deleted application',
        'redirect': reverse_lazy('cis:teacher_applications')
    })

@xframe_options_exempt
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'cis/teacher_applications/details.html'
    record = get_object_or_404(TeacherApplication, pk=record_id)
    if not record.misc_info:
        record.misc_info = {}

    app_profile_form = TeacherApplicantProfileForm(
        user=record.user
    )

    migration_form = MigrateForm(record)

    action = request.GET.get('action')
    if request.method == 'POST':
        action = request.POST.get('action')

        if request.POST.get('action') == 'migrate_teacher_application':
            migration_form = MigrateForm(
                record=record, data=request.POST
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
                
        elif action == 'update_teacher':
            app_profile_form = TeacherApplicantProfileForm(
                record.user,
                request.POST
            )

            if app_profile_form.is_valid():
                app_profile_form.save()
                
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    f'The applicant profile has been successfully updated.',
                    'list-group-item-success')
                return redirect(
                    'cis:teacher_application',
                    record_id=record.id
                )

        elif action == 'Import as Instructor':
            try:
                teacher = record.import_as_teacher()
                record.remove_role()

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    f'Successfully imported as teacher. Please update the username, and review the course certification status.',
                    'list-group-item-success'
                )
                return redirect(
                    'cis:instructor',
                    record_id=teacher.id
                )
            except KeyError as e:
                print(e)
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    f'Please make sure the decision letter sent date has been entered.',
                    'list-group-item-danger'
                )

    if action == 'delete_reviewer':
        reviewer_id = request.GET.get('reviewer')
        reviewer = get_object_or_404(ApplicantCourseReviewer, pk=reviewer_id)

        reviewer.delete()
        messages.add_message(
            request,
            messages.SUCCESS,
            f'The reviewer has been successfully deleted',
            'list-group-item-success'
        )
        return redirect(
            'cis:teacher_application',
            record_id=record.id
        )

    form = EditTeacherApplicationForm(initial={
        'status': record.status,
        'assigned_to': record.assigned_to,
        'invite_to_interview': record.misc_info.get('invite_to_interview'),
        'interviewed_on': record.misc_info.get('interviewed_on'),
        'decision_letter_sent_on': record.misc_info.get('decision_letter_sent_on'),
        'action': 'edit_application',
        'participating_acad_year': record.misc_info.get('participating_acad_year'),
        'grad_credit': record.misc_info.get('grad_credit'),
        'checklist': record.misc_info.get('checklist'),
        'psid': record.user.psid,
        'migration_form': migration_form
    })

    if not record.misc_info:
        record.misc_info = {}

    ed_bg = record.user.education_background
    if not ed_bg:
        ed_bg = {}

    rec_req_form = rec_upload_form = ed_bg_form = app_upload_form = None
    if request.method == 'POST':
        if request.POST.get('action') == 'upload_recommendation':           
            recommendation = ApplicantRecommendation(
                teacher_application=record
            )

            rec_upload_form = StaffRecUploadForm(
                request.POST,
                request.FILES,
                instance=recommendation)

            if rec_upload_form.is_valid():
                recommendation = rec_upload_form.save(commit=False)
                recommendation.recommendation = {}
                recommendation.recommendation['number_years'] = rec_upload_form.cleaned_data.get('years', '-')

                recommendation.submitter = {}
                recommendation.submitter['name'] = rec_upload_form.cleaned_data['name']
                recommendation.submitter['position'] = rec_upload_form.cleaned_data['position']
                recommendation.submitter['email'] = rec_upload_form.cleaned_data.get('email')

                recommendation.save()

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    f'The recommendation has been successfully uploaded',
                    'list-group-item-success')

        if request.POST.get('action') == 'send_recommendation_link':
            rec_req_form = RecommendationRequestForm(request.POST)

            if rec_req_form.is_valid():
                result = rec_req_form.save()
                
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    f'Successfully sent recommendation request.',
                    'list-group-item-success')
            else:
                print(rec_req_form.errors)

        if request.POST.get('action') == 'edit_application':
            form = EditTeacherApplicationForm(request.POST)
            if form.is_valid():
                form.save(record)

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    f'Successfully updated application',
                    'list-group-item-success')
            else:
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    f'Please correct the error(s) and try again',
                    'list-group-item-warning')

        if request.POST.get('action') == 'update_course_status':
            update_course_form = ApplicantCourseFinalStatusForm(request.POST)
            if update_course_form.is_valid():
                update_course_form.save()
                return JsonResponse({
                    'message': 'Successfully updated course status.',
                    'status': 'success'
                }, status=200)
            else:
                return JsonResponse({
                    'message': 'Please correct the errors and try again',
                    'errors': update_course_form.errors.as_json()
                }, status=400)

        if request.POST.get('action') == 'update_ed_background':
            ed_bg_form = EdBgForm(request.POST)
            if ed_bg_form.is_valid():
                ed_bg_form.save(record)
                return JsonResponse({
                    'message': 'Successfully saved educational background information.',
                    'status': 'success'
                }, status=200)
            else:
                return JsonResponse({
                    'message': 'Please correct the errors and try again',
                    'errors': ed_bg_form.errors.as_json()
                }, status=400)
        
        if request.POST.get('action') == 'app_upload':
            app_upload_form = AppUploadForm(
                record,
                request.POST,
                request.FILES
            )

            if request.FILES.get('upload') and app_upload_form.is_valid():
                upload = app_upload_form.save(commit=False)
                upload.teacher_application = record
                upload.save()

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    f'Your file has been uploaded. Please repeat the step for additional files. ',
                    'list-group-item-success')
            else:
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    f'Unable to upload file. Did you select a file?',
                    'list-group-item-danger')
    
    course_status_forms = {}
    for course in record.selected_courses:
        course_status_forms[course.id] = ApplicantCourseFinalStatusForm(
            initial={
                'application_course_id':course.id,
                'note': course.note,
                'decision': course.status
            }
        )

    if not rec_req_form:
        rec_req_form = RecommendationRequestForm(initial={
            'name': record.misc_info.get('recommender_name'),
            'email': record.misc_info.get('recommender_email'),
            'name_2': record.misc_info.get('recommender_name_2'),
            'email_2': record.misc_info.get('recommender_email_2'),
            'teacher_application':record.id
        })
    
    if not rec_upload_form:
        rec_upload_form = StaffRecUploadForm(initial={
            'teacher_application':record.id
        })

    if not ed_bg_form:
        ed_bg = record.user.education_background
        if not ed_bg or isinstance(ed_bg, str):
            ed_bg = {}

        ed_bg_form = EdBgForm(initial={
            'teacher_application': record.id,
            'other_name': record.user.previous_names,
            'credits_earned': ed_bg.get('credits_earned'),
            'masters_level_credits': ed_bg.get('masters_level_credits'),
            'grad_courses': ed_bg.get('grad_courses'),
            'undergrad_program': ed_bg.get('undergrad_program'),
            'certified_states': ed_bg.get('certified_states'),
            'certified_subjects': ed_bg.get('certified_subjects'),
            'highschool_years': ed_bg.get('highschool_years'),
            'college_years': ed_bg.get('college_years'),
            'courses_taught': ed_bg.get('courses_taught'),
        })

    if not app_upload_form:
        app_upload_form = AppUploadForm(
            record,
            initial={
                'teacher_application':record.id
            }
        )

    return render(
        request,
        template, {
            'form': form,
            'page_title': "Application",
            'labels': {
                'all_items': 'All Applications'
            },
            'urls': {
                'all_items': 'cis:teacher_applications'
            },
            'menu': draw_menu(cis_menu, 'instructors', 'all_applicants'),
            'record': record,
            'app_profile_form': app_profile_form,
            'recommendations': record.recommendations,
            'rec_req_form': rec_req_form,
            'rec_upload_form': rec_upload_form,
            'interested_courses': record.selected_courses,
            'course_status_forms': course_status_forms,
            'ed_bg': record.user.education_background,
            'ed_bg_form': ed_bg_form,
            'uploads': record.uploads,
            'is_modal': True if request.GET.get('modal') else False,
            'notes': TeacherApplicationNote.objects.filter(teacher_application=record).order_by("-createdon"),
            'app_upload_form': app_upload_form
        })

def index(request):
    '''
     search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'instructors', 'all_applicants')
    template = 'cis/teacher_applications/index.html'

    return render(
        request,
        template, {
            'page_title': 'Instructor Applications',
            'urls': {
            },
            'menu': menu,
            'status': TeacherApplication.STATUS_OPTIONS,
            'course_status': ApplicantSchoolCourse.STATUS_OPTIONS,
            'course_review_status': ApplicantCourseReviewer.STATUS_OPTIONS,
            'academic_years': AcademicYear.objects.all().order_by('-name'),
            'courses': Course.objects.all().order_by('cohort__designator'),
            'api_url': '/ce/api/teacher_application?format=datatables',
            'reviewer_api_url': '/ce/api/teacher_application_reviewers?format=datatables'
        }
    )
