# users/models.py
import uuid
from django.conf import settings as django_settings
from django.db import models
from django.db.models import JSONField, Q
from simple_history.models import HistoricalRecords

# Settings that are per campus on a multi-campus deployment besides the
# CAMPUS_CODE_PREFIX-ed keys (MC-05, #29): each college has its own SIS
# credentials, consume config, future-sections window, roster, syllabus and
# charge rules. Anything else (menu, two_step, sms, password_reset, ...) is
# one row for the whole deployment.
EXTRA_CAMPUS_SCOPED_KEYS = frozenset({
    'cis.settings.sis_settings',
    'ethos.settings.ethos_consume',
    'cis_future_sections',
    'cis.settings.roster_verification',
    'cis.settings.syllabi_review',
    'cis.settings.registration_charges',
})


def is_campus_scoped(key):
    """True for a setting that has one row per campus on a multi-campus deployment."""
    prefix = getattr(django_settings, 'CAMPUS_CODE_PREFIX', '')
    return bool(key) and (
        (bool(prefix) and key.startswith(f'{prefix}_'))
        or key in EXTRA_CAMPUS_SCOPED_KEYS)


def _campus_for(key):
    """The campus a campus-scoped lookup must be narrowed to, or None when the
    lookup is unscoped (single-campus mode, or a global key). Raises
    NoCampusContext in multi-campus mode with no campus set -- a global row is
    never a stand-in for a campus's own."""
    from cis.campus_context import current_campus, is_multi_campus
    if not is_multi_campus() or not is_campus_scoped(key):
        return None
    return current_campus()


class SettingQuerySet(models.QuerySet):
    """Narrows lookups of campus-scoped keys to the current campus.

    Only when MULTI_CAMPUS is on, and only for lookups that name the key
    (key=...) without naming a campus; everything else passes through, so the
    existing Setting.objects.get(key=...) call sites work unchanged.
    """

    @staticmethod
    def _with_campus(kwargs):
        if 'key' not in kwargs or 'campus' in kwargs or 'campus_id' in kwargs:
            return kwargs
        campus = _campus_for(kwargs['key'])
        if campus is None:
            return kwargs
        return {**kwargs, 'campus': campus}

    def filter(self, *args, **kwargs):
        return super().filter(*args, **self._with_campus(kwargs))

    def exclude(self, *args, **kwargs):
        return super().exclude(*args, **self._with_campus(kwargs))

    def get(self, *args, **kwargs):
        return super().get(*args, **self._with_campus(kwargs))

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
