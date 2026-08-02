"""Cross-app bulk-mailer datasource(s) defined in the host ``cis`` app.

These self-register against the announcement app's ``bmailer_datasources``
registry. The module is eager-imported from ``CisConfig.ready()`` so the
datasource(s) are available at startup.
"""
import importlib.util

from django import forms
from django.template.loader import get_template

# Host code uses the editable-submodule path in dev (announcement.announcement)
# and the flat installed package (announcement) in prod.
if importlib.util.find_spec('announcement.announcement'):
    from announcement.announcement.datasources.registry import bmailer_datasources
    from announcement.announcement.datasources.base import (
        MyCE_BMailerDS, MyCE_BMailerForm)
else:
    from announcement.datasources.registry import bmailer_datasources
    from announcement.datasources.base import MyCE_BMailerDS, MyCE_BMailerForm

from cis.models.customuser import CustomUser


@bmailer_datasources.register(
    slug='cis_speakers',
    title='Speakers',
    descriptor='Users in the speaker group.')
class cis_speakers_DS(MyCE_BMailerDS):
    email_column = 'email'
    name_columns = ['FirstName', 'LastName']

    def data_columns(self):
        return {'first_name': 'FirstName', 'last_name': 'LastName', 'email': 'email'}

    def title(self):
        return 'Speakers'

    def description(self):
        return '<p>Users in the speaker group. Email is sent to the primary address.</p>'

    def data_filter(self, form_type='skinny', initial=None):
        form = MyCE_BMailerForm(form_type, 'cis_speakers')
        return get_template('announcements/datasource-form.html').render({'form': form})

    def data_source(self, filters, count=False):
        records = CustomUser.objects.filter(groups__name='speaker')
        if count:
            return records.count()
        return [{
            'FirstName': u.first_name,
            'LastName': u.last_name,
            'email': [u.email],
        } for u in records]
