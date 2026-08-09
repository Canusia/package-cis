"""
One declaration per note kind, in a registry any app can add to.

Before this, a note kind was written three times — a branch in
`cis/views/note.py::add_new_note`, a form in `cis/forms/note.py`, and a model
with its own `add_note()` in `cis/models/note.py` — and only `cis` could add
one. `visitreportnote` and `teacherapplicationnote` are `cis` branches today
purely because there was nowhere else to put them.

A NoteType declares what varies: the owner FK, the form, who may post it, and
which objects they may post it against. Everything else is shared.

Registering from another app, in AppConfig.ready():

    from cis.notes import NoteType, note_types

    note_types.register(NoteType(
        slug='visitreportnote',
        model=ClassVisitReportNote,
        owner_field='visit_report',
        owner_model=VisitReport,
        permission=user_has_cis_or_faculty_role,
    ))

Note on `meta['type']`: the shapes are deliberately left as each kind writes
them today. `cis/signals/notes.py` compares `meta.get('type') == 'response'`
in four places while testing membership (`'to_parent' in …`) in others, so the
string-vs-list difference is load-bearing for replies. Normalising it is a
separate change with its own test pass.
"""
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def _authenticated(user):
    return bool(user and getattr(user, 'is_authenticated', False))


@dataclass(frozen=True)
class NoteType:
    """A kind of note: which model it writes, and who may write it."""

    slug: str
    model: type
    owner_field: str
    owner_model: type
    form: Optional[type] = None

    #: (user) -> bool. Required — an unstated permission is how nine of these
    #: ended up reachable by any authenticated user.
    permission: Callable = _authenticated

    #: (user, owner) -> bool. Object-level check, run after `permission` when
    #: the owner record is resolvable. None means no object scoping.
    scope: Optional[Callable] = None

    supports_media: bool = False
    supports_reply: bool = False

    #: Extra keyword defaults handed to the generic writer.
    extras: dict = field(default_factory=dict)

    def create(self, request, note_form):
        """
        Write the note.

        Delegates to the model's own `add_note()` when it has one, so kinds
        with bespoke behaviour (student notes and their side effects, media
        uploads, reply threading) keep it exactly. Kinds without one get the
        generic writer, which is what the simple `add_note()` bodies all did.
        """
        add_note = getattr(self.model, 'add_note', None)
        if callable(add_note):
            return add_note(request, note_form)
        return self.create_generic(request, note_form)

    def create_generic(self, request, note_form):
        note = self.model()
        setattr(
            note,
            self.owner_field,
            self.owner_model.objects.get(pk=note_form.cleaned_data['add_to']),
        )
        note.createdby = request.user
        note.note = note_form.cleaned_data['note']
        for attr, value in self.extras.items():
            setattr(note, attr, value)
        note.save()
        return note

    def owner_for(self, request):
        """
        Resolve the owner record this request refers to, or None.

        Used for object scoping. `add_to` is the owner on a create; on the GET
        that renders the form it arrives as `parent`.
        """
        source = request.POST if request.method == 'POST' else request.GET
        owner_id = source.get('add_to') or source.get('parent')
        if not owner_id or owner_id == '-1':
            return None
        try:
            return self.owner_model.objects.get(pk=owner_id)
        except Exception:
            return None

    def may(self, request):
        """True when this request is allowed to act on this note kind."""
        if not self.permission(request.user):
            return False
        if self.scope is None:
            return True
        owner = self.owner_for(request)
        if owner is None:
            # Nothing to scope against — the handler's own get_object_or_404
            # is left to reject an unusable id.
            return True
        return bool(self.scope(request.user, owner))


class NoteRegistry:
    """Slug -> NoteType, populated by cis and by any app that wants notes."""

    def __init__(self):
        self._types = OrderedDict()

    def register(self, note_type):
        if note_type.slug in self._types:
            logger.warning(
                'note type %s re-registered; replacing', note_type.slug
            )
        self._types[note_type.slug] = note_type
        return note_type

    def get(self, slug):
        return self._types.get(slug)

    def slugs(self):
        return list(self._types.keys())

    def __contains__(self, slug):
        return slug in self._types

    def __iter__(self):
        return iter(self._types.values())


note_types = NoteRegistry()
