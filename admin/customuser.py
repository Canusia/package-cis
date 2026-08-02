from django.contrib import admin

# Register your models here.
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from cis.forms.customuser import CustomUserCreationForm, CustomUserChangeForm
from cis.models.customuser import CustomUser

class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = CustomUser
    list_display = ['email', 'username', 'psid', 'account_locked',
                    'failed_login_attempts']
    actions = ['unlock_accounts']

    @admin.action(description='Unlock selected accounts (clear login lock)')
    def unlock_accounts(self, request, queryset):
        for user in queryset:
            user.unlock()

admin.site.register(CustomUser, CustomUserAdmin)
