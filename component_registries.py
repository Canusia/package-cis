"""Package defaults for the host's `myce.component_registry.*` modules (#97).

cis views import their tab and action registries from the host's
`myce.component_registry` package. A tenant adopting the package without one
of those modules used to fail the whole cis URLconf. For the registries that
are nothing but empty registries plus an eager import of cis's own tabs and
actions, cis can supply the module itself: `install_defaults()` (run from
`CisConfig.__init__`) registers a stand-in under the host's module name, only
when the host does not ship that module. A host module always wins.

Registries that carry tenant content (course and academic_year wire SIS
actions) have no default; a host missing one is named by system check
cis.W012.
"""
import importlib
import importlib.util
import sys
import types
from collections import OrderedDict

PACKAGE = 'myce.component_registry'

# Every host registry module cis imports, at module level or per request.
REQUIRED_REGISTRIES = (
    'academic_year', 'access_request', 'class_section', 'class_section_index',
    'course', 'faculty_coordinator', 'highschool', 'hs_administrator',
    'registration', 'student', 'support_docs', 'teacher', 'term',
)


def _registry(name, actions=True, tabs=True, action_groups=()):
    """Attributes of a `<name>` registry module: `<name>_actions` (with any
    pre-declared groups, which fix the dropdown order) and `<name>_tabs`."""
    def build():
        from myce.component_registry import ActionRegistry
        from myce.component_registry.tabs import TabRegistry
        attrs = {}
        if actions:
            groups = OrderedDict((g, {'actions': OrderedDict()}) for g in action_groups)
            attrs[f'{name}_actions'] = ActionRegistry(groups)
        if tabs:
            attrs[f'{name}_tabs'] = TabRegistry()
        return attrs
    return build


# name -> (attribute factory, cis modules whose decorators fill the registry).
# Each mirrors the module Canusia/ewu ships. course and academic_year are left
# out: the host's modules wire SIS (ethos) actions cis cannot choose for it.
DEFAULTS = {
    'access_request': (_registry('access_request'), ('cis.tabs.access_request',)),
    'class_section': (_registry('class_section'), ('cis.tabs.class_section',)),
    # Apps eager-import their own index tabs from ready(); see the host module.
    'class_section_index': (_registry('class_section_index', actions=False), ()),
    'faculty_coordinator': (_registry('faculty_coordinator', actions=False),
                            ('cis.tabs.faculty_coordinator',)),
    'highschool': (_registry('highschool'), ('cis.tabs.highschool',)),
    'hs_administrator': (_registry('hs_administrator'), ('cis.tabs.hs_administrator',)),
    'registration': (_registry('registration'),
                     ('cis.tabs.registration', 'cis.actions.registration')),
    # Actions are registered by cis.views.student when the URLconf loads.
    'student': (_registry('student', action_groups=(
        'verification', 'verify_mark', 'email', 'password', 'download',
        'danger', 'bulk_only')), ('cis.tabs.student',)),
    'support_docs': (_registry('support_docs', tabs=False, action_groups=('status',)), ()),
    'teacher': (_registry('teacher'), ('cis.tabs.teacher',)),
    'term': (_registry('term'), ('cis.tabs.term',)),
}


def host_has(name):
    """Whether the host ships `myce.component_registry.<name>` (a cis
    default installed under that name does not count)."""
    dotted = f'{PACKAGE}.{name}'
    module = sys.modules.get(dotted)
    if module is not None:
        return not getattr(module, '__cis_default__', False)
    try:
        return importlib.util.find_spec(dotted) is not None
    except (ModuleNotFoundError, ValueError):
        return False


def install_defaults():
    """Register a cis default for each DEFAULTS module the host lacks, and
    return the names installed.

    Runs when the cis AppConfig is created (before any app's ready()), so a
    view imported from another app's ready() already finds the stand-in. It
    imports nothing that needs the app registry; `load_defaults` imports the
    cis tabs and actions that fill the stand-ins, from ready()."""
    try:
        if importlib.util.find_spec(PACKAGE) is None:
            return []
    except ModuleNotFoundError:  # no host `myce` package at all
        return []
    parent = importlib.import_module(PACKAGE)
    installed = []
    for name, (factory, _) in DEFAULTS.items():
        dotted = f'{PACKAGE}.{name}'
        if host_has(name) or dotted in sys.modules:
            continue
        module = types.ModuleType(dotted, f'cis default for {dotted} (#97).')
        module.__cis_default__ = True
        module.__dict__.update(factory())
        sys.modules[dotted] = module
        setattr(parent, name, module)
        installed.append(name)
    return installed


def load_defaults(names):
    """Import the cis modules whose decorators fill the named stand-ins."""
    for name in names:
        for path in DEFAULTS[name][1]:
            importlib.import_module(path)


def missing_registries():
    """Host registry modules cis needs that neither the host nor cis supplies."""
    return [
        name for name in REQUIRED_REGISTRIES
        if name not in DEFAULTS and not host_has(name)
    ]
