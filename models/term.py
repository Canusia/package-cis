# users/models.py
import uuid, logging
from django.db import models
from django.db.models import JSONField

logger = logging.getLogger(__name__)

class AcademicYear(models.Model):
    """
    Academic Year model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50, unique=True)
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
        try:
            record = AcademicYear.objects.get(
                name=name
            )
        except AcademicYear.DoesNotExist:
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
        unique_together = ['name']

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
