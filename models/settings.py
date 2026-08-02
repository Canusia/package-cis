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
