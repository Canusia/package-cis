import uuid, logging, os

from django.conf import settings
from django.db import models
from django.urls import reverse_lazy

from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.contrib.sites.models import Site

from django.template import Context, Template
from django.template.loader import get_template, render_to_string

from django.dispatch import receiver
from django.db.models import Q
from django.contrib.auth.models import Group
from django.db.models import JSONField

from model_utils import FieldTracker

from mailer import send_mail, send_html_mail

from alerts.models import Alert

from cis.models.term import AcademicYear
from cis.models.course import CourseAppRequirement, Course
from cis.models.customuser import CustomUser
from cis.storage_backend import PrivateMediaStorage
from cis.utils import (
    export_to_excel,
    recommendation_upload_path,
    teacher_app_upload_path
)
logger = logging.getLogger(__name__)

class TeacherApplicant(models.Model):
    """
    Base user model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField('cis.CustomUser', on_delete=models.PROTECT)

    STATUS_OPTIONS = (
        ('Incomplete', 'Incomplete'),
        ('Inactive', 'Inactive'),
    )
    status = models.CharField(max_length=30, choices=STATUS_OPTIONS, default="Incomplete")

    def __str__(self):
        return f"{self.user.first_name} {self.user.last_name}"

    class Meta:
        ordering = ['user__first_name']

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        group = Group.objects.get(name='applicant')
        self.user.groups.add(group)

    @classmethod
    def create_new(cls, tapp_form):
        """
        Returns a TeacherApplicant object
        """
        user = CustomUser()
        user.first_name = tapp_form.cleaned_data['first_name']
        user.last_name = tapp_form.cleaned_data['last_name']
        user.middle_name = tapp_form.cleaned_data['middle_name']

        user.email = tapp_form.cleaned_data['email']
        user.username = tapp_form.cleaned_data['email']
        user.secondary_email = tapp_form.cleaned_data['secondary_email']
        user.alt_email = tapp_form.cleaned_data['alt_email']

        user.ssn = tapp_form.cleaned_data.get('ssn')
        user.date_of_birth = tapp_form.cleaned_data.get('date_of_birth')
        
        user.primary_phone = tapp_form.cleaned_data['primary_phone']
        user.secondary_phone = tapp_form.cleaned_data['secondary_phone']
        user.alt_phone = tapp_form.cleaned_data['alt_phone']

        user.address1 = tapp_form.cleaned_data['home_address']
        user.city = tapp_form.cleaned_data['city']
        user.state = tapp_form.cleaned_data['state']
        user.postal_code = tapp_form.cleaned_data['zip_code']

        user.set_password(tapp_form.cleaned_data['password'])
        user.save()

        record = TeacherApplicant(user=user)
        record.save()

        teacher_application = TeacherApplication.create_new(user=user)
        return teacher_application

class TeacherApplication(models.Model):
    """
    Base user model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # applicant = models.ForeignKey('cis.TeacherApplicant', on_delete=models.PROTECT)
    user = models.ForeignKey('cis.CustomUser', on_delete=models.PROTECT)

    createdon = models.DateField(auto_now_add=False)

    status_changed_on = JSONField(blank=True, null=True)
    tracker = FieldTracker(fields=['status'])

    STATUS_OPTIONS = (
        ('In Progress', 'In Progress'),
        ('Submitted', 'Submitted'),
        ('Under Review', 'Under Review'),
        ('Approved for FC review', 'Approved for FC review'),
        ('Decision Made', 'Decision Made'),
        ('Withdrawn', 'Withdrawn'),
        ('Closed', 'Closed'),
    )
    status = models.CharField(max_length=30, choices=STATUS_OPTIONS, default="In Progress")

    misc_info = JSONField(blank=True, null=True)

    highschool = models.ForeignKey(
        'cis.HighSchool', on_delete=models.PROTECT, blank=True, null=True)
    highschool_info = JSONField(blank=True, null=True)

    assigned_to = models.ForeignKey(
        'cis.CustomUser', on_delete=models.PROTECT, blank=True, null=True,
        related_name='assigned_to')


    def as_pdf(self, request=None):
        import pdfkit
        from cis.forms.teacher_applicant import TeacherApplicantForm, TeacherApplicantProfileForm, EditTeacherApplicationForm, EdBgForm

        from cis.models.note import TeacherApplicationNote
        record = self
        
        base_template = 'cis/teacher_applications/details_single.html'
        template = get_template(base_template)
        
        app_profile_form = TeacherApplicantProfileForm(
            user=record.user
        )

        ed_bg = record.user.education_background
        if not ed_bg:
            ed_bg = {}

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
            'psid': record.user.psid
        })

        html = template.render({
            'form': form,
            'page_title': "Application",
            'record': record,
            'app_profile_form': app_profile_form,
            'recommendations': record.recommendations,
            'interested_courses': record.selected_courses,
            'ed_bg': record.user.education_background,
            'ed_bg_form': ed_bg_form,
            'uploads': record.uploads,
            'notes': TeacherApplicationNote.objects.filter(teacher_application=record).order_by("-createdon")
        })

        options = {
            'page-size': 'Letter'
        }
        
        template = get_template('cis/print_base.html')
        html = template.render({'main_content': html})

        pdf = pdfkit.from_string(html, False, options)

        return pdf
        
    def needs_notification(self, last_sent_on, num_days):
        # return True
        from datetime import datetime

        current_date = datetime.now()
        last_sent_on = datetime.strptime(last_sent_on, '%m/%d/%Y')

        return True if abs((current_date - last_sent_on).days) >= num_days else False

    def remove_role(self):
        group = Group.objects.get(name='applicant')
        self.user.groups.remove(group)

    def import_as_teacher(self):
        from cis.models.teacher import (
            Teacher, TeacherHighSchool, TeacherCourseCertificate
        )
        from datetime import datetime

        user = self.user

        try:
            letter_sent_on = datetime.strptime(
                self.misc_info['decision_letter_sent_on'],
                '%m/%d/%Y'
            )
        except:
            letter_sent_on = datetime.now()

        try:
            teacher = Teacher.objects.get(user=user)
        except Teacher.DoesNotExist:

            user.secondary_email = user.email
            # user.alt_email = secondary_email
            user.save()
            
            teacher = Teacher(
                user=user
            )
            teacher.save()

        # add teacher to high school
        try:
            ht_hs = TeacherHighSchool(
                teacher=teacher,
                highschool=self.highschool
            )
            ht_hs.save()            
        except Exception as e:
            ht_hs = TeacherHighSchool.objects.get(
                teacher=teacher,
                highschool=self.highschool
            )


        try:
            uploads = ApplicationUpload.objects.filter(
                teacher_application=self
            )

            from cis.models.teacher import TeacherUpload
            for upload in uploads:
                new_file = TeacherUpload(
                    teacher=teacher,
                    media_type='Other',
                    media=upload.upload
                )
                new_file.save()
        except Exception as e:
            print(e)
            
        # add course to teacher
        courses = ApplicantSchoolCourse.objects.filter(
            teacherapplication=self
        )

        for course in courses:
            ht_course = TeacherCourseCertificate(
                teacher_highschool=ht_hs,
                course=course.course
            )

            letter_sent_on = datetime.strptime(
                self.misc_info['decision_letter_sent_on'],
                '%m/%d/%Y'
            )

            if course.status == 'Accepted':
                cert_status = 'Teaching'
                ht_course.approved_to_teach = letter_sent_on
            elif course.status == 'Accepted Provisional':
                cert_status = 'Teaching Provisional'
                ht_course.approved_to_provisionally_teach = letter_sent_on
            elif course.status == 'Accepted Substitute':
                cert_status = 'Teaching Substitute'
                ht_course.approved_to_provisionally_teach = letter_sent_on
            else:
                continue

            ht_course.status = cert_status
            ht_course.since = datetime.now()
            try:
                ht_course.save()
            except Exception as e:
                print(e)
                pass

        return teacher

    @property
    def attending_si_year(self):
        if not self.misc_info.participating_acad_year:
            return 'NA'
        return AcademicYear.objects.get(pk=self.misc_info.participating_acad_year).name

    @property
    def document_list_asHTML(self):
        import itertools
        files_uploaded = ApplicationUpload.objects.filter(
            teacher_application=self
        ).values_list('associated_with', flat=True)

        assoc_ids = list(
            itertools.chain(*files_uploaded)
        )
        
        all_reqs = ApplicantSchoolCourse.objects.filter(
            teacherapplication=self
        ).values_list('course__id', flat=True)
        file_assoc = CourseAppRequirement.objects.filter(
            course__id__in=all_reqs
        )

        result = '<div class="list-group list-group-flush">'
        for file in file_assoc:
            result += '<div class="list-group-item list-group-item-action flex-column align-items-start '
            if file.required == '1' and str(file.id) not in assoc_ids:
                result += " list-group-item-danger"
            result += '">'

            result += "<div class='d-flex w-100 justify-content-between "
            result += "'>"
            result += f"<h5 class='mb-1'>{file.name}</h5>"
            result += "<small>"
            if str(file.id) in assoc_ids:
                result += '<i class="fas fa-check" title="Successfully Uploaded"></i>&nbsp;'
            else:
                if file.required == '1':
                    result += '<i class="fas fa-exclamation-triangle" title="Not yet uploaded"></i>'
            result += '</small>'            
            result += '</div>'

            result += "<small class='text-muted'>"
            if file.description:
                result += file.description + " | "
                
            if file.required == '1':
                result += 'Required'
            else:
                result += 'Optional'
            result += "</small>"

            result += '</div>'
        result += '</div>'
        return result
        
    @property
    def courses(self):
        courses = ApplicantSchoolCourse.objects.filter(
            teacherapplication=self
        ).order_by(
            'course__name'
        ).values_list('course__title', 'course__name')

        course_names = [
            f'{cTitle} {cCat}' for cTitle, cCat in courses
        ]
        return ', '.join(course_names)

    @property
    def course_ids(self):
        course_ids = ApplicantSchoolCourse.objects.filter(
            teacherapplication=self
        ).values_list('course__id')

        return course_ids
    
    @property
    def status_for_teacher(self):
        if self.status in [
            'Approved for FC review'
        ]:
            return 'Under Review'

        if self.status in [
            'Denied',
            'Conditionally accepted',
            'Accepted'
        ]:
            return 'Decision Made'
        
        return self.status

    @property
    def get_status_history(self):
        if not self.status_changed_on:
            self.status_changed_on = {}
            return '-'

        result = ''
        for key, val in self.status_changed_on.items():
            key = key.replace('_', ' ').title()
            result += f'<div class="detail_label">{key}</div><div class="mt-2">{val}</div>'
        return result

    def add_reviewers(self):
        # for each course applied, get active faculty and add as reviewers
        applied_courses = self.selected_courses
        for applied_course in applied_courses:
            course = applied_course.course
            
            fc_reviewers = course.get_faculty_coordinators()

            for fc_reviewer in fc_reviewers:
                try:
                    reviewer = ApplicantCourseReviewer(
                        application_course=applied_course,
                        reviewer=fc_reviewer.user
                    )
                    reviewer.save()
                except Exception as e:
                    logger.error(e)
                    ...

    def notify_status_change(self, new_status):
        if new_status.lower() == 'in progress':
            return

        if new_status.lower() == 'approved for fc review':
            self.add_reviewers()


        if new_status.lower() == 'decision made':
            teacher_application = self
            assigned_to = teacher_application.assigned_to

            from cis.settings.teacher_application_email import teacher_application_email as tapp_s

            email_settings = tapp_s.from_db()
            email_template = Template(email_settings.get('app_decision_made_email'))

            recipient = []
            if not assigned_to:
                recipient = email_settings.get('course_selected_email_recipient', 'kadaji@gmail.com').split(',')
            else:
                recipient = [assigned_to.email]

            context = Context({
                'teacher_first_name': teacher_application.user.first_name,
                'teacher_last_name': teacher_application.user.last_name,
                'highschool': teacher_application.highschool.name,
                'teacher_email': teacher_application.user.email,
                'courses': teacher_application.courses,
                'application_status': teacher_application.status,
            })
            text_body = email_template.render(context)

            # recipient += [teacher_application.user.email]
            recipient += email_settings.get('course_selected_email_recipient', '').split(',')

            if getattr(settings, 'DEBUG', True):
                recipient = ['kadaji@gmail.com']

            subject = email_settings.get('app_decision_made_email_subject')

            template = get_template('cis/email.html')
            html_body = template.render({
                'message': text_body
            })

            send_html_mail(
                subject,
                text_body,
                html_body,
                settings.DEFAULT_FROM_EMAIL,
                recipient
            )
            

        if new_status.lower() == 'submitted':
            teacher_application = self
            assigned_to = teacher_application.assigned_to

            from cis.settings.teacher_application_email import teacher_application_email as tapp_s

            email_settings = tapp_s.from_db()
            email_template = Template(email_settings['app_submitted_email'])

            recipient = []
            if not assigned_to:
                recipient = [
                    email_settings.get('course_selected_email_recipient', 'kadaji@gmail.com')
                ]
            else:
                recipient = [assigned_to.email]

            context = Context({
                'teacher_first_name': teacher_application.user.first_name,
                'teacher_last_name': teacher_application.user.last_name,
                'highschool': teacher_application.highschool.name,
                'teacher_email': teacher_application.user.email,
                'courses': teacher_application.courses,
                'application_status': teacher_application.status,
            })
            text_body = email_template.render(context)

            # send email to course administrator(s)
            course_ids = teacher_application.course_ids
            course_admins = Course.get_administrators(course_ids)

            for course_admin in course_admins:
                alert = Alert()
                alert.alert_type = 'new_si_application_submitted'
                alert.recipient = course_admin.user
                link = teacher_application.ce_url
                alert.message = f'<a href="{link}">SI application by {teacher_application.user.first_name} for {teacher_application.courses} has been marked \'{new_status}\'</a>'
                alert.save()

                recipient += [course_admin.user.email]

            # recipient += [teacher_application.user.email]
            recipient += email_settings.get('course_selected_email_recipient', '').split(',')

            if getattr(settings, 'DEBUG', True):
                recipient = ['kadaji@gmail.com']

            subject = email_settings.get('app_submitted_email_subject')

            template = get_template('cis/email.html')
            html_body = template.render({
                'message': text_body
            })

            send_html_mail(
                subject,
                text_body,
                html_body,
                settings.DEFAULT_FROM_EMAIL,
                recipient
            )

    @property
    def faculty_url(self):
        from ..utils import getDomain
        url = getDomain() + '/faculty/application/' + str(self.id)
        return url

    @property
    def missing_items(self):
        missing = []
        if not self.has_selected_course():
            missing.append('Course Selection')

        if not self.has_submitted_ed_bg():
            missing.append('Ed. Background')
        
        if not self.has_received_recommendation():
            missing.append('Recommendation')
        
        if not self.has_uploaded_material():
            missing.append('Document(s)')

        return missing

    @property
    def ce_url(self):
        from ..utils import getDomain
        url = reverse_lazy(
                'cis:teacher_application',
                kwargs={
                    'record_id': self.id
                }
            )
        url = getDomain() + str(url)
        return url

    def __str__(self):
        return f"{self.user.first_name} {self.user.last_name} / {self.status}"

    class Meta:
        ordering = ['createdon']

    @classmethod
    def get_applications_assigned(cls, user, status='Approved for FC review'):
        pending_app_ids = ApplicantCourseReviewer.objects.filter(
            reviewer=user
        ).distinct('application_course').values_list('application_course__teacherapplication')

        if pending_app_ids:
            return TeacherApplication.objects.filter(
                id__in=pending_app_ids
            )
        return TeacherApplication.objects.none()

    @classmethod
    def create_new(cls, user):
        from datetime import datetime
        record = TeacherApplication(user=user)
        record.createdon = datetime.now().date()
        
        record.misc_info = {}
        record.save()

        return record

    def can_edit(self):
        return bool(self.status == 'In Progress' or self.status == 'Incomplete')

    def has_selected_course(self):
        return ApplicantSchoolCourse.objects.filter(
            teacherapplication=self
        ).exists()
    
    @property
    def selected_courses(self):
        return ApplicantSchoolCourse.objects.filter(
            teacherapplication=self
        )

    def has_received_recommendation(self):
        from cis.settings.inst_app_language import inst_app_language

        config = inst_app_language.from_db()

        return True if ApplicantRecommendation.objects.filter(
            teacher_application=self
        ).count() >= int(config.get('recommendations_needed', '1')) else False

    def has_recommender_submitted(self, rec_email):
        return True if ApplicantRecommendation.objects.filter(
            teacher_application=self,
            submitter__email__iexact=rec_email
        ).exists() else False

    @property
    def recommendations(self):
        try:
            return ApplicantRecommendation.objects.filter(
                teacher_application=self
            )
        except ApplicantRecommendation.DoesNotExist:
            return ApplicantRecommendation.objects.none()

    def has_submitted_ed_bg(self):
        return True if self.user.education_background else False

    def education_bg(self):
        return self.user.education_background

    def has_uploaded_material(self):
        try:
            import itertools
            files_uploaded = ApplicationUpload.objects.filter(
                teacher_application=self
            ).values_list('associated_with', flat=True)

            assoc_ids = list(
                itertools.chain(*files_uploaded)
            )

            selected_courses = ApplicantSchoolCourse.objects.filter(
                teacherapplication=self
            ).values_list('course__id', flat=True)
            
            return not CourseAppRequirement.objects.filter(
                course__id__in=selected_courses,
                required='1'
            ).exclude(
                id__in=assoc_ids
            ).exists()
        except:
            return True

    def uploads(self):
        return ApplicationUpload.objects.filter(
            teacher_application=self
        )


    def can_submit(self):
        """
        Checks if application is ready to be submitted
        """

        from cis.settings.inst_app_language import inst_app_language
        app_settings = inst_app_language.from_db()
        if app_settings.get('is_accepting_new', 'No') == 'No':
            return False

        if self.has_selected_course() and self.has_received_recommendation() and self.has_submitted_ed_bg() and self.has_uploaded_material():
            return True
        return False

    @property
    def interested_courses(self):
        interested_courses = ApplicantSchoolCourse.objects.filter(
            teacherapplication=self
        )

        courses = []
        for interested_course in interested_courses:
            course = {
                'name': interested_course.course.name,
                'status': interested_course.status,
                'id': str(interested_course.id)
            }
            courses.append(course)
        return courses

    def get_recommendation_url(self, email):
        from django.contrib.sites.models import Site
        site = Site.objects.all().first()
        
        return str(site.domain) + str(
            reverse_lazy(
                'instructor_app:instructor_recommendation',
                kwargs={
                    'record_id': self.id
                }
            )
        ) + "?email="+email

    def update_recommendation_request_info(self, name, email, name2=None, email2=None):
        from datetime import datetime

        if not self.misc_info:
            self.misc_info = {}
        
        self.misc_info['recommender_name'] = name
        self.misc_info['recommender_email'] = email

        self.misc_info['recommender_name_2'] = name2
        self.misc_info['recommender_email_2'] = email2
        
        self.misc_info['recommendation_requested_on'] = datetime.now().strftime('%m/%d/%Y')
        self.save()

    def send_recommendation_request(self, sendto_name, sendto_email):
        from cis.settings.inst_app_language import inst_app_language

        email_settings = inst_app_language.from_db()
        email_template = Template(email_settings['rec_req_email_message'])

        url = self.get_recommendation_url(sendto_email)
        recommendations = self.recommendations

        rec_emails = []
        for recommendation in recommendations:
            rec_emails.append(
                recommendation.submitter.get('email')
            )

        if sendto_email in rec_emails:
            return True

        courses = []
        try:
            courses = ApplicantSchoolCourse.objects.filter(
                teacherapplication=self
            ).values_list('course__title', flat=True)
        except ApplicantSchoolCourse.DoesNotExist:
            pass

        context = Context({
            'recommender_name': sendto_name,
            'teacher_first_name': self.user.first_name,
            'teacher_last_name': self.user.last_name,
            'highschool': self.highschool.name if self.highschool else '',
            'course_titles': ', '.join(courses),
            'recommendation_link': url,
        })
        text_body = email_template.render(context)
        to = [sendto_email]

        if getattr(settings, 'DEBUG', True):
            to = ['kadaji@gmail.com']

        subject = email_settings.get('rec_req_email_subject')

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })

        send_html_mail(
            subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            to
        )
        return True

class ApplicantCourseReviewer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    application_course = models.ForeignKey('cis.ApplicantSchoolCourse', on_delete=models.PROTECT)
    reviewer = models.ForeignKey('cis.CustomUser', on_delete=models.PROTECT)

    assigned_on = models.DateField(auto_now_add=True)

    STATUS_OPTIONS = (
        ('---', '---'),
        ('Approved', 'Approved'),
        ('Declined', 'Declined'),
        ('Need more information', 'Need more information')
    )
    status = models.CharField(max_length=50, choices=STATUS_OPTIONS, default='---')
    misc_info = JSONField(blank=True, null=True)

    status_changed_on = JSONField(blank=True, null=True)
    tracker = FieldTracker(fields=['status'])

    class Meta:
        unique_together = ['reviewer', 'application_course']

    def notify_reviewer(self):
        from cis.settings.teacher_application_email import teacher_application_email as tapp_settings

        email_settings = tapp_settings.from_db()
        email_template = Template(email_settings['fc_ready_email'])

        try:
            assigned_to_first_name = assigned_to_last_name = 'Not Assigned'
            if self.application_course.teacherapplication.assigned_to:
                assigned_to_first_name = self.application_course.teacherapplication.assigned_to.first_name
                assigned_to_last_name = self.application_course.teacherapplication.assigned_to.last_name

            context = Context({
                'teacher_first_name': self.application_course.teacherapplication.user.first_name,
                'teacher_last_name': self.application_course.teacherapplication.user.last_name,
                'teacher_email': self.application_course.teacherapplication.user.email,

                'course': self.application_course.course,
                'fc_first_name': self.reviewer.first_name,
                'fc_last_name': self.reviewer.last_name,
                
                'application_url': self.application_course.teacherapplication.faculty_url,
                'highschool': self.application_course.highschool.name,
                'assigned_cis_staff_first_name': assigned_to_first_name,
                'assigned_cis_staff_last_name': assigned_to_last_name,
            })

            text_body = email_template.render(context)
        except Exception as e:
            logger.error('Exception while processing reviewer email template' + str(e))
            return

        to = [self.reviewer.email]

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })

        if getattr(settings, 'DEBUG', True):
            to = ['kadaji@gmail.com']

        subject = email_settings.get('fc_ready_email_subject')

        send_html_mail(
            subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            to
        )

    @property
    def get_status_history(self):
        if not self.status_changed_on:
            self.status_changed_on = {}
            return '-'

        result = ''
        for key, val in self.status_changed_on.items():
            key = key.replace('_', ' ').title()
            result += f'<div class="detail_label">{key}</div><div class="mb-2">{val}</div>'
        return result


    def notify_status_change(self, new_status):
        teacher_application = self.application_course.teacherapplication
        assigned_to = teacher_application.assigned_to

        from cis.settings.teacher_application_email import teacher_application_email as tapp_s

        email_settings = tapp_s.from_db()
        email_template = Template(email_settings['course_reviewed_email'])

        recipient = []
        if not assigned_to:
            course_ids = teacher_application.course_ids
            course_admins = Course.get_administrators(course_ids)

            for course_admin in course_admins:
                alert = Alert()
                alert.alert_type = 'si_application_reviewed'
                alert.recipient = course_admin.user
                link = teacher_application.ce_url
                alert.message = f'<a href="{link}">{self.reviewer.first_name} has reviewed application submitted by {teacher_application.user.first_name} for {teacher_application.courses}</a>'
                alert.save()

                recipient += [course_admin.user.email]
        else:
            recipient = [assigned_to.email]

        context = Context({
            'teacher_first_name': teacher_application.user.first_name,
            'teacher_last_name': teacher_application.user.last_name,
            'highschool': teacher_application.highschool.name,
            'application_url': teacher_application.ce_url,
            'course': self.application_course.course,
            'course_review_status': self.status,
            'reviewer_name': self.reviewer.first_name + ' ' + self.reviewer.last_name,
            'reviewer_email': self.reviewer.email,
            'reviewer_comment': self.misc_info.get('reviewer_note')
        })

        text_body = email_template.render(context)

        if getattr(settings, 'DEBUG', True):
            recipient = ['akadajis@syr.edu', 'kadaji@gmail.com']

        subject = email_settings.get('course_reviewed_email_subject')

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })

        send_html_mail(
            subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            recipient
        )

class ApplicantSchoolCourse(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    teacherapplication = models.ForeignKey('cis.TeacherApplication', on_delete=models.PROTECT)
    course = models.ForeignKey('cis.Course', on_delete=models.PROTECT)
    highschool = models.ForeignKey(
        'cis.HighSchool', on_delete=models.PROTECT, blank=True, null=True)

    starting_academic_year = models.ForeignKey(
        'cis.AcademicYear', on_delete=models.PROTECT,
        blank=True,
        null=True
    )
    misc_info = JSONField()

    STATUS_OPTIONS = (
        ('---', '---'),
        # ('Pending', 'Pending'),
        ('Accepted', 'Accepted'),
        ('Conditionally Accepted', 'Conditionally Accepted'),
        ('Denied', 'Denied'),
    )
    status = models.CharField(max_length=50, choices=STATUS_OPTIONS, default='---')
    note = models.CharField(max_length=1000, blank=True, null=True)

    class Meta:
        unique_together = ['teacherapplication', 'course', 'highschool']

    @property
    def reviewers_asHTML(self):
        context = {
            'reviewers': ApplicantCourseReviewer.objects.filter(
                application_course=self
            ).order_by('-assigned_on')
        }
        template = get_template('cis/teacher_applications/course_reviewers.html')
        html = template.render(context)

        return html

    @property
    def first_time_teaching(self):
        if self.misc_info.get('first_time') == '1':
            return 'Yes'
        elif self.misc_info.get('first_time') == '2':
            return 'No'
        return ''

    @property
    def replacing_instructor(self):
        if self.misc_info.get('replace_instructor') == '1':
            return 'Yes'
        elif self.misc_info.get('replace_instructor') == '2':
            return 'No'
        return ''

    @property
    def replacing_info(self):
        try:
            if self.misc_info.get('replace_instructor') == '1':
                return self.misc_info.get('instructor_name') + '<br>' + self.misc_info.get('start_date') + ' - ' + self.misc_info.get('end_date')
        except:
            return ''
        
class ApplicantRecommendation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    teacher_application = models.ForeignKey('cis.TeacherApplication', on_delete=models.PROTECT)
    applicantschoolcourse = models.ForeignKey(
        'cis.ApplicantSchoolCourse', on_delete=models.PROTECT, blank=True, null=True)

    submitted_on = models.DateField(auto_now=True)
    recommendation = JSONField(blank=True, null=True)
    submitter = JSONField(blank=True, null=True)

    upload = models.FileField(
        storage=PrivateMediaStorage(),
        upload_to=recommendation_upload_path
    )

    @property
    def filename(self):
        return os.path.basename(self.upload.name)

class ApplicationUpload(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    teacher_application = models.ForeignKey('cis.TeacherApplication', on_delete=models.PROTECT)
    
    associated_with = JSONField(
        blank=True,
        null=True
    )

    upload = models.FileField(
        storage=PrivateMediaStorage(),
        upload_to=teacher_app_upload_path,
        blank=True)

    @property
    def filename(self):
        return os.path.basename(self.upload.name)

    @property
    def associated_with_as_html(self):
        if not self.associated_with:
            return ''
        
        file_assoc = CourseAppRequirement.objects.filter(
            id__in=self.associated_with
        )

        if not file_assoc:
            return ''
        
        return '<br>'.join([
            file.name for file in file_assoc
        ])

@receiver(models.signals.post_delete, sender=[ApplicationUpload, ApplicantRecommendation])
def auto_delete_file_on_delete(sender, instance, **kwargs):
    try:
        if instance.upload:
            instance.upload.delete(save=False)
        return True
    except AttributeError:
        pass
    return False