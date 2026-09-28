# users/models.py
import uuid, datetime, json
from django.db import models
from django.db.models import JSONField
from django.urls import reverse_lazy

from rest_framework import serializers

from cis.models.student import Student
from cis.models.section import StudentRegistration, ClassSection

from django.utils.timezone import now as datetime_now

class SISLogManager(models.Manager):

    def purge_old_entries(self, days, result_codes=None):
        limit = datetime_now() - datetime.timedelta(days=days)

        query = self.filter(sent_on__lt=limit)
        count = query.count()

        query.delete()
        return count
    
class SIS_Log(models.Model):
    sent_on = models.DateTimeField(auto_now_add=True, null=True)

    MESSAGE_TYPE = [
        ('person_create', 'Person Create'),
        ('class_registered', 'Register'),
        ('class_dropped', 'Drop'),
        ('class_list', 'Class List')
    ]
    message_type = models.CharField(max_length=50, choices=MESSAGE_TYPE)
    
    message = JSONField(blank=True, default=dict)
    response = JSONField(blank=True, default=dict)

    objects = SISLogManager()

    @property
    def ce_url(self):
        return reverse_lazy('cis:sis_log_details', kwargs={
            'record_id': self.id})

    @property
    def error_message(self):
        return self.response.get('message')

    @property
    def response_code(self):
        return self.response.get('status', '-')

    @property
    def sexy_message_type(self):
        print(self.message)
        return self.message.get('url').replace('https://integrate.elluciancloud.com/api', '')
        for k, v in self.MESSAGE_TYPE:
            if self.message_type == k:
                return v
        return 'N/A'

    @property
    def sexy_message(self):
        return self.message
    
        messages = []

        try:
            if self.message_type == 'class_registered':
                student_id = self.message['data'].get('registrant')['id']
                class_section_id = self.message['data'].get('section')['id']

                registration = StudentRegistration.objects.filter(
                    student__sis_id=student_id,
                    class_section__class_number=class_section_id
                )

                if registration:
                    messages.append(
                        f'Sent request for {registration[0].student.user.last_name}, {registration[0].student.user.first_name} - {registration[0].class_section.course.name}-{registration[0].class_section.section_number} / {registration[0].class_section.term.code}'
                    )
                else:
                    messages.append(
                        'Unable to find registration'
                    )
        
            if self.message_type == 'person_create':
                student_id = self.message['data'].get('CrmApplicationId')
                student = Student.objects.filter(
                    id=student_id
                )

                if student:
                    messages.append(f'Sent request for {student[0].user.last_name}, {student[0].user.first_name}')
                else:
                    messages.append('Unable to find student')
        except:
            ...
            
        return messages


class SIS_LogSerializer(serializers.ModelSerializer):
    sent_on = serializers.DateTimeField(
        format='%Y-%m-%d %I:%M %p'
    )

    sexy_message_type = serializers.CharField()
    error_message = serializers.CharField()
    response_code = serializers.CharField()
    sexy_message = serializers.ListField()
    ce_url = serializers.CharField()
    
    class Meta:
        model = SIS_Log
        fields = '__all__'

        datatables_always_serialize = [
            'error_message',
            'id',
            'ce_url'
        ]
