"""
The add_new action registry, owned by cis.

Deliberately self-contained. The other registries (cis/tabs/*, cis/actions/
registration.py) are eager-imported *by* a host file in myce/component_registry/,
so a tenant that lacks that host file simply never imports them. This one is
reached from cis/views/ajax.py, which cis/urls.py imports on every tenant — so
depending on a host module here would hard-crash every deployment that has not
also had that file added. Only ewu has one.

ActionRegistry itself is present in every tenant's myce/component_registry, so
subclassing it is safe; the permission behaviour below is implemented here so it
does not depend on the host version.
"""
from django.http import JsonResponse

from myce.component_registry import ActionRegistry


class GuardedActionRegistry(ActionRegistry):
    """
    An ActionRegistry that refuses to register an action without a permission,
    and enforces it on dispatch.

    /ce/add_new_ajax/ has no role gate on the URL and is forwarded from the
    high school admin portal, so the per-action permission is the only thing in
    front of each handler. Forgetting one is how eleven handlers ended up
    reachable by any authenticated user — so omission fails at import, not at
    request time.
    """

    #: Matches the wording the hand-written per-branch guards used, which the
    #: PT regression tests and the client JS both rely on.
    PERMISSION_DENIED_MESSAGE = 'You are not authorized to perform this action.'

    def action(self, group, label, scope, slug=None, permission=None, **kwargs):
        if permission is None:
            raise ValueError(
                f"action '{slug or label}' must declare a permission — "
                f"{type(self).__name__} does not allow ungated actions"
            )
        return super().action(
            group, label, scope, slug=slug, permission=permission, **kwargs
        )

    def dispatch(self, request, action_slug):
        """
        Resolve, authorize, run.

        The permission check is done here rather than deferred to the base
        class so the 403 body is identical on every tenant, whatever version of
        myce/component_registry the host happens to ship.
        """
        action = self._find_action(action_slug)
        if action is None:
            return JsonResponse({
                'outcome': 'alert',
                'status': 'error',
                'title': 'Error',
                'message': 'Invalid action.',
            }, status=400)

        permission = action.get('permission')
        if permission is None or not permission(request.user):
            return JsonResponse({
                'status': 'error',
                'message': self.PERMISSION_DENIED_MESSAGE,
            }, status=403)

        handler = action.get('handler')
        if handler is None:
            return JsonResponse({
                'outcome': 'alert',
                'status': 'error',
                'title': 'Error',
                'message': 'Invalid action.',
            }, status=400)

        if callable(handler):
            return handler(request)
        return self._resolve_handler(handler)(request)


add_new_actions = GuardedActionRegistry()

# Eager-import the action definitions so their decorators run. Kept at the
# bottom: the instance above must exist before these import it back.
import cis.actions.add_new  # noqa: E402,F401
import cis.actions.notes  # noqa: E402,F401
