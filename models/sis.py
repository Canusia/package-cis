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
    
class SISSubscriptionManager(models.Manager):

    def purge_old_entries(self, days, result_codes=None):
        limit = datetime_now() - datetime.timedelta(days=days)

        query = self.filter(received_on__lt=limit)
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


class SIS_Subscription(models.Model):
    """
    Setting/Config model
    """
    received_on = models.DateTimeField(auto_now_add=True, null=True)
    message = JSONField(blank=True, default=dict)

    processed_message = JSONField(blank=True, default=dict)

    objects = SISSubscriptionManager()

    @property
    def message_id(self):
        return self.message['id']

    @property
    def processed_message_sexy(self):
        return '<br>'.join(self.processed_message)
    
    @property
    def sexy_message(self):
        result = []

        if self.message['content'].get('appliedOn'):
            result.append('Found Applied On date - ' + self.message['content'].get('appliedOn'))

        if self.message['content'].get('admittedOn'):
            result.append('Found Admitted On date - ' + self.message['content'].get('admittedOn'))

        if self.message['content'].get('matriculatedOn'):
            result.append('Found Matriculated On date - ' + self.message['content'].get('matriculatedOn'))

        if self.message['content'].get('personId'):
            result.append('Found Person ID - ' + self.message['content'].get('personId'))

        return result

    def process_section_registration(self):        
        self.processed_message = []

        try:
            registrant_id = self.message.get('content')['registrant']['id']
            section_id = self.message.get('content')['section']['id']

            status = self.message['content']['status']['registrationStatus']
            id = self.message['resource']['id']

            registration = StudentRegistration.objects.filter(
                sis_id=id
            )

            if registration.exists():
                if registration[0].status != status:
                    registration[0].status = status
                    registration[0].save()

                    self.processed_message.append('Updated registration status')
                else:
                    self.processed_message.append(f'No need to update registration status {status}')
            else:
                student = Student.objects.filter(
                    sis_id=registrant_id
                )

                if not student.exists():
                    self.processed_message.append(f'Unable to find student {registrant_id}')
            
                section = ClassSection.objects.filter(
                    meta__section_id=section_id
                )

                if not section:
                    self.processed_message.append(f'Unable to find section {section_id}')

                if student.exists() and section.exists():
                    registration = StudentRegistration.objects.filter(
                        student=student[0],
                        class_section=section[0]
                    )

                    if not registration.exists():
                        registration = StudentRegistration(
                            student=student[0],
                            class_section=section[0],
                            status=status,
                            highschool=section[0].highschool
                        )

                        registration.save()
                        self.processed_message.append(f'Added new registration for {student[0]}, section[0], status')
                    else:
                        regis = registration[0]
                        regis.sis_id = id
                        regis.status = status
                        regis.save()

                        self.processed_message.append(f'Assigned ID and status')
        except Exception as e:
            self.processed_message.append(str(e))

        self.save()

    def process(self, add_note_to_student=False):
        
        from cis.settings.sis_settings import sis_settings
        configs = sis_settings.from_db()

        guids = json.loads(configs.get('guids'))

        alternativeCredId = str(guids.get('alternativeCredentials'))

        self.processed_message = []

        if self.message['resource']['name'] == 'section-registrations':
            return self.process_section_registration()
        
        if self.message['resource']['name'] == 'persons':           
            sis_id = self.message['resource']['id']
            
            # check if record has altCred
            try:
                altCreds = self.message['content']['alternativeCredentials']
            except:
                self.processed_message.append('Unable to find alt credentials')
                self.save()
                return
            
            canusia_id = None
            for altCred in altCreds:
                if altCred['type']['id'] == alternativeCredId:
                    canusia_id = altCred['value']
                    self.processed_message.append(f'Found Canusia id {canusia_id}')

            bannerid = '-'
            banner_email = ''
            if not canusia_id:
                self.processed_message.append('Did not find Canusia ID')
                self.save()
            else:
                credentials = self.message['content']['credentials']
                
                for cred in credentials:
                    if cred['type'] == 'bannerId':
                        bannerid = cred['value']
                        self.processed_message.append(f'Found banner id {bannerid}')

                    if cred['type'] == 'bannerUserName':
                        banner_username = cred['value']
                        self.processed_message.append(f'Found banner username {banner_username}')

                emails = self.message['content']['emails']
                for email in emails:
                    if email.get('preference') == 'primary':
                        banner_email = email['address']
                        self.processed_message.append(f'Found banner email {banner_email}')
            try:
                student = Student.objects.get(pk=canusia_id)
                student.sis_id = sis_id
                student.save()

                student.user.psid = bannerid
                student.user.alt_username = banner_username
                student.user.secondary_email = banner_email
                student.user.save()

                student.add_note(None, f'Found SIS ID {sis_id}')
                self.processed_message.append(f'Added Banner ID to {student}')
            except:
                self.processed_message.append(f'Unable to find student record in Canusia for {canusia_id}')
        
            self.save()

    @property
    def student(self):
        try:
            student = Student.objects.filter(
                id=self.message['content']['applCrmApplicationNo']
            )

            if student:
                return student
        except:
            ...
        return None

    @property
    def student_name(self):
        student = self.student
        if student:
            return student[0].user.last_name + ", " + student[0].user.first_name

        return 'N/A'

    @property
    def student_id(self):
        student = self.student
        if student:
            return student[0].id

        return None

    def __str__(self):
        return f"{self.message['id']}"


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

class SIS_SubscriptionSerializer(serializers.ModelSerializer):

    received_on = serializers.DateTimeField(
        format='%Y-%m-%d %I:%M %p'
    )

    message_id = serializers.CharField()
    # message_type = serializers.CharField()
    
    student_name = serializers.CharField()
    student_id = serializers.CharField()

    sexy_message = serializers.ListField()

    class Meta:
        model = SIS_Subscription
        fields = '__all__'

        datatables_always_serialize = [
            # 'student_id',
            'message',
        ]
