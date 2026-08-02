from rest_framework import serializers

from ..models.crontab import CronLog, CronTab


class CronTabSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = CronTab
        fields = '__all__'

class CronLogSerializer(serializers.ModelSerializer):

    summary = serializers.CharField(read_only=True)
    command = serializers.CharField(read_only=True)

    cron = CronTabSerializer()
    
    class Meta:
        model = CronLog
        fields = '__all__'
        datatables_always_serialize = [
            'summary',
            'command'
        ]
