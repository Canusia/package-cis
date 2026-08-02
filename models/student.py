# users/models.py
import uuid, logging, json
from datetime import datetime

import pdfkit

from django.template import Context, Template
from django.template.loader import get_template
from django.shortcuts import render
from django.http import HttpResponse

from django.conf import settings
from django.db import models
from model_utils import FieldTracker
from simple_history.models import HistoricalRecords

from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.urls import reverse_lazy
from django.utils.safestring import mark_safe

from django.template import Context, Template
from django.contrib.auth.models import Group

from mailer import send_mail, send_html_mail

from cis.validators import validate_email
from cis.utils import (
    format_emplid, getDomain,
    student_recommendation_upload_path,
    model_as_HTML, is_student_registration_open
)

logger = logging.getLogger(__name__)

from cis.storage_backend import PrivateMediaStorage

from cis.models.note import StudentNote
from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.section import StudentRegistration

from cis.utils import (
    YES_NO_OPTIONS, STUDENT_GRADE_OPTIONS, STUDENT_GPA_OPTIONS,
    registration_terms,
    student_tuition_assistance_upload_path,
    student_supporting_doc_upload_path
)

from ..settings.registration_email import registration_email
from ..settings.signup import signup as signup_settings
from ..settings.registrations import registrations as reg_settings

from django.db.models import JSONField
from multiselectfield import MultiSelectField

from ..models.settings import Setting


class StudentSISError(models.Model):
    """
    Student SIS Import model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    student = models.ForeignKey(
        'cis.Student',
        on_delete=models.PROTECT
    )

    message = models.CharField(max_length=500, blank=True)
    match_results = JSONField(blank=True)
    created_on = models.DateTimeField(auto_now_add=True)

    STATUS_OPTIONS = (
        ('Pending', 'Pending'),
        ('Processed', 'Processed')
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_OPTIONS,
        default='Pending'
    )

    def asHTML(self):
        result = "<div class='details'>"
        result += "<div class='row p-2'>"
        result += "<div class='col-md-6'>"
        result += "<div class='detail_label'>" + 'Error' + "</div>"
        result += "<div class=''>"
        result += self.message
        result += "</div>"
        result += "</div>"

        result += "<div class='col-md-6'>"
        result += "<div class='detail_label'>" + 'Match Results' + "</div>"
        result += "<div class=''>"
        for match in self.match_results:
            result += match['MatchIds'] + " (" + match['MatchCategories'] + ' - ' + match['MatchRatings'] + ")" + "<br>"
        result += "</div>"
        result += "</div>"

        result += "</div>"
        result += "</div>"
        return result

class Student(models.Model):
    """
    Student model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField('cis.CustomUser', on_delete=models.PROTECT)

    # created_on = models.DateTimeField(auto_now_add=True)
    # auto_id = models.AutoField()

    last_updated_on = models.DateTimeField(auto_now=True, blank=True, null=True)
    history = HistoricalRecords()

    profile_last_reviewed = models.ForeignKey(
        'cis.Term',
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name='profile_last_reviewed'
    )

    profile_dirty_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text='Set when the student edits their own profile. Cleared by staff after review.',
    )

    current_student_balance = models.FloatField(default=0.0)
    current_school_balance = models.FloatField(default=0.0)

    verification_id = models.UUIDField(blank=True, null=True, primary_key=False, editable=False)
    account_verified = models.BooleanField(default=False)
    account_verified_on = models.DateTimeField(blank=True, null=True)

    sis_id = models.UUIDField(blank=True, null=True)
    sis_sent_on = models.DateTimeField(blank=True, null=True)
    sis_applied_on = models.DateTimeField(blank=True, null=True)
    sis_admitted_on = models.DateTimeField(blank=True, null=True)
    sis_matriculated_on = models.DateTimeField(blank=True, null=True)

    SIS_STATUS = [
        ('pending', 'Pending'),
        ('request_sent', 'Request Sent'),
        ('admitted', 'Admitted, waiting Matriculation'),
        ('matriculated', 'Matriculated')
    ]
    sis_status = models.CharField(max_length=20, choices=SIS_STATUS, default='pending')

    APPLICATION_STATUS_CHOICES = (
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('in_review', 'In Review'),
        ('accepted', 'Accepted'),
    )
    application_status = models.CharField(
        max_length=20,
        choices=APPLICATION_STATUS_CHOICES,
        default='draft',
        db_index=True,
    )
    tracker = FieldTracker(fields=['highschool_id', 'application_status'])

    highschool = models.ForeignKey(
        'cis.Highschool', on_delete=models.PROTECT,
        blank=True, null=True
    )
    cte = models.ForeignKey(
        'cis.Highschool', on_delete=models.PROTECT,
        blank=True, null=True, related_name='cte_students'
    )
    student_id = models.CharField(max_length=50, blank=True)
    preferred_name = models.CharField(max_length=50, blank=True, null=True)

    pidm = models.CharField(max_length=50, blank=True)
    # holds = models.CharField(max_length=100, blank=True)
    # college_gpa = models.CharField(max_length=10, blank=True, null=True)
    tuition_owed = models.FloatField(blank=True, null=True)

    graduation_date = models.DateField(blank=True, null=True)
    graduation_year = models.SmallIntegerField(blank=True, null=True)

    parent_first_name = models.CharField(max_length=50, blank=True)
    parent_last_name = models.CharField(max_length=50, blank=True)
    parent_email = models.CharField(max_length=50, blank=True)
    parent_phone = models.CharField(max_length=50, blank=True, null=True)
    parent_test = models.CharField(max_length=50, blank=True, null=True)

    state_id = models.CharField(max_length=50, blank=True, null=True)

    PARENT_EDUCATION_OPTIONS = [
        ('', 'Select'),
        ('1', 'Unknown'),
        ('2', 'High school/GED'),
        ('3', 'Some college, no degree'),
        ('4', 'Associate degree (e.g., AA, AS)'),
        ('5', 'Bachelor\'s degree (e.g., BA, BS)'),
        ('6', 'Some graduate school, no degree'),
        ('7', 'Graduate Degree or higher'),
        ('8', 'Unknown / Prefer not to answer'),
    ]

    PARENT_INTEREST_OPTIONS = [
        ('', 'Select'),
        ('1', 'Not Interested'),
        ('2', 'Interested in Online Bachelor\’s'),
        ('3', 'Certificate'),
        ('4', 'Graduate Programs.'),
    ]

    parent1_education_level = models.CharField(
        choices=PARENT_EDUCATION_OPTIONS,
        blank=True,
        max_length=2
    )

    parent2_education_level = models.CharField(
        choices=PARENT_EDUCATION_OPTIONS,
        blank=True,
        max_length=2
    )

    GENDER_OPTIONS = [
        ('', 'Select'),
        ('m', 'Male'),
        ('f', 'Female'),
        ('u', 'Undisclosed'),
    ]
    gender = models.CharField(max_length=10, choices=GENDER_OPTIONS)

    ETHNICITY_OPTIONS = (
        (1, 'American Indian or Alaska Native'),
        (2, 'Asian'),
        (3, 'Black or African American'),
        (4, 'Native Hawaiian or Other Pacific Islander'),
        (5, 'White'),
    )

    TRUE_FALSE_CHOICES = (
        ('', 'Select'),
        (True, 'Yes'),
        (False, 'No')
    )
    hispanic = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        choices=TRUE_FALSE_CHOICES
    )
    ethnicity = MultiSelectField(
        max_length=200,
        choices=ETHNICITY_OPTIONS,
        blank=True)
    

    GENDER_IDENTITY_OPTIONS = [
        ('', 'Select'),
        ('M', 'Man'),
        ('F', 'Woman'),
        ('NB', 'Nonbinary/Gender Nonconforming'),
        ('T', 'Transgender'),
        ('O', 'Other'),
        ('U', 'Unknown/Not Provided')
    ]
    gender_identity = models.CharField(max_length=10, choices=GENDER_OPTIONS, default='', null=True)

    GENDER_PRONOUN_OPTIONS = [
        ('', 'Select'),
        ('He/Him', 'He/Him'),
        ('She/Her', 'She/Her'),
        ('They/Them', 'They/Them'),
        ('Other', 'Other'),
    ]
    gender_pronoun = models.CharField(max_length=20, choices=GENDER_OPTIONS, default='', null=True)

    HISPANIC_BACKGROUND = (
        (1, 'Central American'),
        (2, 'Dominican'),
        (3, 'Puerto Rican'),
        (4, 'South American'),
        (5, 'Mexican'),
        (6, 'Other/Hispanic/Latino'),
    )

    hispanic_background = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        choices=HISPANIC_BACKGROUND
    )

    FRESHMAN = 'FR'
    SOPHOMORE = 'SO'
    JUNIOR = 'JR'
    SENIOR = 'SR'
    GRADE_LEVEL = [
        ('', 'Select'),
        (SENIOR, 'Senior'),
        (JUNIOR, 'Junior'),
        (SOPHOMORE, 'Sophomore'),
        (FRESHMAN, 'Freshman'),
    ]

    GRADE_LEVEL = [
        ('', 'Select'),
        (SENIOR, 'Senior - 12th grade'),
        (JUNIOR, 'Junior- 11th grade'),
        (SOPHOMORE, 'Sophomore - 10th grade'),
        (FRESHMAN, 'Freshman - 9th grade'),
    ]

    notifications = JSONField(blank=True, null=True)
    meta = JSONField(default=dict, blank=True, null=True)

    grade_level = models.CharField(max_length=2, choices=GRADE_LEVEL, blank=True)
    first_gen_student = models.CharField(max_length=2, choices=YES_NO_OPTIONS, blank=True)

    # grade_level = models.CharField(max_length=2, choices=GRADE_LEVEL, blank=True)
    # att_credits = models.SmallIntegerField(blank=True, null=True)

    # english = models.CharField(max_length=10, blank=True, null=True)
    # math = models.CharField(max_length=10, blank=True, null=True)
    # composite = models.CharField(max_length=10, blank=True, null=True)
    # aleks = models.CharField(max_length=10, blank=True, null=True)

    REQUIRED_HEADERS = [
        'first_name', 'last_name', 'email', 'college_email', 'banner_id', 'highschool_ceeb', 'cellphone'
    ]
    class Meta:
        ordering = ['user__first_name']

    def needs_recommendation(self, term_id):       
        from django.db.models import Q

        classes_needing_recommendation = StudentRegistration.objects.filter(
            Q(student=self) &
            Q(status__in=['applied', 'registered', 'approved']) &
            Q(class_section__registration_term__id=term_id) & 
            (
                (
                    Q(class_section__course__registration_eligibility__contains='SO*') &
                    Q(student__grade_level__in=['SO'])
                    
                ) | (
                    Q(class_section__course__registration_eligibility__contains='FR*') &
                    Q(student__grade_level__in=['FR'])
                )
            )
        )

        if not classes_needing_recommendation.exists():
            return False
        
        # has classes needing recommendation, check if recommendations exist for term_id
        if StudentRecommendation.objects.filter(
            student=self,
            term__id=term_id
        ).exists():
            return False
        return True

    @property
    def suid(self):
        if self.user.psid in [None, '-', '']:
            return 'Not Assigned Yet'
        return self.user.psid
    
    def reset_allow_late_billpay(self):
        if not self.notifications:
            self.notifications = {}

        self.notifications['allow_late_billpay'] = '2'
        self.save()
    
    def enable_allow_late_billpay(self):
        if not self.notifications:
            self.notifications = {}

        self.notifications['allow_late_billpay'] = '1'
        self.save()

    def get_payment_url(cls, student_id, term_id):
        return getDomain() + str(reverse_lazy('student:direct_bill_pay', kwargs={
            'student_id': student_id,
            'term_id': term_id}))

    @property
    def allow_late_billpay(self):
        if not self.notifications:
            return False
            
        if self.notifications.get('allow_late_billpay') == '1':
            return True
        return False

    @property
    def qualify_tuition_assistance(self):
        if not self.meta.get('qualify_tuition_assistance'):
            return False

        if self.meta.get('qualify_tuition_assistance') in ['False', False]:
            return False

        return True

    @property
    def is_sent_to_sis(self):
        """Check if student has been sent to SIS"""
        return (self.user.psid and len(self.user.psid) >= 5) or self.sis_sent_on

    @property
    def allow_late_billpay_sexy(self):
        return 'Yes' if self.allow_late_billpay else 'No'
    
    def debits(self, term=None, label='class_charge', sequence_only=False):
        from student_transactions.models import StudentTransaction

        records = StudentTransaction.objects.filter(
            student=self,
            t_type='debit'
        )

        if sequence_only & False:
            sequence_sections = StudentRegistration.objects.filter(
                student=self,
                class_section__is_sequence='1'
            )

            if term:
                sequence_sections = sequence_sections.filter(
                    class_section__term=term
                )
            
            sequence_section_ids = []
            for seq_section in sequence_sections:
                sequence_section_ids.append(str(seq_section.id))
            
            records = records.filter(
                meta__registration__in=sequence_section_ids
            )

        if label != 'school_charge':
            records = records.exclude(label='school_charge')
        else:
            records = records.filter(label=label)

        if term:
            records = records.filter(term=term)

        records = records.order_by('-created_on')
        return records
        
    def credits(self, term=None, label=None):
        from student_transactions.models import StudentTransaction

        records = StudentTransaction.objects.filter(
            student=self,
            t_type='credit'
        )

        if label:
            if label == 'school_pay':
                label = [
                    'school_pay',
                    '2'
                ]
            records = records.filter(label__in=label)
        else:
            records = records.exclude(
                label__in=['school_pay', '2']
            )

        if term:
            records = records.filter(term=term)

        records = records.order_by('-created_on')
        return records

    def student_payment_amounts(self, term):
        amounts = []

        if self.current_student_balance <= 0:
            return amounts
        
        today = datetime.now()
        payment_due_date = datetime.strptime(
            term.dates.get('payment_due_date', '11/18/2032'),
            '%m/%d/%Y'
        )
        # sequence_class_payment_due_date = None
        # if term.dates.get('sequence_class_payment_due_date'):
        #     sequence_class_payment_due_date = datetime.strptime(
        #         term.dates.get('sequence_class_payment_due_date'),
        #         '%m/%d/%Y'
        #     )

        # # if student has sequence charges
        # sequence_charges = self.debits(
        #     term, 'class_charge', sequence_only=True
        # )
        # total_sequence_charges = sequence_charges.aggregate(models.Sum('amount'))

        # if total_sequence_charges['amount__sum'] == None:
        #     total_sequence_charges = 0
        # else:
        #     total_sequence_charges = total_sequence_charges['amount__sum']
        
        total_sequence_charges = 0
        # if self.current_student_balance > total_sequence_charges:
        #     # if within current term payment due date
        #     if today < payment_due_date:
        #         amounts.append(
        #             (f"due on {term.dates.get('payment_due_date', '11/18/2032')}", (self.current_student_balance - total_sequence_charges))
        #         )

            # if sequence_class_payment_due_date and today < sequence_class_payment_due_date:
            #     if self.current_school_balance < total_sequence_charges:
            #         amounts.append(
            #             (f"Sequence Class(es) Tuition due on {term.dates.get('sequence_class_payment_due_date', '01/03/2025')}", total_sequence_charges)
            #         )

        if total_sequence_charges > 0 and self.current_student_balance == total_sequence_charges:
            ...
            # amounts.append(
            #             (f"Sequence Class(es) Tuition due on {term.dates.get('sequence_class_payment_due_date', '01/03/2025')}", total_sequence_charges)
            #         )
        else:
            amounts.append(
                (f'Total Balance', self.current_student_balance)
            )

        return amounts
                
    @property
    def is_eligible_to_pay_sexy(self):
        result, reasons = self.is_eligible_to_pay()

        return '<br>'.join(reasons)
    
    def is_eligible_to_pay(self):
        reasons = []
        if self.current_student_balance <= 0:
            reasons.append('No student balance')
        
        if not self.has_signed_student_agreement():
            reasons.append('Missing Student Agreement')
            
        student_classes = StudentRegistration.objects.filter(
            student=self
        )
        # if student_classes.filter(status__in=['applied']).count() > 0:
        #     reasons.append('Some classes are waiting on school review')

        # if self.qualify_tuition_assistance:
        #     # has processed TA
        #     if self.has_faa():
        #         # check if it is marked as processed
        #         if not self.has_faa_processed():
        #             reasons.append('TA application is not yet processed')
        #     # else:
        #     #     # check if FAA application window is open
        #     #     if is_tuition_assistance_open():
        #     #         reasons.append('Not applied for TA')
                    
        if not reasons:
            return (True, reasons)
        return (False, reasons)
    
    def has_faa(self):
        from cis.utils import active_term

        return StudentTuitionAssistance.objects.filter(
            student=self,
            term=active_term()
        ).exists()
    
    def student_balance(self, term=None, sequence=False):

        charges = self.debits(term, 'class_charge', sequence_only=sequence)
        
        total_charges = charges.aggregate(models.Sum('amount'))
                
        if total_charges['amount__sum'] == None:
            total_charges = 0
        else:
            total_charges = total_charges['amount__sum']

        payments = self.credits(term, label=None)
        # charges = charges.exclude(label='2')

        total_payments = payments.aggregate(models.Sum('amount'))

        if total_payments['amount__sum'] == None:
            total_payments = 0
        else:
            total_payments = total_payments['amount__sum']

        return float(total_charges) - float(total_payments)

    def school_balance(self, term=None):

        charges = self.debits(term, 'school_charge')
        total_charges = charges.aggregate(models.Sum('amount'))

        if total_charges['amount__sum'] == None:
            total_charges = 0
        else:
            total_charges = total_charges['amount__sum']
        
        payments = self.credits(term, label='school_pay')
        total_payments = payments.aggregate(models.Sum('amount'))

        if total_payments['amount__sum'] == None:
            total_payments = 0
        else:
            total_payments = total_payments['amount__sum']

        return float(total_charges) - float(total_payments)

    def format_balance(self, term):
        balance = self.balance(term)
        
        return "${:,.2f}".format(balance)
        

    def has_banner_id(self):
        if self.user.psid.startswith('R') and self.user.secondary_email.endswith('@mail.rmu.edu'):
            return True
        return False
        

    def get_grade_level(self, graduation_year=None, graduation_date=None):
        """
        Given a student's high school graduation year (or full date), returns:
        'FR' - Freshman
        'SO' - Sophomore
        'JR' - Junior
        'SR' - Senior
        'GRAD' - Already graduated

        Academic year runs roughly August–June. When only a year is known, we
        assume graduation happens at the end of that academic year and treat
        June onward as "advanced a grade". When the actual ``graduation_date``
        is supplied it takes precedence over that heuristic — a student whose
        graduation date is still in the future has NOT graduated, even if it is
        already June (e.g. early June, graduating mid-June).
        """

        today = datetime.now().date()

        grad_date = graduation_date
        if grad_date is not None:
            if hasattr(grad_date, "date"):  # datetime -> date
                grad_date = grad_date.date()
            graduation_year = grad_date.year

        try:
            if not graduation_year:
                years_to_graduation = int(self.graduation_year) - today.year
            else:
                years_to_graduation = int(graduation_year) - today.year
        except Exception as e:
            logger.error(e)
            print(e)
            return '--'

        # After June the academic year has rolled over and the student has
        # advanced a grade — UNLESS we know the actual graduation date and it
        # is still in the future, in which case they haven't advanced yet.
        not_yet_graduated = grad_date is not None and grad_date >= today
        if today.month >= 6 and not not_yet_graduated:
            years_to_graduation -= 1

        mapping = {
            3: "FR",   # 3 years until graduation
            2: "SO",   # 2 years
            1: "JR",   # 1 year
            0: "SR",   # graduating this year
        }

        # If graduation is in the past
        if years_to_graduation < 0:
            return "GRAD"

        return mapping.get(years_to_graduation, None)  # None if outside expected range

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        #if self._state.adding is True
        group = Group.objects.get(name='student')
        self.user.groups.add(group)

    @property
    def current_balance(self):
        return round(self.current_student_balance, 2)
    
    @property
    def ferpa_completed_for(self):
        return self.meta.get('ferpa_completed_for')
    
    @property
    def start_term(self):
        if self.meta and self.meta.get('start_term'):
            return self.meta.get('start_term')
        from cis.utils import active_term
        return active_term().code if active_term() else None
    
    @property
    def ferpa_completed_on(self):
        return self.meta.get('ferpa_completed_on')
    
    @property
    def state_q_completed_for(self):
        return self.meta.get('state_q_completed_for')
    
    @property
    def state_q_completed_on(self):
        return self.meta.get('state_q_completed_on')
    
    @property
    def verify_email(self):
        from ..utils import getDomain

        if not self.verification_id:
            self.reset_verification_id()
            
        return getDomain() + str(
            reverse_lazy(
                'student:verify_email',
                kwargs={
                    # 'student_id': self.id,
                    'verification_id': self.verification_id
                })
        )

    @property
    def parent_name(self):
        first = self.parent_first_name or ''
        last = self.parent_last_name or ''
        combined = f"{first} {last}".strip()
        if combined:
            return combined
        return (self.meta or {}).get('parent_name', '')

    @property
    def mailing_address(self):
        return (self.meta or {}).get('mailing_address', '')

    @property
    def mailing_address2(self):
        return (self.meta or {}).get('mailing_address2', '')

    @property
    def mailing_city(self):
        return (self.meta or {}).get('mailing_city', '')

    @property
    def mailing_state(self):
        return (self.meta or {}).get('mailing_state', '')

    @property
    def mailing_zip_code(self):
        return (self.meta or {}).get('mailing_zip_code', '')

    @property
    def mailing_country(self):
        return (self.meta or {}).get('mailing_country', '')

    @property
    def highschool_start_date(self):
        if not self.meta.get('highschool_start_date'):
            return None
        return datetime.strptime(
            self.meta.get('highschool_start_date'),
            '%Y-%m-%d')
    
    @property
    def residency_date(self):
        if not self.meta.get('residency_date'):
            return None
        return datetime.strptime(
            self.meta.get('residency_date'),
            '%Y-%m-%d')
    
    @property
    def parent2_name(self):
        return self.meta.get('parent2_name')
    
    @property
    def sevis_id(self):
        return self.meta.get('sevis_id')
    
    @property
    def parent2_email(self):
        return self.meta.get('parent2_email')
    
    @property
    def parent2_phone(self):
        return self.meta.get('parent2_phone')
    
    # @property
    # def parent2_education_level(self):
    #     return self.meta.get('parent2_education_level')

    @property
    def other_college_credits(self):
        return self.meta.get('other_college_credits')
    
    @property
    def other_college_credits_sexy(self):
        return 'Yes' if self.other_college_credits == '1' else 'No'

    @property
    def college_attended_1(self):
        if self.meta.get('college_attended_1'):
            return self.meta.get('college_attended_1')[0] + ',' + self.meta.get('college_attended_1')[1] + ',' + self.meta.get('college_attended_1')[2] + ',' + self.meta.get('college_attended_1')[3] + ',' + self.meta.get('college_attended_1')[4] + ',' + self.meta.get('college_attended_1')[5]
        
    @property
    def college_attended_2(self):
        if self.meta.get('college_attended_2'):
            return self.meta.get('college_attended_2')[0] + ',' + self.meta.get('college_attended_2')[1] + ',' + self.meta.get('college_attended_2')[2] + ',' + self.meta.get('college_attended_2')[3] + ',' + self.meta.get('college_attended_2')[4] + ',' + self.meta.get('college_attended_2')[5]
            
    @property
    def college_attended_3(self):
        if self.meta.get('college_attended_3'):
            return self.meta.get('college_attended_3')[0] + ',' + self.meta.get('college_attended_3')[1] + ',' + self.meta.get('college_attended_3')[2] + ',' + self.meta.get('college_attended_3')[3] + ',' + self.meta.get('college_attended_3')[4] + ',' + self.meta.get('college_attended_3')[5]
    
    @property
    def colleges_attended(self):
        result = ""
        if self.meta.get('college_attended_1'):
            result += self.meta.get('college_attended_1')[0] + '<br>' + self.meta.get('college_attended_1')[1] + '<br>' + self.meta.get('college_attended_1')[2] + '<br>'
        if self.meta.get('college_attended_2'):
            result += self.meta.get('college_attended_2')[0] + '<br>' + self.meta.get('college_attended_2')[1] + '<br>' + self.meta.get('college_attended_2')[2] + '<br>'
        if self.meta.get('college_attended_3'):
            result += self.meta.get('college_attended_3')[0] + '<br>' + self.meta.get('college_attended_3')[1] + '<br>' + self.meta.get('college_attended_3')[2] + '<br>'

        return result
    
    @property
    def us_citizen(self):
        return self.meta.get('us_citizen')
    
    @property
    def parent_education(self):
        return self.meta.get('parent_education')
    
    @property
    def parent2_email(self):
        return self.meta.get('parent2_email')
    
    @property
    def parent2_phone(self):
        return self.meta.get('parent2_phone')
    
    @property
    def emergency_relationship_type(self):
        return self.meta.get('emergency_relationship_type')
    
    @property
    def emergency_contact_name(self):
        return self.meta.get('emergency_contact_name')
    
    @property
    def emergency_contact_phone(self):
        return self.meta.get('emergency_contact_phone')
    
    @property
    def emergency_contact_email(self):
        return self.meta.get('emergency_contact_email')
    
    @property
    def father_education(self):
        return self.meta.get('father_education')
    
    @property
    def mother_education(self):
        return self.meta.get('mother_education')
    
    @property
    def military_family(self):
        return self.meta.get('military_family')
    
    @property
    def homeless(self):
        return self.meta.get('homeless')
    
    @property
    def education_plans(self):
        return self.meta.get('education_plans')
    
    @property
    def plan_to_transfer(self):
        return self.meta.get('plan_to_transfer')
    
    @property
    def transfer_where(self):
        return self.meta.get('transfer_where')
    
    @property
    def foreign_born(self):
        return self.meta.get('foreign_born')
    
    @property
    def birth_place(self):
        return self.meta.get('birth_place')
    
    @property
    def been_outside_us(self):
        return self.meta.get('been_outside_us')
    
    @property
    def outside_where(self):
        return self.meta.get('outside_where')
    
    @property
    def contact_with_tb(self):
        return self.meta.get('contact_with_tb')
    
    @property
    def any_symptoms(self):
        return self.meta.get('any_symptoms')
    
    @property
    def contact_by_ds(self):
        return self.meta.get('contact_by_ds')
        
    def has_signed_parent_consent_for_term(self, term):
        return ParentConsent.has_signed(self, term)

    def generate_account_statement(self, request=None):

        base_template = 'transactions/receipt.html'
        template = get_template(base_template)

        from cis.utils import active_term as get_active_term
        from cis.models.section import StudentRegistration
        from cis.settings.registration_charges import registration_charges

        template_settings = registration_charges.from_db()

        header_template = Template(template_settings.get('invoice_template_header', 'change me'))
        footer_template = Template(template_settings.get('invoice_template_footer', 'change me'))
        
        active_term = get_active_term()    

        student = self
        payment_amounts = student.student_payment_amounts(active_term)
        is_eligible_to_pay, missing_items = student.is_eligible_to_pay()
        
        charges = student.debits()
        payments = student.credits()
        full_balance = student.student_balance()

        try:
            formatted_balance = float(full_balance)
            formatted_balance = "${:,.2f}".format(formatted_balance)
        except:
            formatted_balance = full_balance

        from cis.utils import qr_code

        qrcode = None
        if student.current_student_balance > 0:
            if not is_eligible_to_pay:
                if not student.has_signed_parent_consent_for_term(active_term.id):
                    url = ParentConsent.get_url(student.id, active_term.id)
                    qrcode = qr_code(url + '?scaned=1')    
            else:
                qrcode = qr_code(student.get_payment_url(student.id, active_term.id) + '?scaned=1')

        context = Context({
            'record': student,
            'highschool': student.highschool,
            'address': student.sexy_address,
            'suid': student.suid,
            'balance': full_balance,
            'formatted_balance': formatted_balance,
            'qrcode': qrcode,
        })
        header_template = header_template.render(context)
        footer_template = footer_template.render(context)

        html = template.render({
            
            'header': header_template,
            'classes': StudentRegistration.objects.filter(
                student=student
            ),
            'missing_items': missing_items,
            'charges': charges,
            'payments': payments,
            'balance': full_balance,
            'payment_amounts': payment_amounts,
            'record': student,

            'qrcode': qrcode,
            'generated_on': datetime.now(),
            'footer': footer_template
        })


        if request and request.GET.get('mode') == 'page':
            return HttpResponse(html)

        options = {
            'page-size': 'Letter'
        }
        pdf = pdfkit.from_string(html, False, options)

        return pdf

    def generate_unofficial_transcript(self, request=None):
        """
        Generate an unofficial transcript PDF for the student.

        Uses configurable templates from class_section_grades settings for
        header, table header, row template, and footer.

        Args:
            request: Optional HTTP request. If request.GET.get('mode') == 'page',
                     returns HTML instead of PDF.

        Returns:
            PDF bytes or HttpResponse with HTML if mode=page
        """
        # The rendering itself lives in the optional ``grades`` app; this method
        # is kept so existing callers and URLs are unaffected. Returns None when
        # grades is not installed.
        from cis.integrations.grades import render_transcript

        return render_transcript(self, request=request)

    def send_payment_url(self, term_id, mode='active'):
        student = self

        from cis.settings.registration_charges import registration_charges
        from cis.utils import bill_due_date
        email_settings = registration_charges.from_db()
        email_template = Template(email_settings.get('parent_bill_email', 'change me'))

        url = self.get_payment_url(self.id, term_id)

        context = Context({
            'recipient': 'student',
            'payment_url': url,
            'bill_due_date': bill_due_date(),
            # 'sequence_bill_due_date': sequence_class_tuition_pay_end_date(),
            'student_first_name': student.user.first_name,
            'student_last_name': student.user.last_name
        })
        text_body = email_template.render(context)
        try:            
            to = [student.user.email]
        except:
            ...

        if getattr(settings, 'DEBUG', True) or mode == 'debug':
            to = ['kadaji@gmail.com', 'akadajis@syr.edu']

        subject = email_settings.get('parent_bill_email_subject', 'change me')

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })

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

        # email the parent(s)
        email_template = Template(email_settings.get('parent_bill_email', 'change me'))

        url = self.get_payment_url(self.id, term_id)

        context = Context({
            'recipient': 'parent',
            'payment_url': url,
            'parent_first_name': student.parent_first_name,
            'student_first_name': student.user.first_name,
            'student_last_name': student.user.last_name
        })
        text_body = email_template.render(context)
        try:
            validate_email(student.parent_email)
            to = [student.parent_email]
        except:
            ...

        try:
            validate_email(student.parent2_email)
            to = [student.parent2_email]
        except:
            ...

        if getattr(settings, 'DEBUG', True) or mode == 'debug':
            to = ['kadaji@gmail.com', 'akadajis@syr.edu']

        subject = email_settings.get('parent_bill_email_subject', 'change me')

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })

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

    @property
    def qualify_tuition_assistance(self):
        if not self.meta.get('qualify_tuition_assistance'):
            return False
        
        if self.meta.get('qualify_tuition_assistance') == 'False':
            return False
        
        return True
    
    @property
    def emergency_contact(self):
        name = ''
        if self.emergency_contact_name:
            name += self.emergency_contact_name + ' <br> ' 

        if self.emergency_contact_phone:
            name += self.emergency_contact_phone + ' <br> '
        
        if self.emergency_contact_email:
            name += self.emergency_contact_email + ' <br> '
        
        if self.emergency_relationship_type:
            name += self.emergency_relationship_type

        return name
    
    @property
    def signature(self):
        return self.meta.get('signature')
    
    @property
    def highschool_graduation_month(self):
        try:
            return self.graduation_date.strftime('%m')
        except:
            ''

    @property
    def highschool_graduation_year(self):
        try:
            return self.graduation_date.strftime('%Y')
        except:
            ''

    def send_welcome_email(self):

        from cis.settings.registration_email import registration_email
        
        email_settings = registration_email.from_db()

        email_template = Template(email_settings['new_user_email'])
        subject = email_settings.get('new_user_email_subject')

        context = Context({
            'student_first_name': self.user.first_name,
            'student_last_name': self.user.last_name,
            'student_email': self.user.email,
        })
        text_body = email_template.render(context)
        to = [self.user.email]

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })
        
        if getattr(settings, 'DEBUG', True):
            to = ['kadaji@gmail.com']
        
        send_html_mail(
            subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            to
        )

    @staticmethod
    def get_student_signup_intro(account_verified=True):
        reg_options = signup_settings.from_db()
        if account_verified:
            return reg_options.get('intro')
        return reg_options.get('email_verify_intro')


    @property
    def total_approved_sections(self):
        from cis.utils import registration_terms
        from cis.models import StudentRegistration

        return StudentRegistration.objects.filter(
            student=self,
            class_section__term__in=registration_terms(),
            status__in=['approved_by_instructor', 'registered', 'approved']
        ).count()
    
    def send_psid_assigned_email(self):
    
        from cis.settings.registration_email import registration_email
        from django.conf import settings

        from_email = getattr(settings, 'DEFAULT_FROM')
        email_settings = registration_email.from_db()

        email_template = Template(email_settings['id_assigned_email'])
        subject = email_settings.get('id_assigned_subject')

        context = Context({
            'student_first_name': self.user.first_name,
            'student_id': self.user.psid,
            'student_last_name': self.user.last_name
        })
        text_body = email_template.render(context)
        to = [self.user.email]

        if getattr(settings, 'DEBUG', True):
            to = ['kadaji@gmail.com']
        else:
            self.student.add_note(None, 'Sent EMPLID assigned email')
            
        email_message = EmailMultiAlternatives(
            subject,
            text_body,
            from_email, 
            to
        )

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })
        
        email_message.attach_alternative(html_body, 'text/html')
        return email_message.send()
        
    def reset_verification_id(self, reset_account_verified=True):
        if reset_account_verified:
            self.account_verified = False

        self.verification_id = uuid.uuid4()
        self.save()

        return self.verification_id

    def send_verification_request_email(self):
    
        from cis.settings.registration_email import registration_email
        from django.conf import settings

        from_email = getattr(settings, 'DEFAULT_FROM')
        email_settings = registration_email.from_db()

        email_template = Template(email_settings['verification_email'])
        subject = email_settings.get('verify_email_subject')

        context = Context({
            'student_first_name': self.user.first_name,
            'student_last_name': self.user.last_name,
            'student_email': self.user.email,
            'verification_link': self.verify_email
        })
        text_body = email_template.render(context)
        to = [self.user.email]

        if getattr(settings, 'DEBUG', True):
            to = ['kadaji@gmail.com']
        
        email_message = EmailMultiAlternatives(
            subject,
            text_body,
            from_email, 
            to
        )

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })
        
        email_message.attach_alternative(html_body, 'text/html')
        return email_message.send()

    def signed_up_during_current_registration_period(self):
        return is_student_registration_open(self.user.created_at)

    def add_note(self, createdby=None, note='', meta=None):

        if not createdby:
            createdby = CustomUser.objects.get(
                username='cron'
            )

        note = StudentNote(
            createdby=createdby,
            note=note,
            student=self
        )

        if not meta:
            meta = {'type': 'private'}

        note.meta = meta
        note.save()

        return note
    
    @staticmethod
    def notify_counselor_student_notes(*args, **kwargs):
        from datetime import datetime, timedelta
        from cis.settings.student_notes_email import student_notes_email

        from cis.utils import (
            getDomain, upload_to_s3
        )

        from cis.models.student import Student
        from cis.models.note import StudentNote
        
        email_settings = student_notes_email.from_db()

        date_from = datetime.now() - timedelta(days=1)
        student_notes = StudentNote.objects.filter(
            meta__type__contains='to_counselor',
            createdon__gte=date_from
        ).order_by('-createdon')

        notes_summary = {}
        for note in student_notes:
            summary = notes_summary.get(str(note.student.highschool.id), [])
            summary.append(note)

            notes_summary[str(note.student.highschool.id)] = summary

        emails_sent = 0
        emails = []
        for highschoolid, note_summary in notes_summary.items():
            
            highschool = HighSchool.objects.get(pk=highschoolid)
            student = note_summary[0].student

            subject = email_settings.get('student_note_counselor_subject', 'change me')
            message = Template(email_settings.get('student_note_counselor_message', 'change'))

            notes_list = ''
            for note in note_summary:
                notes_list += note.student.user.first_name + ' ' + note.student.user.last_name + '<br>'
                notes_list += mark_safe(note.note) + "<br><hr><br>"

            context = Context({
                'student_notes': mark_safe(notes_list)
            })
            text_body = message.render(context)

            template = get_template('cis/email.html')
            html_body = template.render({
                'message': text_body
            })

            hs_administrators = highschool.administrators_in_highschool()
            to = [
                member.user.email for member in hs_administrators
            ]

            is_active = email_settings.get('is_active', 'No')
            if getattr(settings, 'DEBUG', True) or is_active == 'Debug':
                to = ['kadaji@gmail.com']
            elif is_active == 'No':
                continue

            send_html_mail(
                subject,
                text_body,
                html_body,
                settings.DEFAULT_FROM_EMAIL,
                to
            )
            emails_sent += 1

        prefix = getattr(
            settings,
            'CAMPUS_CODE_PREFIX'
        )
        upload_to_s3(
            json.dumps(emails),
            f'{prefix}/email/daily/student/notes/summary'
        )

        logger.info(f'Sent {emails_sent} emails to counselor student notes')
        logger.error(f'Sent {emails_sent} emails to counselor student notes')


    @staticmethod
    def notify_student_notes(*args, **kwargs):
        return
    
        from datetime import datetime, timedelta
        from cis.settings.student_notes_email import student_notes_email

        from cis.utils import (
            getDomain, upload_to_s3
        )

        from cis.models.student import Student
        from cis.models.note import StudentNote
        
        email_settings = student_notes_email.from_db()

        date_from = datetime.now() - timedelta(days=1)
        student_notes = StudentNote.objects.filter(
            meta__type__contains='to_student',
            createdon__gte=date_from
        ).order_by('-createdon')

        notes_summary = {}
        for note in student_notes:
            summary = notes_summary.get(str(note.student.id), [])
            summary.append(note)

            notes_summary[str(note.student.id)] = summary

        emails_sent = 0
        emails = []
        for studentid, note_summary in notes_summary.items():

            student = note_summary[0].student

            subject = email_settings.get('student_note_subject', 'change me')
            message = Template(email_settings.get('student_note_message', 'change'))

            notes_list = ''
            for note in note_summary:
                notes_list += mark_safe(note.note) + "<br><hr><br>"

            context = Context({
                'student_first_name': student.user.first_name,
                'student_last_name': student.user.last_name,
                'notes': mark_safe(notes_list)
            })
            text_body = message.render(context)

            template = get_template('cis/email.html')
            html_body = template.render({
                'message': text_body
            })

            to = [student.user.email]
            is_active = email_settings.get('is_active', 'No')
            if getattr(settings, 'DEBUG', True) or is_active == 'Debug':
                to = ['kadaji@gmail.com']
            elif is_active == 'No':
                continue

            send_html_mail(
                subject,
                text_body,
                html_body,
                settings.DEFAULT_FROM_EMAIL,
                to
            )
            
            emails.append(
                {
                    'to': to,
                    'message': text_body
                }
            )
            emails_sent += 1

    @staticmethod
    def notify_student_parent_notes(*args, **kwargs):
        return

        from datetime import datetime, timedelta
        from cis.settings.student_notes_email import student_notes_email

        from cis.utils import (
            getDomain, upload_to_s3
        )

        from cis.models.student import Student
        from cis.models.note import StudentNote
        
        email_settings = student_notes_email.from_db()

        date_from = datetime.now() - timedelta(days=1)
        student_notes = StudentNote.objects.filter(
            meta__type__contains='to_parent',
            createdon__gte=date_from
        ).order_by('-createdon')

        notes_summary = {}
        for note in student_notes:
            summary = notes_summary.get(str(note.student.id), [])
            summary.append(note)

            notes_summary[str(note.student.id)] = summary

        logger.error(notes_summary)
        emails_sent = 0
        emails = []
        for studentid, note_summary in notes_summary.items():

            student = note_summary[0].student

            subject = email_settings.get('student_note_parent_subject', 'change me')
            message = Template(email_settings.get('student_note_parent_message', 'change'))

            notes_list = ''
            for note in note_summary:
                notes_list += mark_safe(note.note) + "<br><hr><br>"

            context = Context({
                'student_first_name': student.user.first_name,
                'student_last_name': student.user.last_name,
                'notes': mark_safe(notes_list)
            })
            text_body = message.render(context)

            template = get_template('cis/email.html')
            html_body = template.render({
                'message': text_body
            })

            to = [student.parent_email]
            is_active = email_settings.get('is_active', 'No')
            if getattr(settings, 'DEBUG', True) or is_active == 'Debug':
                to = ['kadaji@gmail.com']
            elif is_active == 'No':
                continue

            send_html_mail(
                subject,
                text_body,
                html_body,
                settings.DEFAULT_FROM_EMAIL,
                to
            )
            
            emails.append(
                {
                    'to': to,
                    'message': text_body
                }
            )
            emails_sent += 1

        prefix = getattr(
            settings,
            'CAMPUS_CODE_PREFIX'
        )
        upload_to_s3(
            json.dumps(emails),
            f'{prefix}/email/daily/parent/notes/summary'
        )

        logger.info(f'Sent {emails_sent} emails to parent notes')
        logger.error(f'Sent {emails_sent} emails to parent notes')


    @classmethod
    def _for_import_get_or_add(cls, pidm, user, **kwargs):
        try:
            record = Student.objects.get(
                pidm=pidm
            )
        except Student.DoesNotExist:
            record = Student(user=user)
            record.pidm = pidm

        try:
            # Add extra fields if present
            for key, value in kwargs.items():
                setattr(record, key, value)
            record.save()
        except Exception as e:
            logger.error('Error while adding user' + str(e))
            print(str(e))
            return CustomUser.objects.none()

        return record

    def __str__(self):
        return f"{self.user.first_name} {self.user.last_name}"

    @property
    def ce_url(self):
        return reverse_lazy('cis:student', kwargs={
            'record_id': self.id})


    def as_pdf(self, request=None):
        import pdfkit
        from cis.forms.student import StudentStateQForm
        
        template = 'cis/students/single-page.html'
        template = get_template(template)
        html = template.render({
            'page_title': "Student",
            'labels': {
                'all_items': 'All Students'
            },
            'urls': {
                'add_new': 'cis:student_add_new',
                'all_items': 'cis:students'
            },
            'record': self,
            'registrations': StudentRegistration.objects.filter(
                student=self
            ),
            'ferpa': self.get_ferpa(),
            'state_q_form': StudentStateQForm(student=self),
            'recommendations': StudentRecommendation.objects.filter(
                student=self
            ),
            'agreements': StudentAgreement.objects.filter(
                student=self
            ),
            'notes': StudentNote.objects.filter(
                student=self
            ),
            'parent_consents': ParentConsent.objects.filter(
                student=self
            )
        })

        options = {
            'page-size': 'Letter'
        }
        
        template = get_template('cis/print_base.html')
        html = template.render({'main_content': html})

        pdf = pdfkit.from_string(html, False, options)

        return pdf

    def asTable(self):
        return self.asHTML('table')

    def editable_profile_asHTML(self):
        """Render the per-term Review Profile display from the
        student_profile setting's configurable Django template.

        Falls back to DEFAULT_REVIEW_TEMPLATE when the setting is absent
        or the profile_review_template field is blank.
        """
        from cis.settings.student_profile import (
            student_profile,
            DEFAULT_REVIEW_TEMPLATE,
        )

        template_str = (
            student_profile.from_db().get('profile_review_template')
            or DEFAULT_REVIEW_TEMPLATE
        )
        return Template(template_str).render(Context({'student': self}))

    def asHTML(self, html_type='div'):
        import json
        from cis.settings.student_profile import (
            student_profile, DEFAULT_PROFILE_DISPLAY,
        )

        raw = student_profile.from_db().get('profile_display')
        layout = DEFAULT_PROFILE_DISPLAY
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    layout = parsed
            except (ValueError, TypeError):
                layout = DEFAULT_PROFILE_DISPLAY

        return model_as_HTML(self, layout, html_type)

    @property
    def sexy_address(self):
        return f'{self.user.address1}<br>{self.user.city} {self.user.state} {self.user.postal_code}'
    
    @property
    def ums_campus_id(self):
        campus_id = StudentCampusID.objects.filter(
            campus__code__contains='UMS',
            student=self
        ).first()

        try:
            return campus_id.user_id
        except:
            return ''

    @property
    def campus_id(self):
        campus_ids = StudentCampusID.objects.filter(
            student=self
        ).order_by('campus__name')

        result = ''
        for campus_id in campus_ids:
            result += f'{campus_id.campus.name} - {campus_id.user_id}<br>'

        return result

    @property
    def primary_phone_numbers(self):
        import re
        return re.sub('[^0-9]+', '', self.user.primary_phone)

    @property
    def dob_mmddyyyy(self):
        return self.user.date_of_birth.strftime('%m%d%Y')

    @property
    def race_code(self):
        code = []

        if self.is_american_indian:
            code.append('I')

        if self.is_asian:
            code.append('A')

        if self.is_black:
            code.append('B')

        if self.is_hawaiin:
            code.append('P')

        if self.is_white:
            code.append('W')

        return ','.join(code)
    
    def _has_ethnicity(self, code, label):
        # MultiSelectField returns a list when read normally; raw queryset
        # access (.values_list) and some legacy rows can return a CSV string.
        # Handle both — the previous .split(',') call crashed on the list path.
        raw = self.ethnicity
        if not raw:
            return False
        if isinstance(raw, str):
            values = [v.strip() for v in raw.split(',')]
        else:
            values = [str(v).strip() for v in raw]
        return str(code) in values or label in values

    @property
    def is_asian(self):
        return self._has_ethnicity(2, 'Asian')

    @property
    def is_american_indian(self):
        return self._has_ethnicity(1, 'American Indian or Alaska Native')

    @property
    def is_black(self):
        return self._has_ethnicity(3, 'Black or African American')

    @property
    def is_hawaiin(self):
        return self._has_ethnicity(4, 'Native Hawaiian or Other Pacific Islander')

    @property
    def is_white(self):
        return self._has_ethnicity(5, 'White')
    
    @property
    def _gender(self):
        return self.get_gender_code()
    
    @property
    def intended_college_start(self):
        return self.meta.get('intended_college_start')
    
    @property
    def intended_college_major(self):
        return self.meta.get('intended_college_major')
    
    @property
    def relationship_type(self):
        return self.meta.get('relationship_type')
    
    @property
    def country_of_residence(self):
        return self.meta.get('country_of_residence')

    @property
    def is_homeschooled(self):
        
        setting_key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_cis_registrations"
        home_school_id = Setting.get_value(setting_key, 'homeschool')

        if not self.highschool:
            return False
        return bool(str(self.highschool.id) == home_school_id)

    @property
    def is_hispanic(self):       
        if not self.hispanic:
            return ''
        return 'Yes' if self.hispanic == 'True' else 'No'

    @property
    def _parent1_education_level(self):
        for (key, value) in self.PARENT_EDUCATION_OPTIONS:
            if key == self.parent1_education_level:
                return value
        return ''
    
    @property
    def _parent2_education_level(self):
        for (key, value) in self.PARENT_EDUCATION_OPTIONS:
            if key == self.parent2_education_level:
                return value
        return ''
    
    @property
    def gender_sexy(self):
        return self.gender.upper()
    
    def get_gender_code(self):
        if self.gender == 'm':
            return 'Male'
        if self.gender == 'f':
            return 'Female'
        return ''

    
    def get_ethnicity_code(self):
        if self.ethnicity == '':
            return "Not Specified"
        if self.ethnicity == '01':
            return 'American Indian/Alaska Native'
        if self.ethnicity == '02':
            return 'Asian'
        if self.ethnicity == '03':
            return 'Black/African American'
        if self.ethnicity == '04':
            return 'Hispanic/Latino'
        if self.ethnicity == '05':
            return 'Native Hawaiian/Oth Pac Island'
        if self.ethnicity == '06':
            return 'White'
        return 'Not Specified'

    def get_registrations(self, status=[]):
        """
        Return a queryset of 'StudentRegistration' objects for the student
        """
        return StudentRegistration.objects.filter(student__id=self.id)

    @staticmethod
    def get_student_signup_terms():
        reg_options = signup_settings.from_db()
        return reg_options.get('signup_terms')

    @staticmethod
    def get_registration_close_notice():
        r_options = reg_settings.from_db()
        return r_options.get('window_close_notice')

    @staticmethod
    def is_valid_age_range(date_of_birth):
        from datetime import datetime
        r_options = reg_settings.from_db()
        start_range = datetime.strptime(
            r_options.get('starting_birth_date', '10/10/2010'), '%m/%d/%Y').date()
        end_range = datetime.strptime(
            r_options.get('ending_birth_date', '10/10/2020'), '%m/%d/%Y').date()

        return True if start_range <= date_of_birth and end_range >= date_of_birth else False

    @staticmethod
    def import_from_csv(dictReader):
        """
        """
        required_headers = Student.REQUIRED_HEADERS
        has_headers = False
        result = []
        for row in dictReader:
            if not has_headers:
                missing_headers = []
                for header in required_headers:
                    if header not in row.keys():
                        missing_headers.append(header)
                if len(missing_headers) > 0:
                    return {
                        'status': 'error',
                        'message': 'Missing some required column headers, ' + ''.join(missing_headers)}
                has_headers = True

            # Check if high school code exists
            try:
                highschool = HighSchool.objects.get(
                    code=row['highschool_ceeb']
                )
            except HighSchool.DoesNotExist:
                row['RESULT'] = "HS Code not found"
                result.append(row)
                continue

            emplid = format_emplid(row['banner_id'])
            try:
                user = CustomUser.objects.get(
                    psid=emplid
                )
            except CustomUser.DoesNotExist:
                user = CustomUser()

            try:
                user = CustomUser.objects.get(
                    psid=row['banner_id']
                )
                user.psid = emplid
                user.save()
            except CustomUser.DoesNotExist:
                user = CustomUser()

            user.first_name = row['first_name']
            user.last_name = row['last_name']
            # user.middle_name = row['middle_name']

            user.psid = emplid
            user.email = row['college_email']
            username, junk = row['college_email'].split("@")
            user.username = username
            
            try:
                user.save()
            except Exception as e:
                row['RESULT'] = "Unable to save user record, " + str(e)
                result.append(row)
                continue

            group = Group.objects.get(name='student')
            user.groups.add(group)

            try:
                student = Student.objects.get(
                    user__psid=emplid
                )
            except Student.DoesNotExist:
                student = Student()

            student.user = user
            
            try:
                highschool = HighSchool.objects.get(
                    code=row['highschool_ceeb']
                )
            
                student.highschool = highschool
            except:
                ...
                
            student.save()
            row['RESULT'] = "Successfully saved student record"
            result.append(row)

        return {
            'status': 'success',
            'records': result
        }

    @staticmethod
    def delete_record(record):

        # Remove all classes
        registrations = record.get_registrations()
        registrations.delete()

        StudentCampusID.objects.filter(
            student=record
        ).delete()

        StudentRecommendation.objects.filter(
            student=record
        ).delete()

        StudentAgreement.objects.filter(
            student=record
        ).delete()

        StudentFerpa.objects.filter(
            student=record
        ).delete()

        ParentConsent.objects.filter(
            student=record
        ).delete()

        StudentNote.objects.filter(
            student=record
        ).delete()

        user = record.user
        record.delete()

        # try to remove base user account if this was the only role
        try:
            user.delete()
        except:
            pass

        return True


    def update_profile(self, profile_form):
        """
        DEPRECATED
        """
        user = CustomUser.objects.get(pk=self.user.id)
        user.first_name = profile_form.cleaned_data['first_name']
        user.last_name = profile_form.cleaned_data['last_name']
        user.middle_name = profile_form.cleaned_data['middle_name']

        user.email = profile_form.cleaned_data['email']
        user.secondary_email = profile_form.cleaned_data['secondary_email']
        user.username = profile_form.cleaned_data['email']

        user.primary_phone = profile_form.cleaned_data['cell_phone']
        user.date_of_birth = profile_form.cleaned_data['date_of_birth']

        user.address1 = profile_form.cleaned_data['mailing_address']
        user.city = profile_form.cleaned_data['city']
        user.state = profile_form.cleaned_data['state']
        user.postal_code = profile_form.cleaned_data['zip_code']

        user.save()

        self.user = user
        
        notifications = self.notifications
        if not notifications:
            notifications = {}

        notifications['cell_phone_opt_in'] = profile_form.cleaned_data['cell_phone_opt_in']

        self.notifications = notifications

        self.preferred_name = profile_form.cleaned_data['preferred_name']
        self.gender = profile_form.cleaned_data['gender']

        self.hispanic = profile_form.cleaned_data['hispanic']
        self.ethnicity = profile_form.cleaned_data['ethnicity']
        
        if profile_form.cleaned_data.get('highschool'):
            self.highschool = profile_form.cleaned_data['highschool']
        self.graduation_year = profile_form.cleaned_data['graduation_year']
        
        self.parent_first_name = profile_form.cleaned_data['parent_first_name']
        self.parent_last_name = profile_form.cleaned_data['parent_last_name']
        self.parent_email = profile_form.cleaned_data['parent_email']

        self.parent1_education_level = profile_form.cleaned_data['parent1_education_level']
        self.parent2_education_level = profile_form.cleaned_data['parent2_education_level']

        self.save()

    @staticmethod
    def create_new_student(application_form):
        """
        DEPRECATED

        Create and return a 'Student' object from the application application_form
        """
        user = CustomUser()
        user.first_name = application_form.cleaned_data['first_name']
        user.last_name = application_form.cleaned_data['last_name']
        user.middle_name = application_form.cleaned_data['middle_name']
        
        user.ssn = application_form.cleaned_data['ssn']

        user.email = application_form.cleaned_data['email'].lower()
        user.username = application_form.cleaned_data['email']
        user.secondary_email = application_form.cleaned_data['email']

        user.primary_phone = application_form.cleaned_data['cell_phone']
        user.date_of_birth = application_form.cleaned_data['date_of_birth']

        user.address1 = application_form.cleaned_data['mailing_address']
        user.city = application_form.cleaned_data['city']
        user.state = application_form.cleaned_data['state']
        user.postal_code = application_form.cleaned_data['zip_code']
        user.is_active = True

        user.set_password(application_form.cleaned_data['password'])
        user.save()

        # Add custom fields into Student record
        record = Student(user=user)
        record.preferred_name = application_form.cleaned_data['preferred_name']
        record.gender = application_form.cleaned_data['gender']
        record.hispanic = application_form.cleaned_data['hispanic']
        record.ethnicity = application_form.cleaned_data['ethnicity']
        record.highschool = application_form.cleaned_data['highschool']
        record.graduation_year = application_form.cleaned_data['graduation_year']

        notifications = record.notifications
        if not notifications:
            notifications = {}

        notifications['cell_phone_opt_in'] = application_form.cleaned_data['cell_phone_opt_in']

        record.notifications = notifications

        record.parent_first_name = application_form.cleaned_data['parent_first_name']
        record.parent_last_name = application_form.cleaned_data['parent_last_name']
        record.parent_email = application_form.cleaned_data['parent_email']

        record.parent1_education_level = application_form.cleaned_data['parent1_education_level']

        record.parent2_education_level = application_form.cleaned_data['parent2_education_level']

        record.save()
        return record

    @property
    def can_receive_sms(self):
        notifications = self.notifications
        if not notifications:
            notifications = {}

        return True if notifications.get('cell_phone_opt_in', 'False') == 'True' else False

    @property
    def cellphone(self):
        return self.user.primary_phone
    
    @property
    def parent1_interest_pretty(self):
        if not self.meta.get('parent1_interest'):
            return ''
        
        for k, v in self.PARENT_INTEREST_OPTIONS:
            if k == self.meta.get('parent1_interest'):
                return v

    @property
    def parent2_interest_pretty(self):
        if not self.meta.get('parent2_interest'):
            return ''
        
        for k, v in self.PARENT_INTEREST_OPTIONS:
            if k == self.meta.get('parent2_interest'):
                return v
    
    def has_applied_for_classes(self):
        regis_term_ids = registration_terms()
        return StudentRegistration.objects.filter(
            student=self,
            class_section__term__id__in=regis_term_ids).exists()

    def has_signed_student_agreement(self):
        return StudentAgreement.has_signed(self)

    def has_signed_parent_consent(self):
        return ParentConsent.has_signed(self)

    def has_recommendation(self, term_id=None):
        return StudentRecommendation.has_recommendation(self, term_id)

    def needs_recommendation(self, term_id=None):
        if self.has_recommendation(term_id):
            return False
        
        records = StudentRegistration.objects.filter(
                status__in=['applied'],
                student=self
        )

        skip_ids = []
        for record in records:
            if f'{record.student.grade_level}*' not in record.class_section.course.registration_eligibility:
                skip_ids.append(record.id)

        records = records.exclude(id__in=skip_ids)

        if len(records) > 0:
            return True
        return False

    def get_recommendation(self, term_id):
        return StudentRecommendation.objects.get(
            student=self,
            term__id=term_id)
    
    def get_ferpa(self):
        try:
            return StudentFerpa.objects.get(
                student=self)
        except StudentFerpa.DoesNotExist:
            return StudentFerpa.objects.none()

        
class StudentTuitionAssistance(models.Model):
    """
    Student FAA
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    student = models.ForeignKey(
        'cis.Student',
        on_delete=models.PROTECT
    )

    term = models.ForeignKey(
        'cis.Term',
        on_delete=models.PROTECT
    )

    information = JSONField(default=dict)

    STATUS_OPTIONS = (
        ('Not Yet Submitted', 'Not Yet Submitted'),
        ('Submitted', 'Submitted'),
        ('Pending Review', 'Pending Review'),
        ('Needs Information', 'Needs Information'),
        ('Processed', 'Processed')
    )
    status = models.CharField(
        max_length=50,
        choices=STATUS_OPTIONS,
        default=''
    )

    created_on = models.DateField(auto_now_add=True, blank=True, null=True)
    updated_on = models.DateField(auto_now=False, blank=True, null=True)

    class Meta:
        unique_together = ['student', 'term']


    def send_email(self):

        from cis.settings.registration_charges import registration_charges
        
        email_settings = registration_charges.from_db()

        email_template = Template(email_settings.get('ta_status_updated_email', 'change me'))
        subject = email_settings.get('ta_status_updated_email_subject', 'change me')

        context = Context({
            'student_first_name': self.student.user.first_name,
            'student_last_name': self.student.user.last_name,
            'student_email': self.student.user.email,
            'student_balance': self.student.student_balance,
            'ta_term': str(self.term),
            'public_note': self.information.get('public_note', ''),
            'status': self.status
        })
        text_body = email_template.render(context)
        to = [self.student.user.email]

        from cis.validators import validate_email
        try:
            validate_email(self.student.parent_email)
            to.append(self.student.parent_email)
        except:
            ...

        try:
            validate_email(self.student.parent2_email)
            to.append(self.student.parent2_email)
        except:
            ...

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })
        
        if getattr(settings, 'DEBUG', True):
            to = ['kadaji@gmail.com']
        
        send_html_mail(
            subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            to
        )

    @property
    def files(self):
        return StudentTuitionAssistanceDocument.objects.filter(
            tuition_assistance=self
        )
    
    @property
    def public_note(self):
        self.information.get('public_note')
    
    @property
    def ce_url(self):
        return reverse_lazy('cis:faa', kwargs={
            'record_id': self.id})

    @property
    def can_edit(self):
        return True if self.status in ['Not Yet Submitted', 'Submitted', 'Needs Information'] else False
    
    @property
    def other_info(self):
        return self.information.get('other_info')

    @property
    def updates(self):
        if not self.information.get('updates'):
            return ''

        self.information.get('updates').reverse()
        return '<br>'.join(self.information.get('updates'))

    @property
    def files_sexy(self):
        file_label = '<br><h5>Uploaded Files</h5><table class="table table-striped">'
        for file in self.files:
            file_label += "<tr><td>"
            file_label += f"<a href='{file.media.url}'>{file.filename}</a><br>"
            file_label += "</td>"
            file_label += "<td>"
            file_label += f"{file.description}"
            file_label += "</td>"
            file_label += "</tr>"
        
        file_label += "</table>"
        return file_label
    
    def asHTML(self):
        format = [
            [
                'student',
                'term'
            ],
            [
                {
                    'label': 'Submitted On',
                    'field': 'created_on'
                },
                {
                    'label': 'Status',
                    'field': 'status'
                }
            ],
            [
                {
                    'field': 'other_info',
                    'label': 'Personal Statement'
                },
                {
                    'field': 'files_sexy',
                    'label': 'File(s)'
                }
            ],
            [
                {
                    'label': 'Update History',
                    'field': 'updates'
                }
            ]
        ]
        return model_as_HTML(self, format)

class StudentTuitionAssistanceDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    description = models.TextField(blank=True)
    media = models.FileField(
        storage=PrivateMediaStorage(),
        upload_to=student_tuition_assistance_upload_path
    )

    tuition_assistance = models.ForeignKey('cis.StudentTuitionAssistance', on_delete=models.CASCADE)
    uploaded_on = models.DateTimeField(auto_now=True)

    @property
    def filename(self):
        import os
        return os.path.basename(self.media.name)


class StudentCampusID(models.Model):
    """
    Student Campus ID
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    student = models.ForeignKey(
        'cis.Student',
        on_delete=models.PROTECT
    )
    campus = models.ForeignKey(
        'cis.Campus',
        on_delete=models.PROTECT
    )

    username = models.CharField(max_length=100, blank=True)
    email = models.EmailField(max_length=100, blank=True)
    user_id = models.CharField(max_length=100)

    class Meta:
        unique_together = ['student', 'campus', 'user_id']    

    @staticmethod
    def import_from_csv(dictReader):
        from cis.models.course import Campus
        from cis.models.student import Student
        """
        """
        required_headers = [] 
        has_headers = False
        result = []

        campus = Campus.get_all()

        print('importing')
        for row in dictReader:
            # if not has_headers:
            #     missing_headers = []
            #     for header in required_headers:
            #         if header not in row.keys():
            #             missing_headers.append(header)
            #     if len(missing_headers) > 0:
            #         return {
            #             'status': 'error',
            #             'message': 'Missing some required column headers, ' + ','.join(missing_headers)}
            #     has_headers = True

            # Check if student exists
            if not row['canusia_id']:
                row['RESULT'] = 'Blank canusia id'
                result.append(row)
                continue

            try:
                student = Student.objects.get(
                    id=row['canusia_id']
                )
            except Student.DoesNotExist:
                row['RESULT'] = 'Unable to find student'
                result.append(row)
                continue
            except Exception as e:
                row['RESULT'] = str(e)
                result.append(row)
                continue

            student.user.psid = row['bannerid']
            student.user.save()
            row['RESULT'] = 'Found student ' + student.user.first_name + ' ' + student.user.last_name
            result.append(row)            
        return {
            'status': 'success',
            'records': result
        }

class ParentConsent(models.Model):
    """
    Parent Consent
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    student = models.ForeignKey(
        'cis.Student',
        on_delete=models.PROTECT
    )
    term = models.ForeignKey(
        'cis.Term',
        on_delete=models.PROTECT
    )

    parent_signature = models.TextField()
    parent_signed_on = models.DateField(auto_now=False, blank=True, null=True)

    parent_name = models.CharField(max_length=100, blank=True)
    parent_phone = models.CharField(max_length=15, blank=True)
    parent_email = models.CharField(max_length=100, blank=True)

    class Meta:
        unique_together = ['student', 'term']
        
    @classmethod
    def default_term(cls):
        from cis.settings.registrations import registrations as regis_settings
        # print(regis_settings.from_db().get('active_term'))
        return regis_settings.from_db().get('active_term')
    
    @classmethod
    def get_form_message(cls, setting_name='request_consent_intro'):
        setting_key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_parent_consent"
        return Setting.get_value(setting_key, setting_name)

    @classmethod
    def has_signed(cls, student, term_id=None):
        if not term_id:
            terms = registration_terms()

            registered_term_ids = StudentRegistration.objects.filter(
                student=student,
                class_section__term__in=terms
            ).values_list('class_section__term__id', flat=True)

            if not registered_term_ids:
                registered_term_ids = terms.values_list('id', flat=True)

            for term in terms:
                if term.id in registered_term_ids:
                    if not ParentConsent.objects.filter(
                            term__id=term.id,
                            student=student).exists():
                        return False
            return True
        return ParentConsent.objects.filter(
            term__id=term_id,
            student=student).exists()

    @classmethod
    def get_url(cls, student_id, term_id):
        return getDomain() + str(reverse_lazy('student:parent', kwargs={
            'student_id': student_id,
            'term_id': term_id}))

    @classmethod
    def send_notification(cls, student, term_id, parent_name, parent_email):
        email_settings = registration_email.from_db()
        email_template = Template(email_settings['parent_consent_req'])

        url = ParentConsent.get_url(student.id, term_id)

        context = Context({
            'parent_consent_url': url,
            'parent_name': parent_name,
            'student_first_name': student.user.first_name,
            'student_last_name': student.user.last_name
        })
        text_body = email_template.render(context)
        to = [parent_email]

        if getattr(settings, 'DEBUG', True):
            to = ['kadaji@gmail.com']

        subject = email_settings.get('parent_consent_req_subject')

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

    @property
    def _parent_signature(self):
        return self.parent_signature
    
        if self.parent_signature.startswith('Marked'):
            return self.parent_signature
        return f"<img class='responsive border' src='{self.parent_signature}' />"

    @property
    def _parent_signed_on(self):
        return self.parent_signed_on.strftime('%m/%d/%Y')
    
    def asTable(self):
        return self.asHTML('table')

    def asHTML(self, html_type='div'):
        format = [
            [
                'student',
                'term'
            ],
            [
                {
                    'label': 'Signed On',
                    'field': '_parent_signed_on'
                },
                {
                    'label': 'Signature',
                    'field': '_parent_signature'
                }
            ]
        ]
        return model_as_HTML(self, format, html_type)
    
class StudentFerpa(models.Model):
    """
    Student FERPA
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    student = models.ForeignKey(
        'cis.Student',
        on_delete=models.PROTECT
    )

    campus = JSONField()
    permissions_granted = JSONField()

    student_signature = models.TextField()
    student_signed_on = models.DateField(auto_now=False, blank=True, null=True)

    RELEASES = [
        # ('dec', 'I decline to release any information'),
        # ('al', 'All Record Types Listed Below (AL) OR check mark below for individual department records.'),
        # ('rg', 'Academic Records (RG) May include: grade information, admission and registration information, academic advising information, schedule documentation contained in the academic records'),
        # ('ar', 'Student Account Records (AR) May include: amount for tuition and fees, sources of payment for tuition and fees, refund information, records hold information as it relates to parking tickets, library fines, financial aid repayments and any other accounts receivable information contained in student account records.'),
        # ('ic', 'Instructor/Classroom Records (IC) May include: attendance, progress reports, test and homework scores if available. Please Note: instructors are not required to take attendance or provide progress reports, and retain only those records which make up the final grade. Instructors are not required to have conversations about progress with anyone other than the student.'),
        # ('fa', 'Financial Aid Records (FA) - excludes income information. May include: status of file, aid offers and disbursement of funds information, Satisfactory Academic Progress status, and any other information contained in the application or financial aid file.'),
        # ('hd', 'Housing/Dorms (HD) May include: housing contract information, housing placement, and additional housing charges (fees, fines, etc.)'),
        # ('ot', 'Other (OT)'),
    ]
    
    class Meta:
        unique_together = ['student']
        
    @property
    def releases(self):
        return self.permissions_granted.get('releases', [])
    
    @property
    def other_releases(self):
        return self.permissions_granted.get('other_releases', '')
    
    @property
    def decline_release(self):
        return True if self.permissions_granted.get('release_status', False) == 'decline' else False

    @property
    def permissions_granted_to(self):
        return self.permissions_granted.get('permissions', [])
    
    @classmethod
    def get_form_message(cls, setting_name='ferpa_intro'):
        setting_key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_ferpa"
        return Setting.get_value(setting_key, setting_name)

    @classmethod
    def has_signed(cls, student):
        return StudentFerpa.objects.filter(
            student=student).exists()

    def asHTML(self):
        from cis.services.tenant_services import get_tenant_service
        return get_tenant_service('ferpa_form').as_html(self)


class StudentRecommendation(models.Model):
    """
    Student Recommendation
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    student = models.ForeignKey(
        'cis.Student',
        on_delete=models.PROTECT
    )
    term = models.ForeignKey(
        'cis.Term',
        on_delete=models.PROTECT
    )
    submitted_on = models.DateTimeField(auto_now=True)
    submitted_by = models.ForeignKey(
        'cis.CustomUser',
        on_delete=models.PROTECT,
        blank=True,
        null=True
    )
    recommendation = JSONField()
    upload = models.FileField(
        storage=PrivateMediaStorage(),
        upload_to=student_recommendation_upload_path,
        blank=True)

    class Meta:
        unique_together = ['student', 'term']

    @classmethod
    def has_recommendation(cls, student, term_id=None):
        if not term_id:
            registered_term_ids = StudentRegistration.objects.filter(
                student=student
            ).values_list('class_section__term__id', flat=True)

            terms = registration_terms()
            for term in terms:
                if term.id in registered_term_ids:
                    if not StudentRecommendation.objects.filter(
                            term__id=term.id,
                            student=student).exists():
                        return False
            return True
        return StudentRecommendation.objects.filter(
            term__id=term_id,
            student=student).exists()

    @property
    def waiver_approved(self):
        return self.recommendation.get('waiver_approved', 'N/A')
    
    @classmethod
    def get_url(cls, student_id, term_id):
        return getDomain() + str(reverse_lazy('student:parent', kwargs={
            'student_id': student_id,
            'term_id': term_id}))

    @classmethod
    def default_term(cls):
        setting_key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_cis_registrations"
        return Setting.get_value(setting_key, 'signature_term')

    @property
    def gpa(self):
        result = self.recommendation.get('student_gpa', 'N/A')
        # if result == 'Yes':
        #     result += "<br> (" + self.recommendation.get('grade_earned', '')
        return result

    # @property
    # def grade_level(self):
    #     for (key, value) in STUDENT_GRADE_OPTIONS:
    #         if str(key) == self.recommendation['student_grade_level']:
    #             return value
    #     return ''

    @property
    def qualification(self):
        return self.recommendation.get('student_qualification', '')

    @property
    def grade_earned(self):
        return self.recommendation.get('grade_earned', '')

    @property
    def school_assessment(self):
        return self.recommendation.get('school_assessment', '')

    @property
    def keystone_exam(self):
        return self.recommendation.get('keystone_exam', '')

    @property
    def geip(self):
        return self.recommendation.get('geip', '')

    @property
    def enrolled_in_honors(self):
        return self.recommendation.get('enrolled_in_honors', '')

    @property
    def meets_prereq(self):
        return self.recommendation.get('student_prereq', '')
    
    @property
    def student_prereq(self):
        return self.recommendation.get('student_prereq', '')

    @property
    def bridge_academy(self):
        if self.recommendation.get('student_bridge', '2') == '2':
            return 'No'
        return 'Yes'

    @property
    def file_download_url(self):
        if self.upload:
            return f'<a href=\'{self.upload.url}\' class="btn btn-primary" target="_blank">Download</a>'

    @classmethod
    def get_form_message(cls, setting_name='upload_label'):
        setting_key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_counselor_language"
        return Setting.get_value(setting_key, setting_name)

    def asTable(self):
        return self.asHTML('table')

    @property
    def eval_method_pretty(self):
        """
        Returns the evaluation method in a pretty format
        """
        if not self.recommendation.get('eval_method', None):
            return ''

        method_map = {
            'sophomore-other_states': 'Sophomore - All Other States',
            'sophomore-pa_religious_private': 'Sophomore - PA, Religious or Private Schools',
            'sophomore-pa_public': 'Sophomore - PA, Public Schools',
        }

        return method_map.get(self.recommendation['eval_method'], self.recommendation['eval_method'])

    def asHTML(self, html_type='div'):
        from cis.services.tenant_services import get_tenant_service
        return get_tenant_service('recommendation_form').as_html(self, html_type)

class StudentAgreement(models.Model):
    """
    Student Agreement
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    student = models.ForeignKey(
        'cis.Student',
        on_delete=models.PROTECT
    )
    term = models.ForeignKey(
        'cis.Term',
        on_delete=models.PROTECT
    )

    student_signature = models.TextField()
    student_signed_on = models.DateField(auto_now=False, blank=True, null=True)

    class Meta:
        unique_together = ['student', 'term']

    @classmethod
    def default_term(cls):
        setting_key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_cis_registrations"
        return Setting.get_value(setting_key, 'signature_term')

    @classmethod
    def get_form_message(cls, setting_name='student_terms'):
        setting_key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_signup"
        return Setting.get_value(setting_key, setting_name)

    @classmethod
    def has_signed(cls, student, term_id=None):
        """
        Checks if agreement has been signed for term_id. If no term_id is 
        passed then it checks for ALL terms that are currently open for registration.

        If agreement is missing for any then return False, True otherwise.
        """
        if not term_id:
            terms = registration_terms()
            registered_term_ids = StudentRegistration.objects.filter(
                student=student,
                class_section__term__in=terms
            ).values_list('class_section__term__id', flat=True)

            if not registered_term_ids:
                registered_term_ids = terms.values_list('id', flat=True)

            for term in terms:
                if not StudentAgreement.objects.filter(
                        term__id=term.id,
                        student=student).exists():
                    return False
            return True

        return StudentAgreement.objects.filter(
            term__id=term_id,
            student=student).exists()

    @property
    def _student_signed_on(self):
        return self.student_signed_on.strftime('%m/%d/%Y')

    @property
    def _student_signature(self):
        return self.student_signature
        return f"<img class='responsive border' src='{self.student_signature}' />"

    def asTable(self):
        return self.asHTML('table')

    def asHTML(self, html_type='div'):

        format = [
            [
                'student',
                'term'
            ],
            [
                {
                    'label': 'Signed On',
                    'field': '_student_signed_on'
                },
                {
                    'label': 'Signature',
                    'field': '_student_signature'
                }
            ]
        ]
        return model_as_HTML(self, format, html_type)

class StudentSupportingDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    description = models.TextField(blank=True)
    # Free-text values validated against the CE-configurable lists in
    # the cis.settings.support_docs setting (stored, not FK'd,
    # so re-labeling a type/status in settings doesn't orphan existing docs).
    document_type = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=255, blank=True, default='')
    media = models.FileField(
        storage=PrivateMediaStorage(),
        upload_to=student_supporting_doc_upload_path
    )

    term = models.ForeignKey('cis.Term', on_delete=models.PROTECT)
    student = models.ForeignKey('cis.Student', on_delete=models.PROTECT)
    uploaded_on = models.DateTimeField(auto_now=True)


    @property
    def filename(self):
        import os
        return os.path.basename(self.media.name)
