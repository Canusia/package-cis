"""Remove cis's SettingRecord rows for the portal-text settings a portal
package now owns (#81, #82), so the CE settings list shows one entry each.

Only for names cis no longer registers in this deployment (the package is
installed). The stored Setting rows are kept: they are the package's seed and
the fallback for older readers. Mirrors package-faculty 0002.
"""
from django.db import migrations


def hide(apps, schema_editor):
    from cis.apps import CisConfig, PORTAL_TEXT_OWNERS
    registered = {record['name'] for record in CisConfig.CONFIGURATORS}
    gone = [name for name in PORTAL_TEXT_OWNERS if name not in registered]
    if gone:
        SettingRecord = apps.get_model('setting', 'SettingRecord')
        SettingRecord.objects.filter(app='cis', name__in=gone).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('cis', '0107_emailchangerequest'),
        ('setting', '0002_settingrecord_app'),
    ]

    operations = [
        migrations.RunPython(hide, migrations.RunPython.noop),
    ]
