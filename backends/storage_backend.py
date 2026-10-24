# storage backend

from storages.backends.s3boto3 import S3Boto3Storage


class StaticStorage(S3Boto3Storage):
    location = 'static'
    default_acl = 'public-read'

class PublicMediaStorage(S3Boto3Storage):
    location = 'media'
    default_acl = 'public-read'
    file_overwrite = False

class PrivateMediaStorage(S3Boto3Storage):
    location = 'private'
    default_acl = 'private'
    file_overwrite = False
    custom_domain = False

class StudentExportStorage(S3Boto3Storage):
    """The student export's S3 destination (#114 item 5): writes at the exact
    configured key (no location prefix) and overwrites a file of the same
    name, so the SIS always picks up the latest export."""
    location = ''
    default_acl = 'private'
    file_overwrite = True
    custom_domain = False
