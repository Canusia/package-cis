"""
Utility functions for CIS
"""
import os, csv, datetime, re, json
import socket
import ipaddress

import logging
logger = logging.getLogger(__name__)

from django.conf import settings
from django.http import HttpResponse
from django.contrib.sites.models import Site
from django.core.files.base import ContentFile

from rest_framework.permissions import BasePermission

from twilio.rest import Client as Twilio_Client

from smartystreets_python_sdk import StaticCredentials, exceptions, ClientBuilder
from smartystreets_python_sdk.us_street import Lookup as StreetLookup

from cis.backends.storage_backend import PrivateMediaStorage
from cis.models.settings import Setting

from django.core.validators import validate_email
from django.core.exceptions import ValidationError

def qr_code(data, version=1, return_type='str'):
    import qrcode
    import base64
    from django.http import HttpResponse
    from io import BytesIO
    from PIL import Image

    # Create a QR code image
    qr = qrcode.QRCode(
        version=version,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,  # Size of each box in the QR code
        border=4,  # Thickness of the border
    )
    qr.add_data(data)
    qr.make(fit=True)

    # Create an image from the QR code
    img = qr.make_image(fill='black', back_color='white')

    # Save image to a BytesIO buffer
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    
    img_str = base64.b64encode(buffer.read()).decode('utf-8')
    
    return img_str

def is_valid_email(email):
    try:
        validate_email(email)
        return True
    except ValidationError:
        return False


COUNTRY_LIST = [
    ('US', 'United States of America'),
    ('AF', 'Afghanistan'),
    ('AX', 'Åland Islands'),
    ('AL', 'Albania'),
    ('DZ', 'Algeria'),
    ('AD', 'Andorra'),
    ('AO', 'Angola'),
    ('AI', 'Anguilla'),
    ('AQ', 'Antarctica'),
    ('AG', 'Antigua and Barbuda'),
    ('AR', 'Argentina'),
    ('AM', 'Armenia'),
    ('AW', 'Aruba'),
    ('AU', 'Australia'),
    ('AT', 'Austria'),
    ('AZ', 'Azerbaijan'),
    ('BS', 'Bahamas'),
    ('BH', 'Bahrain'),
    ('BD', 'Bangladesh'),
    ('BB', 'Barbados'),
    ('BY', 'Belarus'),
    ('BE', 'Belgium'),
    ('BZ', 'Belize'),
    ('BJ', 'Benin'),
    ('BM', 'Bermuda'),
    ('BT', 'Bhutan'),
    ('BO', 'Bolivia'),
    ('BQ', 'Bonaire'),
    ('BA', 'Bosnia and Herzegovina'),
    ('BW', 'Botswana'),
    ('BV', 'Bouvet Island'),
    ('BR', 'Brazil'),
    ('IO', 'British Indian Ocean Territory'),
    ('BN', 'Brunei Darussalam'),
    ('BG', 'Bulgaria'),
    ('BF', 'Burkina Faso'),
    ('BI', 'Burundi'),
    ('KH', 'Cambodia'),
    ('CM', 'Cameroon'),
    ('CA', 'Canada'),
    ('CV', 'Cape Verde'),
    ('KY', 'Cayman Islands'),
    ('CF', 'Central African Republic'),
    ('TD', 'Chad'),
    ('CL', 'Chile'),
    ('CN', 'China'),
    ('CX', 'Christmas Island'),
    ('CC', 'Cocos (Keeling) Islands'),
    ('CO', 'Colombia'),
    ('KM', 'Comoros'),
    ('CG', 'Congo'),
    ('CD', 'Congo, The Democratic Republic of the'),
    ('CK', 'Cook Islands'),
    ('CR', 'Costa Rica'),
    ('HR', 'Croatia'),
    ('CU', 'Cuba'),
    ('CW', 'Curaçao'),
    ('CY', 'Cyprus'),
    ('CZ', 'Czech Republic'),
    ('CI', 'Côte d’Ivoire'),
    ('DK', 'Denmark'),
    ('DJ', 'Djibouti'),
    ('DM', 'Dominica'),
    ('DO', 'Dominican Republic'),
    ('EC', 'Ecuador'),
    ('EG', 'Egypt'),
    ('SV', 'El Salvador'),
    ('GQ', 'Equatorial Guinea'),
    ('ER', 'Eritrea'),
    ('EE', 'Estonia'),
    ('SZ', 'Eswatini'),
    ('ET', 'Ethiopia'),
    ('FK', 'Falkland Islands (Malvinas)'),
    ('FO', 'Faroe Islands'),
    ('FJ', 'Fiji'),
    ('FI', 'Finland'),
    ('FR', 'France'),
    ('GF', 'French Guiana'),
    ('PF', 'French Polynesia'),
    ('TF', 'French Southern Territories'),
    ('GA', 'Gabon'),
    ('GM', 'Gambia'),
    ('GE', 'Georgia'),
    ('DE', 'Germany'),
    ('GH', 'Ghana'),
    ('GI', 'Gibraltar'),
    ('GR', 'Greece'),
    ('GL', 'Greenland'),
    ('GD', 'Grenada'),
    ('GP', 'Guadeloupe'),
    ('GT', 'Guatemala'),
    ('GG', 'Guernsey'),
    ('GN', 'Guinea'),
    ('GW', 'Guinea-Bissau'),
    ('GY', 'Guyana'),
    ('HT', 'Haiti'),
    ('HM', 'Heard Island and McDonald Islands'),
    ('VA', 'Holy See (Vatican City State)'),
    ('HN', 'Honduras'),
    ('HK', 'Hong Kong'),
    ('HU', 'Hungary'),
    ('IS', 'Iceland'),
    ('IN', 'India'),
    ('ID', 'Indonesia'),
    ('IR', 'Iran, Islamic Republic of'),
    ('IQ', 'Iraq'),
    ('IE', 'Ireland'),
    ('IM', 'Isle of Man'),
    ('IL', 'Israel'),
    ('IT', 'Italy'),
    ('JM', 'Jamaica'),
    ('JP', 'Japan'),
    ('JE', 'Jersey'),
    ('JO', 'Jordan'),
    ('KZ', 'Kazakhstan'),
    ('KE', 'Kenya'),
    ('KI', 'Kiribati'),
    ('KP', 'Korea, Democratic People’s Republic of'),
    ('KR', 'Korea, Republic of'),
    ('XK', 'Kosovo'),
    ('KW', 'Kuwait'),
    ('KG', 'Kyrgyzstan'),
    ('LA', 'Lao People’s Democratic Republic'),
    ('LV', 'Latvia'),
    ('LB', 'Lebanon'),
    ('LS', 'Lesotho'),
    ('LR', 'Liberia'),
    ('LY', 'Libya'),
    ('LI', 'Liechtenstein'),
    ('LT', 'Lithuania'),
    ('LU', 'Luxembourg'),
    ('MO', 'Macao'),
    ('MK', 'North Macedonia'),
    ('MG', 'Madagascar'),
    ('MW', 'Malawi'),
    ('MY', 'Malaysia'),
    ('MV', 'Maldives'),
    ('ML', 'Mali'),
    ('MT', 'Malta'),
    ('MQ', 'Martinique'),
    ('MR', 'Mauritania'),
    ('MU', 'Mauritius'),
    ('YT', 'Mayotte'),
    ('MX', 'Mexico'),
    ('MD', 'Moldova, Republic of'),
    ('MC', 'Monaco'),
    ('MN', 'Mongolia'),
    ('ME', 'Montenegro'),
    ('MS', 'Montserrat'),
    ('MA', 'Morocco'),
    ('MZ', 'Mozambique'),
    ('MM', 'Myanmar'),
    ('NA', 'Namibia'),
    ('NR', 'Nauru'),
    ('NP', 'Nepal'),
    ('NL', 'Netherlands'),
    ('NC', 'New Caledonia'),
    ('NZ', 'New Zealand'),
    ('NI', 'Nicaragua'),
    ('NE', 'Niger'),
    ('NG', 'Nigeria'),
    ('NU', 'Niue'),
    ('NF', 'Norfolk Island'),
    ('NO', 'Norway'),
    ('OM', 'Oman'),
    ('PK', 'Pakistan'),
    ('PS', 'Palestine, State of'),
    ('PA', 'Panama'),
    ('PG', 'Papua New Guinea'),
    ('PY', 'Paraguay'),
    ('PE', 'Peru'),
    ('PH', 'Philippines'),
    ('PN', 'Pitcairn'),
    ('PL', 'Poland'),
    ('PT', 'Portugal'),
    ('PR', 'Puerto Rico'),
    ('QA', 'Qatar'),
    ('SS', 'Republic of South Sudan'),
    ('RO', 'Romania'),
    ('RU', 'Russian Federation'),
    ('RW', 'Rwanda'),
    ('RE', 'Réunion'),
    ('BL', 'Saint Barthélemy'),
    ('SH', 'Saint Helena, Ascension and Tristan da Cunha'),
    ('KN', 'Saint Kitts and Nevis'),
    ('LC', 'Saint Lucia'),
    ('MF', 'Saint Martin (French Part)'),
    ('PM', 'Saint Pierre and Miquelon'),
    ('VC', 'Saint Vincent and the Grenadines'),
    ('WS', 'Samoa'),
    ('SM', 'San Marino'),
    ('ST', 'Sao Tome and Principe'),
    ('SA', 'Saudi Arabia'),
    ('SN', 'Senegal'),
    ('RS', 'Serbia'),
    ('SC', 'Seychelles'),
    ('SL', 'Sierra Leone'),
    ('SG', 'Singapore'),
    ('SX', 'Sint Maarten'),
    ('SK', 'Slovakia'),
    ('SI', 'Slovenia'),
    ('SB', 'Solomon Islands'),
    ('SO', 'Somalia'),
    ('ZA', 'South Africa'),
    ('GS', 'South Georgia and the South Sandwich Islands'),
    ('ES', 'Spain'),
    ('LK', 'Sri Lanka'),
    ('SD', 'Sudan'),
    ('SR', 'Suriname'),
    ('SJ', 'Svalbard and Jan Mayen'),
    ('SE', 'Sweden'),
    ('CH', 'Switzerland'),
    ('SY', 'Syrian Arab Republic'),
    ('TW', 'Taiwan, Province of China'),
    ('TJ', 'Tajikistan'),
    ('TZ', 'Tanzania, United Republic of'),
    ('TH', 'Thailand'),
    ('TL', 'Timor-Leste'),
    ('TG', 'Togo'),
    ('TK', 'Tokelau'),
    ('TO', 'Tonga'),
    ('TT', 'Trinidad and Tobago'),
    ('TN', 'Tunisia'),
    ('TR', 'Turkey'),
    ('TM', 'Turkmenistan'),
    ('TC', 'Turks and Caicos Islands'),
    ('TV', 'Tuvalu'),
    ('UG', 'Uganda'),
    ('UA', 'Ukraine'),
    ('AE', 'United Arab Emirates'),
    ('GB', 'United Kingdom'),
    ('UM', 'United States Minor Outlying Islands'),
    ('UY', 'Uruguay'),
    ('UZ', 'Uzbekistan'),
    ('VU', 'Vanuatu'),
    ('VE', 'Venezuela, Bolivarian Republic of'),
    ('VN', 'Viet Nam'),
    ('VG', 'Virgin Islands, British'),
    ('WF', 'Wallis and Futuna'),
    ('EH', 'Western Sahara'),
    ('YE', 'Yemen'),
    ('ZM', 'Zambia'),
    ('ZW', 'Zimbabwe')
]


COUNTRY_LIST_3_LETTER_CODES = [
    ('USA', 'United States of America'),
    ('AFG', 'Afghanistan'),
    ('ALA', 'Åland Islands'),
    ('ALB', 'Albania'),
    ('DZA', 'Algeria'),
    ('AND', 'Andorra'),
    ('AGO', 'Angola'),
    ('AIA', 'Anguilla'),
    ('ATA', 'Antarctica'),
    ('ATG', 'Antigua and Barbuda'),
    ('ARG', 'Argentina'),
    ('ARM', 'Armenia'),
    ('ABW', 'Aruba'),
    ('AUS', 'Australia'),
    ('AUT', 'Austria'),
    ('AZE', 'Azerbaijan'),
    ('BHS', 'Bahamas'),
    ('BHR', 'Bahrain'),
    ('BGD', 'Bangladesh'),
    ('BRB', 'Barbados'),
    ('BLR', 'Belarus'),
    ('BEL', 'Belgium'),
    ('BLZ', 'Belize'),
    ('BEN', 'Benin'),
    ('BMU', 'Bermuda'),
    ('BTN', 'Bhutan'),
    ('BOL', 'Bolivia'),
    ('BES', 'Bonaire'),
    ('BIH', 'Bosnia and Herzegovina'),
    ('BWA', 'Botswana'),
    ('BVT', 'Bouvet Island'),
    ('BRA', 'Brazil'),
    ('IOT', 'British Indian Ocean Territory'),
    ('BRN', 'Brunei Darussalam'),
    ('BGR', 'Bulgaria'),
    ('BFA', 'Burkina Faso'),
    ('BDI', 'Burundi'),
    ('KHM', 'Cambodia'),
    ('CMR', 'Cameroon'),
    ('CAN', 'Canada'),
    ('CPV', 'Cape Verde'),
    ('CYM', 'Cayman Islands'),
    ('CAF', 'Central African Republic'),
    ('TCD', 'Chad'),
    ('CHL', 'Chile'),
    ('CHN', 'China'),
    ('CXR', 'Christmas Island'),
    ('CCK', 'Cocos (Keeling) Islands'),
    ('COL', 'Colombia'),
    ('COM', 'Comoros'),
    ('COG', 'Congo'),
    ('COD', 'Congo, The Democratic Republic of the'),
    ('COK', 'Cook Islands'),
    ('CRI', 'Costa Rica'),
    ('HRV', 'Croatia'),
    ('CUB', 'Cuba'),
    ('CUW', 'Curaçao'),
    ('CYP', 'Cyprus'),
    ('CZE', 'Czech Republic'),
    ('CIV', 'Côte d’Ivoire'),
    ('DNK', 'Denmark'),
    ('DJI', 'Djibouti'),
    ('DMA', 'Dominica'),
    ('DOM', 'Dominican Republic'),
    ('ECU', 'Ecuador'),
    ('EGY', 'Egypt'),
    ('SLV', 'El Salvador'),
    ('GNQ', 'Equatorial Guinea'),
    ('ERI', 'Eritrea'),
    ('EST', 'Estonia'),
    ('SWZ', 'Eswatini'),
    ('ETH', 'Ethiopia'),
    ('FLK', 'Falkland Islands (Malvinas)'),
    ('FRO', 'Faroe Islands'),
    ('FJI', 'Fiji'),
    ('FIN', 'Finland'),
    ('FRA', 'France'),
    ('GUF', 'French Guiana'),
    ('PYF', 'French Polynesia'),
    ('ATF', 'French Southern Territories'),
    ('GAB', 'Gabon'),
    ('GMB', 'Gambia'),
    ('GEO', 'Georgia'),
    ('DEU', 'Germany'),
    ('GHA', 'Ghana'),
    ('GIB', 'Gibraltar'),
    ('GRC', 'Greece'),
    ('GRL', 'Greenland'),
    ('GRD', 'Grenada'),
    ('GLP', 'Guadeloupe'),
    ('GTM', 'Guatemala'),
    ('GGY', 'Guernsey'),
    ('GIN', 'Guinea'),
    ('GNB', 'Guinea-Bissau'),
    ('GUY', 'Guyana'),
    ('HTI', 'Haiti'),
    ('HMD', 'Heard Island and McDonald Islands'),
    ('VAT', 'Holy See (Vatican City State)'),
    ('HND', 'Honduras'),
    ('HKG', 'Hong Kong'),
    ('HUN', 'Hungary'),
    ('ISL', 'Iceland'),
    ('IND', 'India'),
    ('IDN', 'Indonesia'),
    ('IRN', 'Iran, Islamic Republic of'),
    ('IRQ', 'Iraq'),
    ('IRL', 'Ireland'),
    ('IMN', 'Isle of Man'),
    ('ISR', 'Israel'),
    ('ITA', 'Italy'),
    ('JAM', 'Jamaica'),
    ('JPN', 'Japan'),
    ('JEY', 'Jersey'),
    ('JOR', 'Jordan'),
    ('KAZ', 'Kazakhstan'),
    ('KEN', 'Kenya'),
    ('KIR', 'Kiribati'),
    ('PRK', 'Korea, Democratic People’s Republic of'),
    ('KOR', 'Korea, Republic of'),
    ('XKV', 'Kosovo'),
    ('KWT', 'Kuwait'),
    ('KGZ', 'Kyrgyzstan'),
    ('LAO', 'Lao People’s Democratic Republic'),
    ('LVA', 'Latvia'),
    ('LBN', 'Lebanon'),
    ('LSO', 'Lesotho'),
    ('LBR', 'Liberia'),
    ('LBY', 'Libya'),
    ('LIE', 'Liechtenstein'),
    ('LTU', 'Lithuania'),
    ('LUX', 'Luxembourg'),
    ('MAC', 'Macao'),
    ('MKD', 'North Macedonia'),
    ('MDG', 'Madagascar'),
    ('MWI', 'Malawi'),
    ('MYS', 'Malaysia'),
    ('MDV', 'Maldives'),
    ('MLI', 'Mali'),
    ('MLT', 'Malta'),
    ('MTQ', 'Martinique'),
    ('MRT', 'Mauritania'),
    ('MUS', 'Mauritius'),
    ('MYT', 'Mayotte'),
    ('MEX', 'Mexico'),
    ('MDA', 'Moldova, Republic of'),
    ('MCO', 'Monaco'),
    ('MNG', 'Mongolia'),
    ('MNE', 'Montenegro'),
    ('MSR', 'Montserrat'),
    ('MAR', 'Morocco'),
    ('MOZ', 'Mozambique'),
    ('MMR', 'Myanmar'),
    ('NAM', 'Namibia'),
    ('NRU', 'Nauru'),
    ('NPL', 'Nepal'),
    ('NLD', 'Netherlands'),
    ('NCL', 'New Caledonia'),
    ('NZL', 'New Zealand'),
    ('NIC', 'Nicaragua'),
    ('NER', 'Niger'),
    ('NGA', 'Nigeria'),
    ('NIU', 'Niue'),
    ('NFK', 'Norfolk Island'),
    ('NOR', 'Norway'),
    ('OMN', 'Oman'),
    ('PAK', 'Pakistan'),
    ('PSE', 'Palestine, State of'),
    ('PAN', 'Panama'),
    ('PNG', 'Papua New Guinea'),
    ('PRY', 'Paraguay'),
    ('PER', 'Peru'),
    ('PHL', 'Philippines'),
    ('PCN', 'Pitcairn'),
    ('POL', 'Poland'),
    ('PRT', 'Portugal'),
    ('PRI', 'Puerto Rico'),
    ('QAT', 'Qatar'),
    ('SSD', 'Republic of South Sudan'),
    ('ROU', 'Romania'),
    ('RUS', 'Russian Federation'),
    ('RWA', 'Rwanda'),
    ('REU', 'Réunion'),
    ('BLM', 'Saint Barthélemy'),
    ('SHN', 'Saint Helena, Ascension and Tristan da Cunha'),
    ('KNA', 'Saint Kitts and Nevis'),
    ('LCA', 'Saint Lucia'),
    ('MAF', 'Saint Martin (French Part)'),
    ('SPM', 'Saint Pierre and Miquelon'),
    ('VCT', 'Saint Vincent and the Grenadines'),
    ('WSM', 'Samoa'),
    ('SMR', 'San Marino'),
    ('STP', 'Sao Tome and Principe'),
    ('SAU', 'Saudi Arabia'),
    ('SEN', 'Senegal'),
    ('SRB', 'Serbia'),
    ('SYC', 'Seychelles'),
    ('SLE', 'Sierra Leone'),
    ('SGP', 'Singapore'),
    ('SXM', 'Sint Maarten'),
    ('SVK', 'Slovakia'),
    ('SVN', 'Slovenia'),
    ('SLB', 'Solomon Islands'),
    ('SOM', 'Somalia'),
    ('ZAF', 'South Africa'),
    ('SGS', 'South Georgia and the South Sandwich Islands'),
    ('ESP', 'Spain'),
    ('LKA', 'Sri Lanka'),
    ('SDN', 'Sudan'),
    ('SUR', 'Suriname'),
    ('SJM', 'Svalbard and Jan Mayen'),
    ('SWE', 'Sweden'),
    ('CHE', 'Switzerland'),
    ('SYR', 'Syrian Arab Republic'),
    ('TWN', 'Taiwan, Province of China'),
    ('TJK', 'Tajikistan'),
    ('TZA', 'Tanzania, United Republic of'),
    ('THA', 'Thailand'),
    ('TLS', 'Timor-Leste'),
    ('TGO', 'Togo'),
    ('TKL', 'Tokelau'),
    ('TON', 'Tonga'),
    ('TTO', 'Trinidad and Tobago'),
    ('TUN', 'Tunisia'),
    ('TUR', 'Turkey'),
    ('TKM', 'Turkmenistan'),
    ('TCA', 'Turks and Caicos Islands'),
    ('TUV', 'Tuvalu'),
    ('UGA', 'Uganda'),
    ('UKR', 'Ukraine'),
    ('ARE', 'United Arab Emirates'),
    ('GBR', 'United Kingdom'),
    ('UMI', 'United States Minor Outlying Islands'),
    ('URY', 'Uruguay'),
    ('UZB', 'Uzbekistan'),
    ('VUT', 'Vanuatu'),
    ('VEN', 'Venezuela, Bolivarian Republic of'),
    ('VNM', 'Viet Nam'),
    ('VGB', 'Virgin Islands, British'),
    ('WLF', 'Wallis and Futuna'),
    ('ESH', 'Western Sahara'),
    ('YEM', 'Yemen'),
    ('ZMB', 'Zambia'),
    ('ZWE', 'Zimbabwe')
]

STATE_LIST = (
    ('AL', 'AL'),
    ('AK', 'AK'),
    ('AZ', 'AZ'),
    ('AR', 'AR'),
    ('CA', 'CA'),
    ('CO', 'CO'),
    ('CT', 'CT'),
    ('DC', 'DC'),
    ('DE', 'DE'),
    ('FL', 'FL'),
    ('GA', 'GA'),
    ('HI', 'HI'),
    ('ID', 'ID'),
    ('IL', 'IL'),
    ('IN', 'IN'),
    ('IA', 'IA'),
    ('KS', 'KS'),
    ('KY', 'KY'),
    ('LA', 'LA'),
    ('MD', 'MD'),
    ('MA', 'MA'),
    ('ME', 'ME'),
    ('MI', 'MI'),
    ('MN', 'MN'),
    ('MS', 'MS'),
    ('MO', 'MO'),
    ('MT', 'MT'),
    ('NE', 'NE'),
    ('NV', 'NV'),
    ('NH', 'NH'),
    ('NJ', 'NJ'),
    ('NM', 'NM'),
    ('NY', 'NY'),
    ('NC', 'NC'),
    ('ND', 'ND'),
    ('OH', 'OH'),
    ('OK', 'OK'),
    ('OR', 'OR'),
    ('PA', 'PA'),
    ('RI', 'RI'),
    ('SC', 'SC'),
    ('SD', 'SD'),
    ('TN', 'TN'),
    ('TX', 'TX'),
    ('UT', 'UT'),
    ('VT', 'VT'),
    ('VA', 'VA'),
    ('WA', 'WA'),
    ('WV', 'WV'),
    ('WI', 'WI'),
    ('WY', 'WY'),
)

STUDENT_GRADE_OPTIONS = [
    ('SR', 'Senior'),
    ('JR', 'Junior'),
    ('SO', 'Sophomore'),
    ('FR', 'Freshman')
]

FILE_DELIMITER = [
    ('|', 'Pipe ( | )'),
    ('\t', 'Tab'),
]

STUDENT_GPA_OPTIONS = [
    ('', 'Select'),
    (1, 'Between 3.0 to 4.0 (or equivalent of a B average or above)'),
    (2, 'Between 2.0 and 2.9 (or equivalent of C to B-)'),
    (3, 'Below 2.0 (equivalent of C- or below)')
]

YES_NO_SELECT_OPTIONS = [
    ('', 'Select'),
    ('1', 'Yes'),
    ('2', 'No')
]

YES_NO_OPTIONS = [
    (1, 'Yes'),
    (2, 'No')
]

REGISTRATION_TYPES = [
    ('aspirations', 'Aspirations'),
    ('bridge', 'Bridge'),
    ('concurrent', 'Concurrent'),
    ('other', 'Other')
]

from django.contrib.contenttypes.models import ContentType

def get_foreign_key_references(instance):
    references = []

    try:
        # Get the content type of the instance
        content_type = ContentType.objects.get_for_model(instance)

        # Iterate over all models
        for model in ContentType.objects.all():
            # Get the model class
            model_class = model.model_class()

            # Skip stale ContentTypes whose model no longer exists (e.g. a
            # removed third-party model such as s3_storage_browser.globalpermission).
            # model_class() is None here, and None._meta below would raise an
            # AttributeError that the bare `except` swallows — silently
            # truncating the entire reference scan and blanking the migrate
            # tab's "select items to move" (issue #22).
            if model_class is None:
                continue

            # Check if the model has any foreign keys to the instance's model
            for field in model_class._meta.get_fields():
                if field.is_relation and field.related_model == instance.__class__:
                    # Get the objects that reference the instance
                    related_objects = model_class.objects.filter(**{field.name: instance})
                    for obj in related_objects:
                        references.append((model_class.__name__, obj))
    except:
        ...
        
    return references

def password_reset_email_template():
    from cis.settings.password_reset import password_reset

    config = password_reset.from_db()
    
    if config.get('password_reset_subject'):
        return (
            config.get('password_reset_subject'),
            config.get('password_reset_email'),
        )
    
    return (
        'Not configured correctly',
        'Not configured correctly'
    )

def allowed_to_reset_password(user_roles):
    from cis.settings.password_reset import password_reset

    config = password_reset.from_db()
    roles_allowed_to_reset = config.get('allowed_roles', ['student', 'highschool_admin'])

    if not any( user_role in roles_allowed_to_reset for user_role in user_roles):
        return False
    return True

def send_sms(to, text_body):
    from cis.settings.sms import sms

    sms_settings = sms.from_db()
    if sms_settings.get('is_active', 'No') == 'No':
        return False

    from_phone = sms_settings.get('from_phone')
    sid = getattr(settings, 'TWILIO_SID')
    auth_token = getattr(settings, 'TWILIO_AUTH_TOKEN')

    to = re.sub("[^\\d]", "", str(to))

    if sms_settings.get('footer'):
        text_body += '\r\n' + sms_settings.get('footer')

    if getattr(settings, 'DEBUG', True):
        to = '3153785335'

    try:
        client = Twilio_Client(sid, auth_token)
        message = client.messages.create(
            body=text_body,
            from_=from_phone,
            to=to
        )

        return True
    except Exception as e:
        logger.error(e)
    return False
        
# Start Grades Module
#
# These three helpers used to hold the grade-window logic themselves. That logic now
# lives in ``grades.services.window``; the functions are kept here purely for
# backward compatibility because host apps import them from ``cis.utils``
# (``instructor/views/uploads.py`` and ``instructor/views/dashboard.py``).
# They delegate through ``cis.integrations.grades``, so they degrade safely
# (``''`` / ``False``) when the optional ``grades`` app is not installed.
def grades_page_header_for_instructor():
    """Instructor grades page header. ``''`` when grades is absent."""
    from cis.integrations.grades import page_header_for_instructor

    return page_header_for_instructor()

def can_view_grades():
    """Is the grade viewing window open? ``False`` when grades is absent."""
    from cis.integrations.grades import can_view_grades as _can_view_grades

    return _can_view_grades()

def is_submit_grades_open():
    """Is the grade submission window open? ``False`` when grades is absent."""
    from cis.integrations.grades import is_submit_grades_open as _is_submit_grades_open

    return _is_submit_grades_open()

def upload_to_s3(results, path_prefix='ums/class_import/results'):
    time = datetime.datetime.now().strftime('%m%d%Y')
    path = f'{path_prefix}-{time}.txt'

    media_storage = PrivateMediaStorage()

    media_storage.save(path, ContentFile(results.encode()))
    media_storage.url(path)

def can_edit_highschool(user):
    if user_has_cis_role(user):
        return True

    return True if user.is_superuser else False

def can_edit_campus_registration(user, registration):
    if user.is_superuser:
        return True

    if not user_has_cis_role(user):
        return False

    from cis.campus_gate import can_process_campus
    return can_process_campus(user, registration.class_section.course.campus)

def can_edit_campus_section(user, section):
    if not user_has_cis_role(user):
        return False

    from cis.campus_gate import can_process_campus
    return can_process_campus(user, section.campus)

def get_default_campus(user):
    from cis.models.course import Campus

    if not user_has_cis_role(user):
        return None

    from cis.models.customuser import CustomUser
    record = CustomUser.objects.get(
        pk=user.id
    )
    
    if record.campus:
        return record.campus.get('default_campus')
    campuses = Campus.get_all()
    return str(campuses[0].id) if campuses else None

def getDomain():
    try:
        site = Site.objects.get(
            id=getattr(settings, 'SITE_ID')
        )
    except:
        return 'https://explorec.canusia.com'
    
    domain = str(site.domain)
    if not domain.lower().startswith('https://') and not getattr(settings, 'DEBUG'):
        domain = 'https://' + domain
    return domain

def is_tuition_assistance_open():
    from cis.settings.registrations import registrations

    config = registrations.from_db()

    try:
        start_date = datetime.datetime.strptime(
            config.get('starting_date'),
            '%m/%d/%Y'
        )

        end_date = datetime.datetime.strptime(
            config.get('tuition_assistance_ending_date'),
            '%m/%d/%Y'
        )

        today = datetime.datetime.now()
        if start_date > today:
            return False
        
        if today > end_date:
            return False
        
        return True
    except:
        return False
        
def bill_due_date():
    from cis.settings.registrations import registrations
    config = registrations.from_db()
    try:
        due_date = config.get('tuition_pay_end_date')
        due_date = datetime.datetime.strptime(due_date, '%m/%d/%Y').date()
        
        # remove 1 day from due date
        due_date = due_date - datetime.timedelta(days=1)
        return due_date.strftime('%m/%d/%Y')
    except Exception as e:
        logger.error(e)
        return None
    
def is_student_billpay_open(test_date_time=None):
    
    from datetime import datetime
    if not test_date_time:
        test_date_time = datetime.now()
        
    try:
        key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_cis_registrations"
        setting = Setting.objects.get(key=key)
        try:
            if datetime.strptime(setting.value.get('tuition_pay_end_date'), "%m/%d/%Y") > test_date_time:
                return True
        except:
            return False
        return False
    except Setting.DoesNotExist:
        return False
    
def extract_class_times(meeting_time):
    import time

    if meeting_time == 'TBA':
        return ('', 0, 2359)

    start_time, end_time = meeting_time.split('-')

    start_time = int(time.strftime('%H%M', time.strptime(start_time, '%I:%M %p')))
    end_time = int(time.strftime('%H%M', time.strptime(end_time, '%I:%M %p')))

    return (start_time, end_time)

def format_emplid(id):
    return id.rjust(8, '0')

def student_tuition_assistance_upload_path(instance, filename):
    now = datetime.datetime.now().strftime("%Y/%m")
    return f'student/tuition_assistance_docs/{now}/{instance.id}/{filename}'

def student_supporting_doc_upload_path(instance, filename):
    now = datetime.datetime.now().strftime("%Y/%m")
    return f'student/support_docs/{now}/{instance.id}/{filename}'

def event_file_upload_path(instance, filename):
    now = datetime.datetime.now().strftime("%Y/%m")
    return f'event_file/{now}/{instance.id}/{filename}'

def recommendation_upload_path(instance, filename):
    now = datetime.datetime.now().strftime("%Y/%m")
    return f'rec/{now}/{instance.id}/{filename}'

def teacher_app_upload_path(instance, filename):
    now = datetime.datetime.now().strftime("%Y/%m")
    return f'tapp/{now}/{instance.id}/{filename}'

def student_recommendation_upload_path(instance, filename):
    now = datetime.datetime.now().strftime("%Y/%m")
    return f'student/recommendation/{now}/{instance.id}/{filename}'

def student_notes_media_upload_path(instance, filename):
    now = datetime.datetime.now().strftime("%Y/%m")
    return f'notes/students/{now}/{instance.id}/{filename}'

def teacher_notes_media_upload_path(instance, filename):
    now = datetime.datetime.now().strftime("%Y/%m")
    return f'notes/teachers/{now}/{instance.id}/{filename}'

def syllabus_upload_path(instance, filename):
    now = datetime.datetime.now().strftime("%Y/%m")
    return f'syllabus/{now}/{instance.id}/{filename}'

def course_files_upload_path(instance, filename):
    now = datetime.datetime.now().strftime("%Y/%m")
    return f'course/files/{now}/{instance.id}/{filename}'

def bulk_message_log_upload_path(instance, filename):
    now = datetime.datetime.now().strftime("%Y/%m")
    return f'bulk_message/logs/{now}/{instance.id}/{filename}'

def bulk_message_media_upload_path(instance, filename):
    now = datetime.datetime.now().strftime("%Y/%m")
    return f'bulk_message/media/{now}/{instance.id}/{filename}'

def teacher_files_upload_path(instance, filename):
    now = datetime.datetime.now().strftime("%Y/%m")
    return f'teacher/files/{now}/{instance.id}/{filename}'

def hs_transcript_upload_path(instance, filename):
    now = datetime.datetime.now().strftime("%Y/%m")
    return f'hs_transcript/{now}/{instance.id}/{filename}'

def get_s3_url(file_name):
    try:
        import boto3
        from django.conf import settings
        from urllib.parse import unquote

        client = boto3.client('s3')

        # boto3's generate_presigned_url percent-encodes the key exactly
        # once, so it must be handed a fully-decoded key. The key may
        # arrive raw, once-, or multiply-encoded (e.g. extracted from an
        # already-encoded URL), so decode until it stops changing —
        # otherwise a leftover "%20" gets re-encoded into "%2520".
        while True:
            decoded = unquote(file_name)
            if decoded == file_name:
                break
            file_name = decoded
        
        if getattr(settings, 'DEBUG'):
            client = boto3.client('s3',
                aws_access_key_id=getattr(settings, 'AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=getattr(settings, 'AWS_SECRET_ACCESS_KEY')
            )
 
        bucket_name = getattr(settings, 'AWS_STORAGE_BUCKET_NAME')

        if not file_name.startswith('private/'):
            file_name = 'private/' + file_name
        
        # file_name = 'private/datadump/classes.csv'
        url = client.generate_presigned_url(
            'get_object', 
            Params = { 
                        'Bucket': bucket_name, 
                        'Key': file_name, }, 
            ExpiresIn = 604800
        )        
        return url
    except:
        return None
    
def get_uploaded_file(file_type='class_export'):
    import boto3
    from django.conf import settings

    try:
        s3_session = boto3.Session(
            # aws_access_key_id=getattr(settings, 'AWS_ACCESS_KEY_ID'),
            # aws_secret_access_key=getattr(settings, 'AWS_SECRET_ACCESS_KEY')
        )

        if getattr(settings, 'DEBUG'):
            s3_session = boto3.Session(
                aws_access_key_id=getattr(settings, 'AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=getattr(settings, 'AWS_SECRET_ACCESS_KEY')
            )
 
        s3 = s3_session.resource('s3')
        bucket = s3.Bucket(getattr(settings, 'AWS_STORAGE_BUCKET_NAME'))

        key = 'private/data_dump/classexport.csv'
        if file_type == 'class_export':
            key = 'private/data_dump/classexport.csv'
        elif file_type == 'registration_export':
            key = 'private/data_dump/registrationexport.csv'
        elif file_type == 'student_export':
            key = 'private/data_dump/studentexport.csv'
        else:
            key = f'private/{file_type}'

        content = ''
        for obj in bucket.objects.filter(Prefix=key):
            raw = obj.get()['Body'].read()
            try:
                content = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                # Excel on Windows writes CSVs as cp1252, so a single accented
                # name is enough to break a strict UTF-8 decode. Falling back
                # keeps the accented characters instead of discarding the file.
                content = raw.decode('cp1252', errors='replace')

        if content == '':
            return None

        return content
    except Exception as e:
        print(e)
        return None

def is_valid_address_deprecated(address1, city, state, zipcode, address2=''):
    """
    Uses USPS address validation. Returns a tuple with the following fields
    - status (bool)
    - error_message (string or None)
    - address1 (string, formatted address),
    - city (string, formatted city),
    - state (string, formatted 2 char. state code),
    - zipcode (string, formatted 5 char. zipcode),
    """
    try:
        from usps import USPSApi, Address
        import re
        address1 = re.sub('[^a-zA-Z0-9 -.]+', '', address1)

        address = Address(
            name='',
            address_1=address1,
            city=city,
            state=state,
            zipcode=zipcode
        )

        usps = USPSApi(os.getenv('USPS_API_KEY', '504CANUS0013'), test=False)
        validation = usps.validate_address(address)
        
        if not validation.result['AddressValidateResponse'].get(
                'Address').get('Error', None):
            address1 = validation.result['AddressValidateResponse'].get('Address').get('Address2')
            address2 = validation.result['AddressValidateResponse'].get('Address').get('Address1')
            
            zip4 = ''
            if address2 == '-':
                address2 = ''
                zip4 = validation.result['AddressValidateResponse'].get('Address').get('Zip4', '')
                if not zip4:
                    zip4 = ''
                else:
                    zip4 = '-'+zip4
            return (
                True,
                None,
                address1 + ' ' + address2,
                validation.result['AddressValidateResponse'].get('Address').get('City'),
                validation.result['AddressValidateResponse'].get('Address').get('State'),
                validation.result['AddressValidateResponse'].get('Address').get('Zip5') + zip4
            )
        return (
                False,
                validation.result['AddressValidateResponse'].get('Address').get('Error', '').get('Description', ''),
                validation.result['AddressValidateResponse'].get('Address').get('Address2'),
                validation.result['AddressValidateResponse'].get('Address').get('City'),
                validation.result['AddressValidateResponse'].get('Address').get('State'),
                validation.result['AddressValidateResponse'].get('Address').get('Zip5')
            )
    except Exception as e:
        logger.error(e)
        return (
            True,
            None,
            address1,
            city,
            state,
            zipcode
        )

def is_valid_address(address1, city, state, zipcode, address2=None):
    """
    Uses Smarty address validation. Returns a 9-tuple:
    - status (bool)
    - error_message (string or None)
    These additional fields are populated when the address is valid:
    - address1 (string, formatted address — secondary stripped if present),
    - city (string, formatted city),
    - state (string, formatted 2 char. state code),
    - zipcode (string, formatted 5 char. zipcode),
    - plus4_code
    - county name
    - address2 (string, secondary line e.g. "Apt 1B", or '' if no secondary).

    Smarty's delivery_line_1 normally returns the street + secondary glued
    together. When a secondary is present we split it out so callers with a
    separate address2 field can set both cleanly without the apartment line
    duplicating into address1.
    """
    auth_id = getattr(settings, 'SMARTY_AUTH_ID')
    auth_token = getattr(settings, 'SMARTY_AUTH_TOKEN')

    credentials = StaticCredentials(auth_id, auth_token)
    client = ClientBuilder(credentials).with_licenses(["us-core-cloud"]).build_us_street_api_client()

    lookup = StreetLookup()
    lookup.street = address1
    if address2:
        lookup.street2 = address2
    lookup.city = city
    lookup.state = state
    lookup.zipcode = zipcode
    lookup.match = "strict"

    try:
        client.send_lookup(lookup)
    except exceptions.SmartyException as err:
        logger.error(err)
        return (False, str(err), '', '', '', '', '', '', '')

    result = lookup.result

    if not result:
        return (False, 'Invalid address', '', '', '', '', '', '', '')

    if not result[0].analysis.dpv_match_code or result[0].analysis.dpv_match_code == '':
        return (False, 'Invalid address', '', '', '', '', '', '', '')

    components = result[0].components
    # Build the address2 line from Smarty's secondary components. Either piece
    # may be missing (e.g., "PMB 100" has no designator), so we filter empties.
    secondary_parts = [
        getattr(components, 'secondary_designator', '') or '',
        getattr(components, 'secondary_number', '') or '',
    ]
    address2_out = ' '.join(p for p in secondary_parts if p)

    address1_out = result[0].delivery_line_1 or ''
    # delivery_line_1 normally has the secondary glued onto the street; strip
    # it so callers with a separate address2 field don't double up. Match
    # case-insensitively because Smarty sometimes upper-cases the suffix.
    if address2_out and address1_out.lower().endswith(' ' + address2_out.lower()):
        address1_out = address1_out[: -(len(address2_out) + 1)].rstrip()

    return (
        True,
        '',
        address1_out,
        components.city_name,
        components.state_abbreviation,
        components.zipcode,
        components.plus4_code,
        result[0].metadata.county_name,
        address2_out,
    )

def user_has_faculty_role(user):
    """
    Tests for presence of 'faculty' role for current user.
    Return True if 'applicant' role is present, False otherwise
    """
    if user_has_cis_role(user):
        return True

    if user.is_anonymous:
        return False

    roles = user.get_roles()
    return True if 'faculty' in roles else False

def user_has_applicant_role(user):
    """
    Tests for presence of 'student' role for current user.
    Return True if 'applicant' role is present, False otherwise
    """
    if user_has_cis_role(user):
        return True

    if user.is_anonymous:
        return False

    roles = user.get_roles()
    return True if 'applicant' in roles or 'instructor' in roles else False

def user_has_student_role(user):
    """
    Returns True if current user has a 'student' role. False otherwise
    """
    if user.is_anonymous:
        return False

    roles = user.get_roles()
    return True if 'student' in roles else False

def user_has_tech_center_staff_role(user):
    """
    Returns True if current user has a 'tech_center_staff' role. False otherwise
    """
    if user.is_anonymous:
        return False

    roles = user.get_roles()
    return True if 'tech_center_staff' in roles else False

def user_has_highschool_admin_role(user):
    """
    Returns True if current user has a 'highschool_admin' role. False otherwise
    """
    if user.is_anonymous:
        return False

    roles = user.get_roles()
    return True if 'highschool_admin' in roles else False

def user_has_cis_or_faculty_role(user):
    """
    Returns True if current user has a 'cis' role. False otherwise
    """
    if user.is_anonymous:
        return False

    roles = user.get_roles()
    return True if 'ce' in roles or 'faculty' in roles else False

def user_has_cis_role(user):
    """
    Returns True if current user has a 'cis' role. False otherwise
    """
    if user.is_anonymous:
        return False

    roles = user.get_roles()
    return True if 'ce' in roles else False

def user_has_instructor_role(user):
    """
    Returns True if current user has a 'instructor' role. False otherwise
    """
    if user.is_anonymous:
        return False

    roles = user.get_roles()
    return True if 'instructor' in roles else False

def active_academic_year():
    from cis.settings.registrations import registrations
    from cis.models.term import AcademicYear
    
    try:
        academic_year_id = registrations.from_db().get('academic_year')
        return AcademicYear.objects.get(
            id=academic_year_id
        )
    except:
        return None

def active_term():
    """
    Return a Term queryset for active term, if active term is not set then 
    return the first term
    """
    from cis.models.term import Term
    try:
        key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_cis_registrations"
        setting = Setting.objects.get(key=key)

        term = setting.value.get('active_term')
        try:
            return Term.objects.get(pk=term)
        except Term.DoesNotExist:
            return Term.objects.first()

    except Setting.DoesNotExist:
        return Term.objects.first()

def registration_terms():
    """
    Return a Term queryset for which registration is currently set
    """
    from cis.models.term import Term
    try:
        key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_cis_registrations"
        setting = Setting.objects.get(key=key)

        terms = setting.value.get('registration_terms')
        try:
            return Term.objects.filter(pk__in=terms).all()
        except Term.DoesNotExist:
            return None
    except Setting.DoesNotExist:
        return None

def registration_terms_state():
    """Return ``(state, terms)`` for the configured registration terms.

    ``registration_terms()`` collapses three different situations into one
    empty result: the setting is absent, no terms are selected, or the selected
    term ids no longer resolve. The third is a stale-configuration bug -- the
    setting stores term UUIDs, so terms recreated by a data refresh or a
    re-import leave it pointing at ids that match nothing while the settings
    page still displays a configured-looking value -- and callers that gate on
    "are any terms open?" need to tell it apart from the deliberate states.

    ``state`` is one of:

    ``'unconfigured'``
        No setting row, or no terms selected.
    ``'stale'``
        Terms are selected but none of the stored ids resolve to a Term.
    ``'ok'``
        At least one selected term resolves.

    See ewu#45.
    """
    from cis.models.term import Term

    key = getattr(settings, 'CAMPUS_CODE_PREFIX') + "_cis_registrations"
    try:
        setting = Setting.objects.get(key=key)
    except Setting.DoesNotExist:
        return 'unconfigured', Term.objects.none()

    selected = (setting.value or {}).get('registration_terms') or []
    if not selected:
        return 'unconfigured', Term.objects.none()

    try:
        terms = Term.objects.filter(pk__in=selected)
        if not terms.exists():
            return 'stale', Term.objects.none()
    except (ValueError, ValidationError):
        # Stored ids that are not valid UUIDs cannot match anything, and would
        # otherwise surface as a 500 rather than a configuration problem.
        return 'stale', Term.objects.none()

    return 'ok', terms


def is_student_registration_open(test_date_time=None):
    """
    Returns True if registration today is after registration starting date and
    before registration ending date.

    False otherwise
    """

    from datetime import datetime
    if not test_date_time:
        test_date_time = datetime.now()
        
    try:
        key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_cis_registrations"
        setting = Setting.objects.get(key=key)
        try:
            if datetime.strptime(setting.value.get('starting_date'), "%m/%d/%Y") > test_date_time:
                return False
            if datetime.strptime(setting.value.get('ending_date'), "%m/%d/%Y") < test_date_time:
                return False
        except TypeError:
            return False
        except:
            return False
        return True
    except Setting.DoesNotExist:
        return False


def is_pay_type_review_open(test_date_time=None):
    return is_student_registration_open(test_date_time=test_date_time)

def is_instructor_review_open(test_date_time=None):
    """
    Returns True if registration today is after registration starting date and
    before registration ending date.

    False otherwise
    """
    return True

    from datetime import datetime
    if not test_date_time:
        test_date_time = datetime.now()
        
    try:
        key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_cis_registrations"
        setting = Setting.objects.get(key=key)
        try:
            if datetime.strptime(setting.value.get('starting_date'), "%m/%d/%Y") > test_date_time:
                return False
            
            if datetime.strptime(setting.value.get('instructor_review_ending_date'), "%m/%d/%Y") < test_date_time:
                return False
        except:
            return False
        return True
    except Setting.DoesNotExist:
        return False
    
def get_field(instance, field):
    """
    Access related model fields
    """
    if field == '':
        return None

    field_path = field.split('.')
    attr = instance
    for elem in field_path:
        try:
            attr = getattr(attr, elem)
        except AttributeError:
            return ''
    return attr

import re as _re
from django.utils.html import strip_tags as _strip_tags

_SANITIZE_ANGLE_RE = _re.compile(r'[<>]')


def sanitize_plain_text(value):
    """Return ``value`` with all HTML removed, for plain-text fields that may
    later be rendered with ``|safe`` (e.g. Student.asHTML). ``strip_tags``
    removes tags; the angle-bracket scrub then removes any residual ``<``/``>``
    that strip_tags' lenient parser can leave on malformed input, guaranteeing
    no tag/event-handler can ever form. Non-strings pass through unchanged."""
    if not isinstance(value, str):
        return value
    return _SANITIZE_ANGLE_RE.sub('', _strip_tags(value)).strip()


def model_as_HTML(instance, template, html_type='div'):
    if html_type == 'table':
        result = '<table class="table table-striped">'
        for row in template:
            num_columns = int(12 / len(row))
            result += "<tr>"
            for column in row:
                result += f"<td>"
                label = field = column
                if type(column) == dict:
                    label = column['label']
                    field = column['field']
                
                label = label.replace("_", ' ').upper()
                
                result += "<div class='detail_label'>" + label + "</div>"
                result += "<div class=''>"
                if field != '':
                    result += str(get_field(instance, field))
                result += "</div>"
                result += "</div>"
                result += "</td>"

            result += "</tr>"
        result += "</table>"

    else:
        result = '<div class="details">'
        for row in template:
            num_columns = int(12 / len(row))
            result += "<div class='row p-2'>"
            for column in row:
                result += f"<div class='col-md-{num_columns} mt-2'>"
                label = field = column
                if type(column) == dict:
                    label = column['label']
                    field = column['field']
                
                label = label.replace("_", ' ').upper()
                
                result += "<div class='detail_label'>" + label + "</div>"
                result += "<div class=''>"
                if field != '':
                    result += str(get_field(instance, field))
                result += "</div>"
                result += "</div>"

            result += "</div>"
        result += "</div>"

    return result

def export_to_excel(file_name, records, fields):
    from django.utils.encoding import force_str
    """
    Creates an excel export of file 'filename' with records with key in fields
    """
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{file_name}"'
    writer = csv.writer(response, dialect='excel')

    # Write Header
    writer.writerow(fields.values())

    for record in records:
        row = []
        for key in fields.keys():
            row.append(force_str(get_field(record, key)))
        writer.writerow(row)

    return response

class CIS_student_only(BasePermission):
    def has_permission(self, request, view):
        return user_has_student_role(request.user)

class CIS_user_only(BasePermission):
    def has_permission(self, request, view):
        return user_has_cis_role(request.user)

class FACULTY_user_only(BasePermission):
    def has_permission(self, request, view):
        return user_has_faculty_role(request.user)

class TECHSTAFF_user_only(BasePermission):
    def has_permission(self, request, view):
        return user_has_tech_center_staff_role(request.user)

class HSADMIN_user_only(BasePermission):
    def has_permission(self, request, view):
        return user_has_highschool_admin_role(request.user)

class STUDENT_user_only(BasePermission):
    def has_permission(self, request, view):
        return user_has_student_role(request.user)

class INSTRUCTOR_user_only(BasePermission):
    def has_permission(self, request, view):
        return user_has_instructor_role(request.user)


def validate_sftp_host(host, port=22):
    """
    SSRF guard (PT-45): resolve `host` and reject it if ANY resolved address
    is private, loopback, link-local, reserved, multicast, or unspecified.

    This blocks server-side connection probing of internal/link-local ranges
    (RFC1918 10/8, 172.16/12, 192.168/16; 127.0.0.0/8 loopback; 169.254.0.0/16
    link-local incl. the 169.254.169.254 cloud metadata endpoint; ::1; fc00::/7;
    etc.). Must be called BEFORE any socket/paramiko connection is opened.

    Raises ValueError with a generic, non-leaking message on any rejection
    (blank host, unresolvable host, or a disallowed resolved address). The
    message intentionally does NOT include resolved IPs, banners, or resolver
    internals.
    """
    if not host or not str(host).strip():
        raise ValueError("SFTP host is required.")

    host = str(host).strip()

    try:
        port = int(port or 22)
    except (TypeError, ValueError):
        raise ValueError("SFTP port must be an integer between 1 and 65535.")
    if not (1 <= port <= 65535):
        raise ValueError("SFTP port must be an integer between 1 and 65535.")

    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        # Do not leak resolver internals; treat as not-allowed.
        raise ValueError(f"SFTP host '{host}' could not be resolved.")

    if not infos:
        raise ValueError(f"SFTP host '{host}' could not be resolved.")

    for family, _socktype, _proto, _canonname, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            # A resolved address we cannot parse is not safe to trust.
            raise ValueError(f"SFTP host '{host}' resolved to an unusable address.")

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError(
                f"SFTP host '{host}' is not allowed: it resolves to a "
                f"private, loopback, link-local, or reserved network. "
                f"Use a publicly reachable SFTP server."
            )

    return host


def sftp_connect(host, port=22, username=None, password=None, private_key=None, timeout=15):
    """
    Open and return a (paramiko.SSHClient, paramiko.SFTPClient) pair.

    Caller must close both. If `private_key` is provided it takes precedence
    over `password`. Raises paramiko/socket exceptions on failure.

    SSRF guard (PT-45): the host is resolved and validated via
    validate_sftp_host() before any connection is attempted; a host that
    resolves to a private/loopback/link-local/reserved range raises
    ValueError and no socket is opened.
    """
    import io
    from paramiko import SSHClient, AutoAddPolicy, RSAKey, Ed25519Key, ECDSAKey, DSSKey
    from paramiko.ssh_exception import SSHException

    # SSRF guard: reject internal/link-local/reserved destinations up front.
    validate_sftp_host(host, port)

    pkey = None
    if private_key:
        last_err = None
        for key_cls in (Ed25519Key, RSAKey, ECDSAKey, DSSKey):
            try:
                pkey = key_cls.from_private_key(io.StringIO(private_key))
                break
            except SSHException as exc:
                last_err = exc
                continue
        if pkey is None:
            raise SSHException(
                f"Unable to parse private key (tried Ed25519/RSA/ECDSA/DSS): {last_err}"
            )

    client = SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(AutoAddPolicy())
    client.connect(
        hostname=host,
        port=int(port or 22),
        username=username,
        password=password if pkey is None else None,
        pkey=pkey,
        look_for_keys=False,
        allow_agent=False,
        timeout=timeout,
    )
    return client, client.open_sftp()


def sftp_check_read_write(host, port, username, password, private_key, remote_path):
    """
    Validate SFTP credentials by connecting and writing/reading/deleting a probe
    file in the directory portion of `remote_path`. Raises on failure.
    """
    import posixpath, time
    client, sftp = sftp_connect(host, port, username, password, private_key)
    try:
        directory = posixpath.dirname(remote_path) or '.'
        probe_name = posixpath.join(directory, f'.myce_probe_{int(time.time())}')
        payload = b'myce-probe'
        with sftp.open(probe_name, 'wb') as fh:
            fh.write(payload)
        with sftp.open(probe_name, 'rb') as fh:
            got = fh.read()
        if got != payload:
            raise IOError("SFTP probe read-back mismatch")
        sftp.remove(probe_name)
    finally:
        try:
            sftp.close()
        finally:
            client.close()


def resolve_display_layout(raw, default):
    """Return the parsed `profile_display` layout, or `default` when raw is
    blank, not valid JSON, or not a list. Used by the configurable asHTML
    methods to fall back to the historical hardcoded layout.
    """
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return default
    return parsed if isinstance(parsed, list) else default
