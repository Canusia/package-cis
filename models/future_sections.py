# users/models.py
import uuid, csv, datetime
from django.conf import settings

from django.db import models
from django.db.models import JSONField
from django.utils.safestring import mark_safe
from django.core.mail import EmailMessage

from django.template import Context, Template

from django.http import HttpResponse
from django.urls import reverse

from cis.models.teacher import (
    TeacherCourseCertificate
)
from cis.models.term import AcademicYear, Term

from cis.models.settings import Setting

class FutureProjection(models.Model):
    """
    Future Course model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    academic_year = models.ForeignKey(
        'cis.AcademicYear', on_delete=models.PROTECT, blank=True, null=True
    )
    highschool = models.ForeignKey(
        'cis.HighSchool', on_delete=models.PROTECT, blank=True, null=True
    )
    created_by = models.ForeignKey(
        'cis.CustomUser', on_delete=models.PROTECT, blank=True, null=True
    )

    meta = JSONField(default=dict)
    started_on = models.DateField(auto_now_add=True)

    class Meta:
        unique_together = (('academic_year', 'highschool'))

    @property
    def confirmed_administrators(self):
        return self.meta.get('confirmed_administrators', 'No')
    
    @property
    def confirmed_class_sections(self):
        return self.meta.get('confirmed_class_sections', 'No')
    
    @property
    def confirmed_choice_class_sections(self):
        return self.meta.get('confirmed_choice_class_sections', 'No')
    
    @property
    def confirmed_facilitator_class_sections(self):
        return self.meta.get('confirmed_facilitator_class_sections', 'No')

class FutureCourse(models.Model):
    """
    Future Course model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    academic_year = models.ForeignKey(
        'cis.AcademicYear', on_delete=models.PROTECT, blank=True, null=True
    )
    teacher_course = models.ForeignKey(
        'cis.TeacherCourseCertificate', on_delete=models.CASCADE,
        blank=True, null=True
    )
    # highschool = models.ForeignKey(
    #     'cis.HighSchool', on_delete=models.CASCADE,
    #     blank=True, null=True
    # )
    # course = models.ForeignKey(
    #     'cis.Course', on_delete=models.CASCADE,
    #     blank=True, null=True
    # )
    
    term = models.ForeignKey(
        'cis.Term', on_delete=models.PROTECT, blank=True, null=True
    )
    
    meta = JSONField(default=dict)

    started_on = models.DateField(auto_now=True)
    last_viewed_on = models.DateField(auto_now_add=True)
    submitted_on = models.DateField(blank=True, null=True)

    section_info = JSONField(default=dict)

    class Meta:
        unique_together = (('teacher_course', 'academic_year'))

    def __str__(self):
        return f"{self.teacher_course.teacher_highschool.teacher} - {self.teacher_course.course} ({self.academic_year})"
    

    def create_teacher_application(self):
        from cis.models.teacher_applicant import TeacherApplicant, TeacherApplication, ApplicantSchoolCourse, ApplicationUpload

        teacher_app = TeacherApplication(
            user=self.teacher_course.teacher_highschool.teacher.user,
            highschool=self.teacher_course.teacher_highschool.highschool,
            status='Submitted',
            createdon=datetime.datetime.now()
        )

        if not self.teacher_course.teacher_highschool.teacher.user.education_background:
            self.teacher_course.teacher_highschool.teacher.user.education_background = {}
            self.teacher_course.teacher_highschool.teacher.user.save()
            
        teacher_app.save()

        app_course = ApplicantSchoolCourse(
            teacherapplication=teacher_app,
            course=self.teacher_course.course,
            highschool=self.teacher_course.teacher_highschool.highschool,
            status='---',
            misc_info={},
            starting_academic_year=self.academic_year
        )
        app_course.save()

        for s_info in self.section_info.get('sections'):
            # print(s_info)
            file_path = s_info.get('file')
            if file_path:
                import requests
                from django.core.files.base import ContentFile
                from urllib.parse import urlparse
                import os

                # Your S3 URL
                s3_url = file_path

                # Download the file from S3
                response = requests.get(s3_url)

                if response.status_code == 200:
                    # Extract filename from URL
                    parsed_url = urlparse(s3_url)
                    filename = os.path.basename(parsed_url.path)  # Gets 'Avi_1_mil.pdf'
                    
                    # Create a ContentFile from the downloaded content
                    file_content = ContentFile(response.content)
                    
                    # do the upload
                    app_upload = ApplicationUpload(
                        teacher_application=teacher_app
                    )
                    app_upload.save()

                    # Save to the FileField
                    app_upload.upload.save(filename, file_content, save=True)
                    

    @classmethod
    def get_or_add(cls, teacher_course, academic_year, section_info=None):
        try:
            record = FutureCourse.objects.get(
                teacher_course=teacher_course,
                academic_year=academic_year
            )
            return record
        except FutureCourse.DoesNotExist:
            if not section_info:
                section_info = {}

            record = FutureCourse(
                teacher_course=teacher_course,
                academic_year=academic_year,
                section_info=section_info
            )
            record.save()
            return record

    def send_confirmation_email(self, mode="text"):
        """
        Sends confirmation email to instructor
        """
        subject = FutureCourse.get_setting_value('confirmation_subject')
        message = FutureCourse.get_setting_value('confirmation_message')
        message_replyto = FutureCourse.get_setting_value('message_replyto')

        if FutureCourse.get_setting_value('mode') == 'test':
            to = FutureCourse.get_setting_value('testers').split(",")
        else:
            to = [self.teacher.user.email]

        message = message.replace(
            "{instructor_first_name}", self.teacher.user.first_name)
        message = message.replace(
            "{future_sections}", self.as_string(mode)
        )
        message = message.replace(
            "{academic_year}", self.academic_year.name)

        email = EmailMessage(
            subject,
            message,
            settings.MY_CE.get('default_from'),
            to,
            reply_to=[message_replyto]
        )
        return email.send(fail_silently=True)

    def has_completed_all_courses(self):
        """
        Return bool indicating the instructor has responded to all
        eligible course(s)
        """
        ht_courses = TeacherCourseCertificate.objects.filter(
            teacher_highschool__teacher=self.teacher,
            course__status__in=FutureCourse.get_active_course_status(),
            status__in=FutureCourse.get_active_course_certificate_status()
        ).exclude(
            id__in=FutureSection.objects.filter(
                future_course=self.id
                ).values_list('teacher_course', flat=True)).all()
 
        return True if not ht_courses.exists() else False

    def as_string(self, mode='text'):
        """
        Return the future section information as a string
        """
        result = ""
        sections = FutureSection.objects.filter(future_course=self.id).all()

        if mode == 'text':
            for section in sections:
                result += f"{section.teacher_course.course} at {section.teacher_course.teacher_highschool.highschool.name}, "
                if section.section_info.get('teaching') == 'yes':
                    result += section.section_info.get('estimated_enrollment') + " student(s) "
                    result += "\r\n"
                else:
                    result += "Not teaching\r\n"
        return result

    @staticmethod
    def welcome_message(highschools=None):
        from cis.settings.future_sections import future_sections as fs_settings
        from cis.models.term import AcademicYear
        from cis.models.section import ClassSection

        fs_config = fs_settings.from_db()
        message = Template(fs_config.get('welcome_message', 'not configured'))

        academic_year = AcademicYear.objects.get(
            pk=fs_config.get('academic_year')
        )
        previous_academic_year = AcademicYear.objects.get(
            pk=fs_config.get('previous_academic_year')
        )

        if highschools:
            class_sections = ClassSection.objects.filter(
                # term__academic_year=previous_academic_year,
                highschool__in=highschools
            ).order_by('term__code')

            class_section_html = "<table class='table table-striped'><tr><th>Term</th><th>Course</th><th>Instructor</th></tr>"
            for class_section in class_sections:
                class_section_html += f"<tr><td>{class_section.term}</td><td>{class_section.course}</td><td>{class_section.teacher}</td></tr>"
            class_section_html += "</table>"

        context = Context({
            'academic_year': str(academic_year),
            'previous_academic_year': str(previous_academic_year),
            'start_date': fs_config.get('starting_date'),
            'end_date': fs_config.get('ending_date'),
            'previous_year_classes': mark_safe(class_section_html)
        })
        return message.render(context)

    @staticmethod
    def get_setting_value(setting_key):
        key = "cis_future_sections"
        try:
            setting = Setting.objects.get(key=key)
            return setting.value.get(setting_key, '')
        except:
            return ""

    @staticmethod
    def is_window_open():
        from cis.settings.future_sections import future_sections as fs_settings

        fs_config = fs_settings.from_db()
        start_date = datetime.datetime.strptime(
            fs_config.get('starting_date', '10/10/2020'),
            "%m/%d/%Y"
        )

        end_date = datetime.datetime.strptime(
            fs_config.get('ending_date', '10/10/2020'),
            "%m/%d/%Y"
        )

        now = datetime.datetime.now()
        if now >= start_date and now <= end_date:
            return True
        return False

    @staticmethod
    def get_active_course_certificate_status():
        """
        Return the list of course certificate status for which future course should
        pull courses from
        """
        key = "cis_future_sections"
        try:
            setting = Setting.objects.get(key=key)
            return setting.value.get('teacher_course_status')
        except Setting.DoesNotExist:
            return []

    @staticmethod
    def get_active_course_status():
        """
        Return the list of course status for which future course should
        pull courses from
        """
        key = "cis_future_sections"
        try:
            setting = Setting.objects.get(key=key)
            return setting.value.get('course_status')
        except Setting.DoesNotExist:
            return []

    @staticmethod
    def get_active_academic_year():
        """
        Return the academic year for which future course form is set to
        """
        key = "cis_future_sections"
        try:
            setting = Setting.objects.get(key=key)
            return setting.value.get('academic_year')
        except Setting.DoesNotExist:
            return str(AcademicYear.objects.all[0].id)


    @staticmethod
    def get_active_term():
        """
        Return the term for which future course form is set to
        """
        key = "cis_future_sections"
        try:
            setting = Setting.objects.get(key=key)
            return setting.value.get('term')
        except Setting.DoesNotExist:
            return str(Term.objects.all[0].id)


    @staticmethod
    def get_instructors_missing(academic_year,course=''):
        """
        Return list of instructors who have not completed the future course
        """
        pass

    @staticmethod
    def get_link(teacher, academic_year):
        """
        Return course schedule URL
        """
        pass

    @property
    def teaching_or_not(self):
        return 'Yes' if self.section_info.get('teaching') == 'yes' else 'No'

class FutureSection(models.Model):
    """Section info for each instructor"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    future_course = models.ForeignKey('cis.FutureCourse', on_delete=models.CASCADE)

    section_info = JSONField(blank=True)
    added_on = models.DateField(auto_now_add=True)

    @property
    def teaching_or_not(self):
        return 'Yes' if self.section_info.get('teaching') == 'yes' else 'No'

    @property
    def number_of_sections(self):
        return self.section_info.get('number_of_sections')

    @property
    def estimated_enrollment(self):
        return self.section_info.get('estimated_enrollment', '-')

    @staticmethod
    def export_instructor_survey_export():
        """
        Export instructor survey links
        """
        file_name = "instructor_survey_export.csv"

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{file_name}"'
        writer = csv.writer(response)

        fields = [
            'School',
            'Instructor First Name',
            'Instructor Last Name',
            'Email',
            'EMPLID',
            'Link'
        ]
        records = TeacherCourseCertificate.objects.filter(
            course__status='Active'
        ).exclude(
            teacher_highschool__teacher__in=FutureSection.objects.filter(

            ).values('teacher_course__teacher_highschool__teacher')
        ).distinct('teacher_highschool__teacher')
        # Write Header
        writer.writerow(fields)

        for record in records:
            row = []
            row.append(record.teacher_highschool.highschool.name)
            row.append(record.teacher_highschool.teacher.user.first_name)
            row.append(record.teacher_highschool.teacher.user.last_name)
            row.append(record.teacher_highschool.teacher.user.email)
            row.append(record.teacher_highschool.teacher.user.psid)
            row.append(
                reverse(
                    'instructor:course_schedule',
                    kwargs={
                        'instructor':record.teacher_highschool.teacher.id}))

            writer.writerow(row)

        return response
    
    @staticmethod
    def export_to_excel(records):
        """
        Write records to an Excel file
        """
        file_name = "future_sections.csv"
        fields = {
            'future_course.id': 'ID',
            'future_course.academic_year': "Academic Year",
            'teacher_course.teacher_highschool.teacher.user.first_name': 'Instructor Firstname',
            'teacher_course.teacher_highschool.teacher.user.last_name': 'Instructor Lastname',
            'teacher_course.teacher_highschool.teacher.user': 'Instructor Email',
            'teacher_course.teacher_highschool.teacher.user.psid': 'EMPLID',
            'teacher_course.course': 'Course',
            'teacher_course.teacher_highschool.highschool': 'School',
            'added_on': 'Added On',
            "section_info['teaching']": 'Teaching',
            'starting_date': 'Starting Date',
            'ending_date': 'Ending Date',
            'estimated_enrollment': 'Estimated Enrollement',
            'length_change': 'Length Change',
            'access_to_resources': 'Access To Resources',
            'access_needed_date': 'Access Needed By',
            'taught_by_another': 'Taught By Another',
            'another_instructor': 'Another Instructor Name',
        }

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{file_name}"'
        writer = csv.writer(response)

        # Write Header
        writer.writerow(fields.values())

        for record in records:
            row = []
            row.append(record.pk)
            row.append(record.future_course.academic_year)
            row.append(record.teacher_course.teacher_highschool.teacher.user.first_name)
            row.append(record.teacher_course.teacher_highschool.teacher.user.last_name)
            row.append(record.teacher_course.teacher_highschool.teacher.user.email)
            row.append(record.teacher_course.teacher_highschool.teacher.user.psid)
            row.append(record.teacher_course.course)
            row.append(record.teacher_course.teacher_highschool.highschool.name)
            row.append(record.added_on)

            row.append(record.section_info.get('teaching'))
            row.append(record.section_info.get('starting_date'))
            row.append(record.section_info.get('ending_date'))
            row.append(record.section_info.get('estimated_enrollment'))
            row.append(record.section_info.get('length_change'))
            row.append(record.section_info.get('access_to_resources'))
            row.append(record.section_info.get('access_date'))

            row.append(record.section_info.get('taught_by_another'))
            row.append(record.section_info.get('other_instructor'))
            writer.writerow(row)

        return response
