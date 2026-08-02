from django.test import TestCase
from django.contrib.auth import get_user_model

from cis.forms.district import DistrictForm, DistrictPositionForm
from cis.models.district import District, DistrictPosition

class District(TestCase):
    '''District, DPosition Test cases'''
    
    def test_empty_form(self):
        form = DistrictForm()

        self.assertFalse(form.is_valid())

    def test_form(self):
        form = DistrictForm({
            'name':'d1',
            'status': 'Active'
        })

        self.assertTrue(form.is_valid())
        district = form.save()
        self.assertEqual(district.name, 'd1')

    def test_district_position_empty_form(self):  
        form = DistrictPositionForm()
        self.assertFalse(form.is_valid())

    def test_district_position_form(self):
        form = DistrictPositionForm({
            'name':'p1'
        })

        self.assertTrue(form.is_valid())
        position = form.save()
        self.assertEqual(position.name, 'p1')

    def test_dup_district_position(self):
        form = DistrictPositionForm({
            'name':'p1'
        })

        self.assertTrue(form.is_valid())
        form.save()

        form = DistrictPositionForm({
            'name':'p1'
        })

        self.assertFalse(form.is_valid())