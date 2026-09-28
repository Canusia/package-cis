"""TabRegistry for cis-owned index pages (package-cis #41).

`TabRegistry` itself lives in each tenant's `myce/component_registry/tabs.py`,
and most tenants' copy has no `disable()` / `set_active()` (only lsco's does).
A registry cis creates therefore carries both itself, so a tenant can opt out
of a tab whatever version of the host class it runs:

    from cis.tabs.course_index import course_index_tabs
    course_index_tabs.disable('course_administrators', 'app_requirements')

It also falls back to the first visible tab when no tab is marked active, so
disabling the default tab never leaves the page with nothing selected.
"""
from myce.component_registry.tabs import TabRegistry


class IndexTabRegistry(TabRegistry):

    def disable(self, *slugs):
        """Unregister tabs this tenant does not use.

        The tab leaves the nav and its pane is never rendered, so its table
        never initialises or calls the API. Raises KeyError for an unknown
        slug rather than skipping it: an opt-out list that silently no-ops
        would let an upstream rename put a hidden tab back on the page.
        """
        for slug in slugs:
            if slug not in self._tabs:
                raise KeyError(
                    f'Cannot disable unknown tab {slug!r}. Registered: '
                    f'{sorted(self._tabs)}')
            del self._tabs[slug]

    def set_active(self, slug):
        """Make `slug` the default tab, clearing any previous default."""
        if slug not in self._tabs:
            raise KeyError(
                f'Cannot activate unknown tab {slug!r}. Registered: '
                f'{sorted(self._tabs)}')
        for s, t in self._tabs.items():
            t['active'] = (s == slug)

    def for_record(self, request, record, url_for):
        tabs = super().for_record(request, record, url_for)
        visible = [t for t in tabs.values() if not t['hidden']]
        if visible and not any(t['active'] for t in visible):
            visible[0]['active'] = True
        return tabs
