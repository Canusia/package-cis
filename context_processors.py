import os
from django.conf import settings

def export_vars(request):
    data = {}
    data['MYCE_SETTINGS'] = settings.MY_CE
    return data