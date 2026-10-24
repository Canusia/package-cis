"""Importer knobs for tests (#114 item 10).

Empty on purpose: a tenant module without the knobs keeps the package
behaviour. Tests set a knob with
``mock.patch.object(module, 'KNOB', value, create=True)`` under
``override_settings(TENANT_SERVICES_APP='cis.tests.fake_tenant')``.
"""
