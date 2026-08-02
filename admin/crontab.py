from django.contrib import admin

# Register your models here.
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from cis.models.crontab import CronTab

@admin.register(CronTab)
class CronTabAdmin(admin.ModelAdmin):
    list_display = (
        'cron', 'command'
    )

    fields = [
        'cron',
        'command'
    ]