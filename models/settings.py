# users/models.py
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from django.conf import settings as django_settings
from django.db import models
from django.db.models import Exists, JSONField, Q
from simple_history.models import HistoricalRecords

# Settings that are per campus on a multi-campus deployment besides the
# CAMPUS_CODE_PREFIX-ed keys (MC-05, #29): each college has its own SIS
# credentials, consume config, future-sections window, roster, syllabus and
# charge rules. These are STRICT: never read from another row.
EXTRA_CAMPUS_SCOPED_KEYS = frozenset({
    'cis.settings.sis_settings',
    'ethos.settings.ethos_consume',
    'cis_future_sections',
    'cis.settings.roster_verification',
    'cis.settings.syllabi_review',
    'cis.settings.registration_charges',
})

# Settings that really are deployment-wide (#129): one row, superuser-only
# in multi-campus mode. sent_email's retention prunes the shared mail log.
GLOBAL_SETTING_KEYS = frozenset({
    'cis.settings.menu',
    'cis.settings.two_step',
    'cis.settings.sms',
    'cis.settings.password_reset',
    'ses_tracking.settings.email_routing',
    'ses_tracking.settings.sent_email',
})

# STRICT: one row per campus, no fallback (MC-05).
# CAMPUS: the campus's row, else the shared row; a save writes the campus row.
# GLOBAL: the shared row.
STRICT, CAMPUS, GLOBAL = 'strict', 'campus', 'global'

# Inside shared_settings(), CAMPUS keys read and write the shared row with no
# campus needed: installing defaults, register_settings, scripts. STRICT keys
# still need a campus.
_shared = ContextVar('cis_shared_settings', default=False)


@contextmanager
def shared_settings():
    token = _shared.set(True)
    try:
        yield
    finally:
        _shared.reset(token)


def setting_scope(key):
    """How a multi-campus deployment stores ``key`` (#129)."""
    prefix = getattr(django_settings, 'CAMPUS_CODE_PREFIX', '')
    if key and ((prefix and key.startswith(f'{prefix}_'))
                or key in EXTRA_CAMPUS_SCOPED_KEYS):
        return STRICT
    if key in GLOBAL_SETTING_KEYS:
        return GLOBAL
    return CAMPUS


def is_campus_scoped(key):
    """True for a setting that can have one row per campus (STRICT or CAMPUS)."""
    return bool(key) and setting_scope(key) != GLOBAL


def _campus_for(key):
    """The campus a new row for ``key`` belongs to, or None for a shared row.

    None in single-campus mode, for a GLOBAL key, and for a CAMPUS key inside
    shared_settings(). Otherwise the current campus -- raising NoCampusContext
    in multi-campus mode with none set.
    """
    from cis.campus_context import current_campus, is_multi_campus
    if not is_multi_campus():
        return None
    scope = setting_scope(key)
    if scope == GLOBAL or (scope == CAMPUS and _shared.get()):
        return None
    return current_campus()


class SettingQuerySet(models.QuerySet):
    """Narrows lookups that name ``key=`` (and no campus) by the key's scope.

    Only when MULTI_CAMPUS is on; everything else passes through, so the
    existing Setting.objects.get(key=...) call sites work unchanged.

    STRICT: the current campus's row. GLOBAL (and CAMPUS inside
    shared_settings()): the shared row. CAMPUS: the current campus's row if
    it has one, else the shared row -- in one query -- and every shared row
    it yields is marked ``_fallback_campus`` so saving it copies it to the
    campus instead of editing the shared row (#129). With no campus set,
    STRICT and CAMPUS raise NoCampusContext.

    ``Setting.objects.get`` goes through ``filter``, so it is narrowed too.
    """

    @staticmethod
    def _narrowing(kwargs):
        """(kwargs, extra Q or None, fallback campus or None)."""
        if 'key' not in kwargs or any(
                name == 'campus' or name.startswith('campus_') for name in kwargs):
            return kwargs, None, None
        from cis.campus_context import current_campus, is_multi_campus
        if not is_multi_campus():
            return kwargs, None, None
        key = kwargs['key']
        scope = setting_scope(key)
        if scope == GLOBAL or (scope == CAMPUS and _shared.get()):
            return {**kwargs, 'campus__isnull': True}, None, None
        campus = current_campus()
        if scope == STRICT:
            return {**kwargs, 'campus': campus}, None, None
        own = Setting._base_manager.filter(key=key, campus=campus)
        fallback = Q(campus=campus) | (Q(campus__isnull=True) & ~Exists(own))
        return kwargs, fallback, campus

    def filter(self, *args, **kwargs):
        kwargs, extra, campus = self._narrowing(kwargs)
        qs = super().filter(*args, **kwargs)
        if extra is not None:
            qs = qs.filter(extra)
            qs._fallback_campus = campus
        return qs

    def exclude(self, *args, **kwargs):
        # STRICT/GLOBAL narrow as filter() does; a CAMPUS key's fallback has
        # no exclude() meaning, so it is excluded by key alone, as before #129.
        narrowed, extra, _ = self._narrowing(kwargs)
        return super().exclude(*args, **(kwargs if extra is not None else narrowed))

    def _clone(self):
        clone = super()._clone()
        clone._fallback_campus = getattr(self, '_fallback_campus', None)
        return clone

    def _fetch_all(self):
        super()._fetch_all()
        campus = getattr(self, '_fallback_campus', None)
        if campus is None:
            return
        for obj in self._result_cache:
            if isinstance(obj, Setting) and obj.campus_id is None:
                obj._fallback_campus = campus

    def create(self, **kwargs):
        # Mirrors QuerySet.create(), noting whether the caller named a campus:
        # an explicit campus=None (a deliberate global row) must not be
        # filled in by save().
        obj = self.model(**kwargs)
        obj._campus_given = 'campus' in kwargs or 'campus_id' in kwargs
        self._for_write = True
        obj.save(force_insert=True, using=self.db)
        return obj


class Setting(models.Model):
    """
    Setting/Config model
    """
    key = models.CharField(max_length=50)
    value = JSONField(blank=True)
    # Null means the row serves the whole deployment. Campus-scoped keys get
    # one row per campus when MULTI_CAMPUS is on (MC-05); on a single-campus
    # deployment every row stays NULL, as before.
    campus = models.ForeignKey(
        'cis.Campus', null=True, blank=True, on_delete=models.PROTECT,
        related_name='settings')
    history = HistoricalRecords()

    objects = SettingQuerySet.as_manager()

    def __str__(self):
        return f"{self.key}"

    class Meta:
        # Partial constraints: a global row is unique by key, exactly as the old
        # unique key was; a campus row is unique within its campus. Postgres
        # treats NULLs as distinct, so unique_together would allow duplicate
        # global rows.
        constraints = [
            models.UniqueConstraint(
                fields=['key'], condition=Q(campus__isnull=True),
                name='setting_unique_key_global'),
            models.UniqueConstraint(
                fields=['campus', 'key'], condition=Q(campus__isnull=False),
                name='setting_unique_key_per_campus'),
        ]

    def save(self, *args, **kwargs):
        if self.campus_id is None and not getattr(self, '_campus_given', False):
            campus = _campus_for(self.key)
            if campus is not None:
                self.campus = campus
        super().save(*args, **kwargs)

    @staticmethod
    def get_value(setting_key, k):
        from cis.campus_context import NoCampusContext
        try:
            setting = Setting.objects.get(key=setting_key)
            return setting.value.get(k, '')
        except NoCampusContext:
            # A campus-scoped key read with no campus set is a bug in the
            # caller, not a missing setting -- don't turn it into ''.
            raise
        except:
            return ""

    @classmethod
    def install_defaults(cls, key, defaults):
        """Create the setting, or add only the keys it does not already have.

        `register_settings` is re-run whenever a tenant adopts a new cis version,
        so install() must be safe to run against a customised setting. Assigning
        `defaults` wholesale replaced every tenant edit (issue #19). Merging
        key-by-key means a newly shipped key still appears, while anything the
        tenant has already set is left alone.
        """
        defaults = defaults or {}

        try:
            setting = cls.objects.get(key=key)
        except cls.DoesNotExist:
            setting = cls(key=key)
            setting.value = defaults
            setting.save()
            return setting

        stored = setting.value
        if not isinstance(stored, dict):
            stored = {}

        missing = {k: v for k, v in defaults.items() if k not in stored}
        if not missing:
            return setting

        stored.update(missing)
        setting.value = stored
        setting.save()
        return setting
