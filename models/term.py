# users/models.py
import uuid, logging
from django.db import models
from django.db.models import JSONField, Q

logger = logging.getLogger(__name__)

class AcademicYear(models.Model):
    """
    Academic Year model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50)
    code = models.CharField(max_length=10, blank=True, null=True)
    cost_per_credit = models.FloatField(default=0.0)

    campus = models.ForeignKey(
        'cis.Campus', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='academic_years',
    )

    hs_start_date = models.DateField(
        null=True,
        blank=True
    )
    hs_end_date = models.DateField(
        null=True,
        blank=True
    )


    temp_id = models.IntegerField(blank=True, null=True)
    external_sis_id = models.UUIDField(blank=True, null=True)
    meta = JSONField(
        default=dict
    )

    def __str__(self):
        return self.name

    @classmethod
    def get_or_add(cls, name, **kwargs):
        # Names are unique per campus (MC-08), so match on the campus too when
        # the caller gives one.
        lookup = {'name': name}
        if 'campus' in kwargs:
            lookup['campus'] = kwargs['campus']
        record = AcademicYear.objects.filter(**lookup).first()
        if record is None:
            record = AcademicYear(name=name)
        
        try:
            for key, value in kwargs.items():
                setattr(record, key, value)
            record.save()
        except Exception as e:
            logger.error('Unable to add new academic year' + str(e))
            return AcademicYear.objects.none()

        return record

    @staticmethod
    def import_from_csv(dictReader):
        """Import Academic Years from CSV using the AcademicYearImporter service."""
        from cis.services.importers import AcademicYearImporter

        importer = AcademicYearImporter()
        return importer.process_csv(dictReader)

    class Meta:
        # MC-08 (#32): unique per campus, so two colleges on one deployment
        # can share a name. Two partial constraints rather than
        # unique_together: Postgres treats NULLs as distinct, so rows with no
        # campus would otherwise stop being unique at all.
        constraints = [
            models.UniqueConstraint(
                fields=['name'], condition=models.Q(campus__isnull=True),
                name='academicyear_unique_name_unassigned'),
            models.UniqueConstraint(
                fields=['campus', 'name'], condition=models.Q(campus__isnull=False),
                name='academicyear_unique_name_per_campus'),
        ]

def billed_to_q(term, prefix=''):
    """Q for rows (reached through ``prefix``) whose term bills to ``term``.

    A term's own sections bill to it unless it is a sub-term that bills with
    its parent; sub-terms that bill with ``term`` are included. One level only.
    """
    p = prefix
    own = Q(**{f'{p}term': term}) & (
        Q(**{f'{p}term__parent__isnull': True})
        | Q(**{f'{p}term__bills_with_parent': False}))
    from_children = Q(**{f'{p}term__parent': term, f'{p}term__bills_with_parent': True})
    return own | from_children


class Term(models.Model):
    """
    Term model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    academic_year = models.ForeignKey('cis.AcademicYear', on_delete=models.PROTECT)
    parent = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='sub_terms',
    )
    code = models.CharField(max_length=10)
    
    label = models.CharField(max_length=100)

    temp_id = models.IntegerField(blank=True, null=True)

    dates = JSONField(
        default=dict
    )
    
    external_sis_id = models.UUIDField(blank=True, null=True)
    meta = JSONField(
        default=dict
    )
    bills_with_parent = models.BooleanField(
        default=True,
        verbose_name='Bill with parent term',
        help_text="Charges for classes in this sub-term go on the parent "
                  "term's bill and use its payment due date. Ignored for a "
                  "term with no parent.",
    )

    @property
    def billing_term(self):
        """The term whose bill carries charges for this term's classes."""
        if self.parent_id and self.bills_with_parent:
            return self.parent
        return self

    def billing_terms_under(self):
        """Terms bill pay lists for this (active) term: its billing term, then
        its sub-terms that bill separately, by code."""
        return [self.billing_term] + list(
            self.sub_terms.filter(bills_with_parent=False).order_by('code'))

    def __str__(self):
        return f"{self.academic_year.name}, {self.label}"

    class Meta:
        unique_together = [("academic_year", "label")]
        ordering = ['-academic_year__name', '-code']
    
    @property
    def year(self):
        return ''

    @property
    def sexy_name(self):
        return str(self)

    @classmethod
    def by_code(cls, code, campus=None):
        """Terms with ``code``, the right campus's first (#94).

        Term.code is not unique: two campuses' terms may share a code. In
        multi-campus mode the lookup is limited to ``campus`` (default: the
        active campus, if any) plus campus-less years, so an importer never
        lands on another campus's term. Single-campus deployments get every
        term with the code, as before. Use ``.first()`` for one term.
        """
        from cis.campus_context import current_campus_or_none, is_multi_campus

        terms = cls.objects.filter(code=code)
        if is_multi_campus():
            campus = campus or current_campus_or_none()
            if campus is not None:
                terms = terms.filter(
                    models.Q(academic_year__campus=campus)
                    | models.Q(academic_year__campus__isnull=True)
                ).order_by(
                    models.F('academic_year__campus').asc(nulls_last=True),
                    '-academic_year__name')
        return terms

    @classmethod
    def with_descendants(cls, term_ids):
        """Terms `term_ids` plus every sub-term below them, at any depth."""
        from cis.services.term_hierarchy import expand_term_ids
        return cls.objects.filter(pk__in=expand_term_ids(term_ids))

    def would_create_cycle(self, candidate_parent):
        """True if setting self.parent = candidate_parent would form a cycle."""
        if candidate_parent is None:
            return False
        if candidate_parent.pk == self.pk:
            return True
        ancestor = candidate_parent
        seen = set()
        while ancestor is not None:
            if ancestor.pk == self.pk:
                return True
            if ancestor.pk in seen:
                break  # guard against a pre-existing cycle in the data
            seen.add(ancestor.pk)
            ancestor = ancestor.parent
        return False

    @staticmethod
    def import_from_csv(dictReader):
        """Import Terms from CSV using the TermImporter service."""
        from cis.services.importers import TermImporter

        importer = TermImporter()
        return importer.process_csv(dictReader)

    @classmethod
    def get_or_add(cls, academic_year, label, **kwargs):
        try:
            record = Term.objects.get(
                academic_year=academic_year,
                label=label
            )
        except Term.DoesNotExist:
            record = Term(
                academic_year=academic_year,
                label=label
            )
        
        try:
            for key, value in kwargs.items():
                setattr(record, key, value)
            record.save()
        except Exception as e:
            logger.error('Unable to add new term' + str(e))
            return Term.objects.none()

        return record
