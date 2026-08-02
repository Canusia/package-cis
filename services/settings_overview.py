"""Generic engine that renders a settings-overview profile.

Resolves the profile from the tenant config app (settings.TABLE_CONFIGS_APP),
then for each configurator reads labels from the form class's base_fields and
current values from its from_db(), mirroring how setting.record_details loads a
setting. Purely read-only; editing is handled separately via the setting app's
record_details/run_record endpoints.
"""
import importlib
import logging

from django import forms
from django.conf import settings
from django.forms import HiddenInput
from django.utils.module_loading import import_string

import importlib.util
if importlib.util.find_spec('setting.setting'):
    from setting.setting.models import SettingRecord
else:
    from setting.models import SettingRecord

logger = logging.getLogger(__name__)

# Widget classes whose value we render as raw (trusted) HTML rather than escaped.
_HTML_WIDGET_HINTS = ('Textarea', 'CKEditor')


def _get_profile(name):
    mod = importlib.import_module(
        f'{settings.TABLE_CONFIGS_APP}.services.settings_overview')
    return mod.get_profile(name)


def _is_empty(value):
    return value is None or (isinstance(value, str) and value.strip() == '') \
        or value == [] or value == {}


def _render_value(value):
    # Returned raw (unescaped) here; the template renders non-HTML values
    # with Django's default auto-escaping (`{{ f.value }}`), so escaping in
    # the engine would double-escape. Only is_html=True values are rendered
    # with `|safe` and bypass this path entirely.
    if isinstance(value, (list, tuple)):
        return ', '.join(str(v) for v in value)
    return str(value)


def _resolve_choice(form, key, field, raw):
    """Map a stored choice value (or list) to its human label using the
    instantiated form's populated choices. Falls back to the raw value(s)."""
    bound = form.fields.get(key) if form is not None else None
    choices = dict(getattr(bound, 'choices', []) or []) if bound is not None else {}
    if isinstance(field, forms.MultipleChoiceField):
        vals = raw if isinstance(raw, (list, tuple)) else [raw]
        return ', '.join(str(choices.get(str(v), v)) for v in vals)
    return str(choices.get(str(raw), raw))


def _build_item(cfg_item, request=None):
    app, name = cfg_item['app'], cfg_item['name']
    item = {'title': f'{app}.{name}', 'record_id': None,
            'description': '', 'available': False, 'fields': []}
    try:
        record = SettingRecord.objects.filter(app=app, name=name).first()
        form_cls = import_string(f'{app}.settings.{name}.{name}')
        values = form_cls.from_db() or {}

        # Instantiate the form (like setting.record_details) so ChoiceField
        # choices are populated for label resolution. Isolated try/except: on
        # failure we keep raw values rather than dropping the whole setting.
        form = None
        if request is not None:
            try:
                form = form_cls(request, initial=values)
            except Exception as e:
                logger.warning('settings_overview: %s.%s form init failed: %s', app, name, e)
                form = None

        overrides = {}
        hook = getattr(form_cls, 'overview_render', None)
        if callable(hook):
            try:
                overrides = hook(values) or {}
            except Exception as e:
                logger.warning('settings_overview: %s.%s overview_render failed: %s', app, name, e)
                overrides = {}

        if record is not None:
            item['title'] = record.title
            item['record_id'] = str(record.id)
            # SettingRecord.description; '-' is the seeded placeholder → treat as blank.
            desc = (record.description or '').strip()
            item['description'] = '' if desc == '-' else desc

        keys = cfg_item.get('fields') or list(form_cls.base_fields.keys())
        hide = set(cfg_item.get('hide') or [])
        fields = []
        for key in keys:
            if key in hide or key not in form_cls.base_fields:
                continue
            field = form_cls.base_fields[key]
            if isinstance(field.widget, HiddenInput):
                continue
            raw = values.get(key)
            widget_name = type(field.widget).__name__
            if key in overrides:
                rendered = str(overrides[key])
                empty = False
                is_html = any(h in widget_name for h in _HTML_WIDGET_HINTS)
            else:
                empty = _is_empty(raw)
                is_html = any(h in widget_name for h in _HTML_WIDGET_HINTS) and not empty
                if empty:
                    rendered = ''
                elif isinstance(field, forms.ChoiceField) and form is not None:
                    rendered = _resolve_choice(form, key, field, raw)
                elif is_html:
                    rendered = str(raw)          # trusted admin HTML
                else:
                    rendered = _render_value(raw)
            fields.append({
                'label': str(field.label or key),
                'value': rendered,
                'is_empty': empty,
                'is_html': is_html,
            })
        item['fields'] = fields
        item['available'] = True
    except Exception as e:                       # missing record/import/from_db
        logger.warning('settings_overview: %s.%s unavailable: %s', app, name, e)
        return {'title': f'{app}.{name}', 'record_id': None,
                'description': '', 'available': False, 'fields': []}
    return item


def build_overview(profile_name, request=None):
    profile = _get_profile(profile_name)
    out = {'title': profile.get('title', ''), 'sections': []}
    for section in profile['sections']:
        sec = {'title': section['title'], 'items': []}
        for cfg_item in section['items']:
            sec['items'].append(_build_item(cfg_item, request=request))
        out['sections'].append(sec)
    return out
