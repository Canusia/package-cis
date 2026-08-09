from django.http import JsonResponse

from cis.actions.registry import add_new_actions

from cis.views.hs_administrator import (
    get_password_reset_link as hs_administrator_pwd_reset_link
)

from ..views.users import (
    get_password_reset_link as user_pwd_reset_link
)

from cis.utils import user_has_cis_role

def get_footer(request, page_type='non_logged'):
    from cis.settings.footer import footer
    from cis.utils import user_has_student_role, user_has_highschool_admin_role, user_has_cis_role, user_has_faculty_role

    try:
        if request.user.is_authenticated:
            if user_has_cis_role(request.user):
                page_type = "logged_staff"
            else:
                if user_has_student_role(request.user):
                    page_type = "logged_student"
                elif user_has_highschool_admin_role(request.user):
                    page_type = "logged_hsadmin"
                elif user_has_faculty_role(request.user):
                    page_type = "logged_faculty"
    except:
        ...
        
    setting = footer.from_db()

    return JsonResponse({'footer': setting.get(page_type, '')})
get_footer.login_required = False

def get_landing_page_text(request):
    page_type = request.GET.get('page', 'homepage') + '_text'

    from cis.settings.portal_content import portal_content
    setting = portal_content.from_db()

    return JsonResponse({'text': setting.get(page_type, '')})
get_landing_page_text.login_required = False

def pwd_reset_link(request):
    if request.method == 'POST':
        model = request.POST.get('model', None)
    else:
        model = request.GET.get('model', None)

    if model == 'hs_administrator':
        return hs_administrator_pwd_reset_link(request)

    if model == 'customuser':
        return user_pwd_reset_link(request)

def add_new(request):
    '''
    Add new page

    Non-notes actions dispatch through add_new_actions, where each one declares
    its own permission — this URL has no role gate and is forwarded from the
    high school admin portal, so the per-action permission is the only thing in
    front of each handler. Notes are registered there too (cis/actions/notes.py).
    '''

    if request.method == 'POST':
        model = request.POST.get('model', None)
    else:
        model = request.GET.get('model', None)

    return add_new_actions.dispatch(request, model)
