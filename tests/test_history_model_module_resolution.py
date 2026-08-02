"""
Regression test for the django_admin_shell `/admin/shell/` crash:

    AttributeError: module 'cis' has no attribute 'HistoricalSetting'

simple_history sets its ``Historical*`` models' ``__module__`` to the app
import path (``cis``) rather than the submodule the tracked model lives in
(``cis.models.settings``), and only ``setattr``s the class onto that
submodule. Consumers that resolve a model with
``getattr(import_module(model.__module__), model.__name__)`` — both
``django_admin_shell``'s ``get_scope`` and Django's ``manage.py shell``
auto-import — then raise ``AttributeError``.

``CisConfig.ready()`` binds every cis model onto the module named by its
``__module__`` so the lookup succeeds.
"""
import importlib

from django.apps import apps
from django.test import SimpleTestCase


class CisModelModuleResolutionTests(SimpleTestCase):
    def test_every_cis_model_is_resolvable_from_its_module(self):
        unresolvable = []
        for model in apps.get_app_config('cis').get_models():
            module = importlib.import_module(model.__module__)
            if not hasattr(module, model.__name__):
                unresolvable.append(f"{model.__module__}.{model.__name__}")

        self.assertEqual(
            unresolvable, [],
            "Models not gettable from their __module__ — django_admin_shell "
            "get_scope() will crash on these: " + ", ".join(unresolvable),
        )
