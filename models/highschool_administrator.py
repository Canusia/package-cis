# users/models.py
import uuid

from django.conf import settings
from django.urls import reverse_lazy
from django.db import models, IntegrityError, transaction
from django.db.models import Q
from django.contrib.auth.models import Group

from mailer import send_mail, send_html_mail

from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.template import Context, Template
from django.template.loader import get_template, render_to_string
from django.db.models import JSONField

from cis.utils import export_to_excel
from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool

class HSAdministratorAccessRequest(models.Model):
    """
    Model to store access requests
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=100)
    email = models.EmailField(max_length=100)
    phone = models.CharField(max_length=20)

    highschool = models.ForeignKey('cis.HighSchool', on_delete=models.PROTECT)

    role = models.CharField(max_length=100)

    approver_name = models.CharField(max_length=100, blank=True, null=True)
    approver_email = models.EmailField(max_length=100, blank=True, null=True)
    approver_phone = models.CharField(max_length=20, blank=True, null=True)

    message = models.TextField(blank=True, null=True)

    submittedon = models.DateTimeField(auto_now_add=True)

    STATUS_OPTIONS = (
        ('Submitted', 'Submitted'),
        ('Approved', 'Approved'),
        ('Denied', 'Denied'),
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_OPTIONS,
        default='Submitted')

    @property
    def ce_url(self):
        return reverse_lazy('cis:hs_admin_access_request', kwargs={
            'record_id': self.id})

    def notify_on_submit(self):
        from cis.settings.access_request import access_request as access_request_settings

        config = access_request_settings.from_db()
        email = subject = ''

        subject = config.get('submitted_subject')
        email = config.get('submitted_email')

        email_template = Template(email)
        context = Context({
            'name': self.name,
            'highschool': self.highschool.name,
            'highschool_country': self.highschool.country
        })

        text_body = email_template.render(context)
        to = config.get('submitted_internal_notification', 'kadaji@gmail.com').split(',')

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
        return True
        
    def email_context(self, reset_link=None):
        """Values for the approval/denial email placeholders
        (catalogue: cis.services.access_request_review.PLACEHOLDERS)."""
        return {
            'name': self.name,
            'email': self.email,
            'highschool': self.highschool.name,
            'role': self.role,
            'password_reset_link': (
                reset_link if reset_link is not None else self.get_password_reset_link()),
        }

    def send_email(self, subject=None, body=None):
        """Email the requester the outcome. `subject` / `body` override the
        Settings templates (the CE review form's per-request edit)."""
        from cis.settings.access_request import access_request as access_request_settings

        config = access_request_settings.from_db()

        if self.status == 'Approved':
            default_email = config.get('approved_email', '2')
            default_subject = config.get('approved_subject', '2')
        elif self.status == 'Denied':
            default_email = config.get('denied_email', '22')
            default_subject = config.get('denied_subject', '22')
        else:
            return None

        context = Context(self.email_context())
        subject = Template(subject if subject is not None else default_subject).render(context)
        text_body = Template(body if body is not None else default_email).render(context)
        to = [self.email]

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
        return True

    def get_password_reset_link(self):
        try:
            if self.status == 'Approved':
                hs_admin = HSAdministrator.objects.get(
                    user__email__iexact=self.email.lower()
                )

                return hs_admin.user.get_password_reset_link()
        except:
            return '-'

    def grant_access(self, form_data):
        first_name = self.name.split(" ")[0]
        try:
            last_name = self.name.split(" ")[1]
        except:
            last_name = ' '

        hs_administrator = HSAdministrator.create_new(
            first_name,
            last_name,
            self.email.lower(),
            self.phone
        )

        if HSPosition.objects.filter(
            name__iexact=self.role).exists():
            position = HSPosition.objects.get(name__iexact=self.role)
        else:
            position = HSPosition()
            position.name = self.role

            position.save()

        hs_admin_position = HSAdministratorPosition()
        hs_admin_position.highschool = self.highschool
        hs_admin_position.position = position
        hs_admin_position.hsadmin = hs_administrator
        hs_admin_position.status = 'Active'

        try:
            # Savepoint: the duplicate-role IntegrityError must not poison the
            # surrounding transaction (TestCase, or ATOMIC_REQUESTS).
            with transaction.atomic():
                hs_admin_position.save()
        except IntegrityError:
            return False
        hs_admin_position.set_perms(
            [p.codename for p in form_data.get('permissions') or []],
            campus=form_data.get('scope'))
        return True

class HSAdministrator(models.Model):
    """
    Base user model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField('cis.CustomUser', on_delete=models.PROTECT)
    #Look through access db to see other fields

    def __str__(self):
        return f"{self.user.last_name} {self.user.first_name}"


    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        #if self._state.adding is True
        # group = Group.objects.get(name='highschool_admin')
        # self.user.groups.add(group)


    @staticmethod
    def delete_record(record):
        """Delete the administrator record. The CustomUser is never deleted.

        CustomUser is protected by many foreign keys, so deleting it here would
        raise ProtectedError for most real accounts. Revoking the
        highschool_admin group is a separate, explicit step —
        cis.services.hs_admin_role.revoke_hs_admin_access.
        """
        record.delete()
        return True

    @property
    def ce_url(self):
        return reverse_lazy('cis:hs_admin', kwargs={
            'record_id': self.id})

    def can_manage_student_student_recommendation(self, highschool_id, campus=None):
        # Deprecated duplicate of can_manage_student_recommendation.
        return self.can_manage_student_recommendation(highschool_id, campus=campus)

    def has_school_perm(self, codename, highschool_id, campus=None):
        """True if an Active position of this admin at `highschool_id` holds
        `codename` (an HSAdminPerm constant).

        A student with no high school yields highschool_id=None; refuse it
        explicitly so a future filter change cannot turn a missing high
        school into a match."""
        if not highschool_id:
            return False
        return HSAdministratorPosition.objects.filter(
            hsadmin=self, highschool__id=highschool_id,
        ).with_perm(codename, campus).exists()

    def highschools_with_perm(self, codename, campus=None):
        """HighSchool queryset where has_school_perm(codename, ...) is True.

        Exact 'Active', matching get_highschools(): an admin listed here but
        excluded there is shown pending work whose page then 404s."""
        highschool_ids = HSAdministratorPosition.objects.filter(
            hsadmin__id=self.id).with_perm(codename, campus).values_list('highschool', flat=True)
        return HighSchool.objects.filter(id__in=highschool_ids)

    def get_highschools(self, status='Active'):
        """
        Return a HighSchool queryset for highschool_admin. If status is 
        not passed then only HighSchool objects with 'Active' roles 
        is returned
        """
        try:
            highschool_ids = HSAdministratorPosition.objects.filter(
                status=status,
                hsadmin__id=self.id).values_list('highschool', flat=True)

            return HighSchool.objects.filter(id__in=highschool_ids)
        except HSAdministratorPosition.DoesNotExist:
            return []

    def can_manage_student_recommendation(self, highschool_id, campus=None):
        return self.has_school_perm(
            HSAdminPerm.MANAGE_STUDENT_RECOMMENDATION, highschool_id, campus)

    def can_verify_roster(self, highschool_id, campus=None):
        """True if this admin's Active role at the school has Verify Class
        Rosters. Whether high school admins may verify at all is the Roster
        Verification setting's call (roster_verification.can_verify); check
        both (#69)."""
        return self.has_school_perm(HSAdminPerm.VERIFY_ROSTER, highschool_id, campus)

    def get_roster_highschools(self, campus=None):
        """Queryset counterpart to can_verify_roster(), for filtering lists."""
        return self.highschools_with_perm(HSAdminPerm.VERIFY_ROSTER, campus)

    def get_recommendation_highschools(self, campus=None):
        """High schools where this admin may manage student recommendations.

        Queryset counterpart to can_manage_student_recommendation(), for
        filtering lists. The two must agree, so both key off the same active
        position plus the can_manage_student_recommendation permission. Callers that
        show pending-recommendation work should use this rather than
        get_highschools(), which is every school the admin holds any position
        at.

        The status predicate is exact 'Active' for the same reason — it must
        also agree with get_highschools(), or this returns a school that one
        excludes and the admin is shown work they cannot open.
        """
        return self.highschools_with_perm(HSAdminPerm.MANAGE_STUDENT_RECOMMENDATION, campus)

    @classmethod
    def create_new(cls, first_name, last_name, email, primary_phone='', **kwargs):
        #create a CustomUser object
        user = CustomUser()
        user.first_name = first_name
        user.last_name = last_name
        user.email = email
        user.username = email.lower()
        user.primary_phone = primary_phone
        
         #check if user email is already in the system
        if not CustomUser.objects.filter(email=email).exists():
            user.save()
        else:
            user = CustomUser.objects.get(email=email)
            
        record = HSAdministrator(user=user)
        try:
            # Savepoint, so an existing admin does not poison an enclosing
            # transaction before the lookup below.
            with transaction.atomic():
                record.save()
        except IntegrityError:
            record = HSAdministrator.objects.get(
                user=user
            )
        return record

    @staticmethod
    def export_to_excel(records):
        """
        Write records to an Excel file
        """
        file_name = "highschool_administrators.csv"
        fields = {
            "user.first_name": "First Name",
            "user.last_name": "Last Name",
            "user.address1": "Address1",
            "user.address2": "Address2",
            "user.city": 'City',
            'user.state': 'State',
            'user.postal_code': 'ZipCode',
            'user.primary_phone': 'PrimaryPhone',
            'user.email': "Email",
            'status': 'Status',
            'temp_id': 'TempID'
        }

        return export_to_excel(file_name, records, fields)

    @staticmethod
    def import_from_csv(dictReader):
        """Import HS Members from CSV using the HSMemberImporter service."""
        from cis.services.importers import HSMemberImporter

        importer = HSMemberImporter()
        return importer.process_csv(dictReader)

    @classmethod
    def get_or_add(cls, email, **kwargs):
        try:
            record = HSAdministrator.objects.get(
                user__email__iexact=email
            )
        except HSAdministrator.DoesNotExist:
            user = CustomUser.get_or_add(
                username=email,
                email=email,
                **kwargs
            )

            try:
                record = HSAdministrator(user=user)
                record.save()

                #highschool_admin role is added in the save method
            except:
                return None
        return record

class HSPosition(models.Model):
    """
    HS Positions models
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, unique=True)

    YES_NO_OPTIONS = (
        ('no', 'No'),
        ('yes', 'Yes')
    )

    temp_id = models.IntegerField(blank=True, null=True)

    can_manage_class_offering = models.CharField(
        choices=YES_NO_OPTIONS,
        max_length=3,
        default='no'
    )

    def __str__(self):
        return self.name

    class Meta:
        unique_together = ['name']

    @classmethod
    def get_or_add(cls, name, **kwargs):
        try:
            record = HSPosition.objects.get(
                name__iexact=name
            )
        except HSPosition.DoesNotExist:
            record = HSPosition(
                name=name
            )
            record.save()
        return record

# DEPRECATED (v0.1.15a): permissions moved to HSAdministratorPosition.permissions
# (HSAdminPerm). Kept importable for one release; nothing reads these keys.
POSITION_FLAGS = ('manage_student_recommendation', 'manage_roster_verification')


def normalize_position_flag(value):
    """'Yes' for any casing of yes, otherwise 'No' (unset included)."""
    return 'Yes' if str(value or '').strip().lower() == 'yes' else 'No'


class HSAdminPerm:
    """Codenames of the per-school HS admin permissions. Other packages import
    these constants rather than hard-coding the strings."""
    MANAGE_STUDENT_RECOMMENDATION = 'can_manage_student_recommendation'
    VERIFY_ROSTER = 'can_verify_roster'
    BULK_UPLOAD_STUDENTS = 'can_bulk_upload_students'
    BULK_ENROLL = 'can_bulk_enroll'
    BULK_UPLOAD_SUPPORTING_DOCS = 'can_bulk_upload_supporting_docs'
    MANAGE_SCHOOL_PERSONNEL = 'can_manage_school_personnel'
    MANAGE_FUTURE_SECTIONS = 'can_manage_future_sections'
    SUBMIT_DROP_REQUESTS = 'can_submit_drop_requests'
    SUBMIT_GRADES = 'can_submit_grades'

    LABELS = {
        MANAGE_STUDENT_RECOMMENDATION: 'Can manage student recommendations',
        VERIFY_ROSTER: 'Can verify class rosters',
        BULK_UPLOAD_STUDENTS: 'Can bulk upload students',
        BULK_ENROLL: 'Can bulk enroll',
        BULK_UPLOAD_SUPPORTING_DOCS: 'Can upload supporting documents',
        MANAGE_SCHOOL_PERSONNEL: 'Can manage school personnel',
        MANAGE_FUTURE_SECTIONS: 'Can manage future sections',
        SUBMIT_DROP_REQUESTS: 'Can submit drop requests',
        SUBMIT_GRADES: 'Can submit grades',
    }
    ALL = tuple(LABELS)


# A codename alone is not unique in auth_permission; every lookup pins the
# content type too.
_PERMISSION_CT = {
    'content_type__app_label': 'cis',
    'content_type__model': 'hsadministratorposition',
}


def hsadmin_permission_objects(codenames):
    """Permission rows for `codenames`, in HSAdminPerm.ALL order. Raises
    ValueError for anything that is not an HS admin permission."""
    from django.contrib.auth.models import Permission
    from django.db.models import Case, IntegerField, When

    codenames = list(codenames)
    unknown = set(codenames) - set(HSAdminPerm.ALL)
    if unknown:
        raise ValueError(f'Unknown HS admin permission(s): {sorted(unknown)}')

    order = Case(*[When(codename=c, then=i) for i, c in enumerate(HSAdminPerm.ALL)],
                 output_field=IntegerField())
    return Permission.objects.filter(
        codename__in=codenames, **_PERMISSION_CT).order_by(order)


#: Pass as `campus` to match a grant for any campus (lists not tied to one
#: campus, e.g. the HS admin pending-recommendation list).
ANY_CAMPUS = object()


def _campus_q(campus, prefix=''):
    """Grants that count for `campus`: all-campuses (null) grants, plus that
    campus's own when one is given. ANY_CAMPUS matches every grant."""
    if campus is ANY_CAMPUS:
        return Q()
    q = Q(**{f'{prefix}campus__isnull': True})
    if campus is not None:
        q |= Q(**{f'{prefix}campus': campus})
    return q


def _grant_ct():
    return {f'permission__{k}': v for k, v in _PERMISSION_CT.items()}


class HSAdministratorPositionQuerySet(models.QuerySet):
    def with_perm(self, codename, campus=None):
        """Active positions holding `codename` for `campus` (see _campus_q)."""
        g = 'permission_grants__'
        return self.filter(
            Q(status='Active', **{f'{g}permission__codename': codename},
              **{f'{g}{k}': v for k, v in _grant_ct().items()})
            & _campus_q(campus, g)
        ).distinct()


class HSAdministratorPosition(models.Model):
    """
    Model to associate hs admin with their position in high schools
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    hsadmin = models.ForeignKey('cis.HSAdministrator', on_delete=models.PROTECT)
    highschool = models.ForeignKey('cis.HighSchool', on_delete=models.PROTECT)
    position = models.ForeignKey('cis.HSPosition', on_delete=models.PROTECT)

    created_at = models.DateTimeField(auto_now_add=True)
    last_updated_at = models.DateTimeField(auto_now=True)

    since = models.DateTimeField(blank=True, null=True)
    meta = JSONField(default=dict)

    STATUS_OPTIONS = [
        ('Active', 'Active'),
        ('Inactive', 'Inactive'),
        # ('Retired', 'Retired'),
    ]
    status = models.CharField(max_length=10, choices=STATUS_OPTIONS)

    # Per-school HS admin permissions, each optionally for one campus
    # (HSPositionPermission); they count only while status is Active.
    permissions = models.ManyToManyField(
        'auth.Permission', blank=True, related_name='hsadmin_positions',
        through='cis.HSPositionPermission',
        limit_choices_to={**_PERMISSION_CT, 'codename__in': HSAdminPerm.ALL})

    objects = HSAdministratorPositionQuerySet.as_manager()

    class Meta:
        unique_together = (('hsadmin', 'highschool', 'position'))
        permissions = [(c, HSAdminPerm.LABELS[c]) for c in HSAdminPerm.ALL]

    def _grant_rows(self):
        cache = getattr(self, '_prefetched_objects_cache', {})
        if 'permission_grants' in cache:
            rows = cache['permission_grants']
        else:
            rows = self.permission_grants.filter(**_grant_ct()).select_related(
                'permission__content_type', 'campus')
        return [r for r in rows
                if r.permission.codename in HSAdminPerm.ALL
                and r.permission.content_type.app_label == 'cis'
                and r.permission.content_type.model == 'hsadministratorposition']

    def grants(self):
        """[(codename, campus or None)], in HSAdminPerm.ALL order then campus name."""
        order = {c: i for i, c in enumerate(HSAdminPerm.ALL)}
        return sorted(((r.permission.codename, r.campus) for r in self._grant_rows()),
                      key=lambda g: (order[g[0]], g[1].name if g[1] else ''))

    def codenames(self, campus=None):
        """Codenames that count for `campus` (see _campus_q), whatever the status."""
        return {code for code, c in self.grants()
                if campus is ANY_CAMPUS or c is None
                or (campus is not None and c.pk == campus.pk)}

    def has_perm(self, codename, campus=None):
        return self.status == 'Active' and codename in self.codenames(campus)

    def _clear_grant_cache(self):
        getattr(self, '_prefetched_objects_cache', {}).pop('permission_grants', None)

    def grant(self, *codenames, campus=None):
        for perm in hsadmin_permission_objects(codenames):
            HSPositionPermission.objects.get_or_create(
                position=self, permission=perm, campus=campus)
        self._clear_grant_cache()

    def revoke(self, *codenames, campus=None):
        HSPositionPermission.objects.filter(
            position=self, campus=campus,
            permission__in=hsadmin_permission_objects(codenames)).delete()
        self._clear_grant_cache()

    def set_perms(self, codenames, campus=None):
        """Replace the grants of one scope (`campus`, or the all-campuses scope)."""
        HSPositionPermission.objects.filter(
            position=self, campus=campus, **_grant_ct()).delete()
        self.grant(*codenames, campus=campus)

    def set_grants(self, pairs):
        """Replace every grant with [(codename, campus or None)]."""
        HSPositionPermission.objects.filter(position=self, **_grant_ct()).delete()
        for code, campus in pairs:
            self.grant(code, campus=campus)

    def toggle_student_recommendation(self):
        if self.status == 'Active':
            if self.has_perm(HSAdminPerm.MANAGE_STUDENT_RECOMMENDATION):
                self.revoke(HSAdminPerm.MANAGE_STUDENT_RECOMMENDATION)
            else:
                self.grant(HSAdminPerm.MANAGE_STUDENT_RECOMMENDATION)
        
        self.save()

    def toggle_status(self):
        if self.status == 'Active':
            self.status = 'Inactive'
        else:
            self.status = 'Active'
        
        self.save()

    @classmethod
    def get_or_add(cls, hsadmin, highschool, position, status):
        try:
            record = HSAdministratorPosition.objects.get(
                hsadmin=hsadmin,
                highschool=highschool,
                position=position
            )
        except HSAdministratorPosition.DoesNotExist:
            record = HSAdministratorPosition(
                hsadmin=hsadmin,
                highschool=highschool,
                position=position,
                status=status,
            )
            record.save()
        return record


class HSPositionPermission(models.Model):
    """One HS admin permission granted on a position, optionally for one campus.

    Null campus = every campus (the only kind a single-campus deployment
    stores). A campus grant and the all-campuses grant of the same permission
    may coexist; checks treat them as a union.
    """
    position = models.ForeignKey(
        'cis.HSAdministratorPosition', on_delete=models.CASCADE,
        related_name='permission_grants')
    permission = models.ForeignKey(
        'auth.Permission', on_delete=models.CASCADE, related_name='+',
        limit_choices_to={**_PERMISSION_CT, 'codename__in': HSAdminPerm.ALL})
    campus = models.ForeignKey(
        'cis.Campus', null=True, blank=True, on_delete=models.CASCADE, related_name='+')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['position', 'permission', 'campus'], name='hsposperm_unique_campus'),
            models.UniqueConstraint(
                fields=['position', 'permission'], condition=Q(campus__isnull=True),
                name='hsposperm_unique_all_campuses'),
        ]

