# users/models.py
import uuid

from django.db import models, IntegrityError
from django.contrib.auth.models import Group
from django.db.models import JSONField

from cis.models.customuser import CustomUser
from cis.models.course import TechCenter

class TechCenterStaff(models.Model):
    """
    Base user model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField('cis.CustomUser', on_delete=models.PROTECT)
    #Look through access db to see other fields

    tech_center = JSONField(blank=True, null=True)

    class Meta:
        unique_together = [
            'user'
        ]

    def __str__(self):
        return self.user.first_name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        #if self._state.adding is True
        group = Group.objects.get(name='tech_center_staff')
        self.user.groups.add(group)


    @classmethod
    def get_or_add(cls, username, email, **kwargs):
        try:
            record = TechCenterStaff.objects.get(
                user__username__iexact=username
            )
        except TechCenterStaff.DoesNotExist:
            user = CustomUser.get_or_add(
                username=email,
                email=email,
                **kwargs
            )

            try:
                record = TechCenterStaff(user=user)
                record.save()
            except:
                return None
        return record

    @property
    def tech_centers(self):
        if self.tech_center:
            return TechCenter.objects.filter(
                id__in=self.tech_center
            )
        return TechCenter.objects.none()

    @property
    def service_areas(self):
        """
        Return a list of postal codes
        """
        service_areas = []
        for center in self.tech_centers:
            areas = center.serving_area.replace(' ', '').split(',')
            service_areas += areas
        return service_areas
