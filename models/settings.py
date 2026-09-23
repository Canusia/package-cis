# users/models.py
import uuid
from django.db import models
from django.db.models import JSONField
from simple_history.models import HistoricalRecords

class Setting(models.Model):
    """
    Setting/Config model
    """
    key = models.CharField(max_length=50, unique=True)
    value = JSONField(blank=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.key}"

    class Meta:
        unique_together = [("key")]

    @staticmethod
    def get_value(setting_key, k):
        try:
            setting = Setting.objects.get(key=setting_key)
            return setting.value.get(k, '')
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
