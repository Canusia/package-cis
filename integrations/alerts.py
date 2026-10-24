"""The one place ``cis`` writes to the ``alerts`` app (#100).

``alerts`` holds the in-app notifications cis raises when a note is answered
or an instructor application changes hands. They are fire-and-forget: nothing
in cis reads them back, so cis works without the app -- the alerts are simply
not created. ``cis.checks`` warns (``cis.W009``) when the app is missing.

Do not add ``from alerts…`` anywhere else in ``cis``. The model is resolved
through the app registry at call time, so neither app-loading order nor the
app's absence can break ``cis`` import.
"""

__all__ = ['ALERTS_APP_LABEL', 'alerts_installed', 'alert_model', 'create_alert',
           'mark_alerts_read']

ALERTS_APP_LABEL = 'alerts'


def alerts_installed():
    """True when an app labelled ``alerts`` is in INSTALLED_APPS."""
    from django.apps import apps
    return ALERTS_APP_LABEL in apps.app_configs


def alert_model():
    """The ``alerts.Alert`` model, or None when the app is absent."""
    if not alerts_installed():
        return None
    from django.apps import apps
    try:
        return apps.get_model(ALERTS_APP_LABEL, 'Alert')
    except LookupError:
        return None


def create_alert(alert_type, recipient, message):
    """Create and return an Alert; None (and nothing written) without the app."""
    Alert = alert_model()
    if Alert is None:
        return None
    alert = Alert()
    alert.alert_type = alert_type
    alert.recipient = recipient
    alert.message = message
    alert.save()
    return alert


def mark_alerts_read(read_on, **filters):
    """Stamp ``read_on`` on the unread alerts matching ``filters``. Returns the
    number updated (0 without the app)."""
    Alert = alert_model()
    if Alert is None:
        return 0
    return Alert.objects.filter(read_on__isnull=True, **filters).update(read_on=read_on)
