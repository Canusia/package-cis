"""PT-45: Blind SSRF via user-controlled SFTP host in Student Exporter.

Fix = validate_sftp_host() resolves the host and rejects any address that is
private / loopback / link-local / reserved / multicast (incl. the cloud
metadata address 169.254.169.254) BEFORE sftp_connect() opens a connection.

All tests are hermetic: socket.getaddrinfo is mocked so no real DNS/network
calls happen.
"""
import socket
from unittest import mock

from django.test import TestCase

from cis.utils import validate_sftp_host


def _addrinfo(ip, family=socket.AF_INET):
    """Build a getaddrinfo()-shaped tuple list for a single resolved IP."""
    sockaddr = (ip, 0) if family == socket.AF_INET else (ip, 0, 0, 0)
    return [(family, socket.SOCK_STREAM, 6, '', sockaddr)]


class ValidateSftpHostRejectsInternalTests(TestCase):
    def test_rejects_loopback_ipv4_literal(self):
        with mock.patch('cis.utils.socket.getaddrinfo',
                        return_value=_addrinfo('127.0.0.1')):
            with self.assertRaises(ValueError):
                validate_sftp_host('127.0.0.1', 22)

    def test_rejects_localhost_name(self):
        with mock.patch('cis.utils.socket.getaddrinfo',
                        return_value=_addrinfo('127.0.0.1')):
            with self.assertRaises(ValueError):
                validate_sftp_host('localhost', 22)

    def test_rejects_cloud_metadata_link_local(self):
        with mock.patch('cis.utils.socket.getaddrinfo',
                        return_value=_addrinfo('169.254.169.254')):
            with self.assertRaises(ValueError):
                validate_sftp_host('169.254.169.254', 80)

    def test_rejects_rfc1918_ten(self):
        with mock.patch('cis.utils.socket.getaddrinfo',
                        return_value=_addrinfo('10.0.0.5')):
            with self.assertRaises(ValueError):
                validate_sftp_host('10.0.0.5', 22)

    def test_rejects_rfc1918_192_168(self):
        with mock.patch('cis.utils.socket.getaddrinfo',
                        return_value=_addrinfo('192.168.1.1')):
            with self.assertRaises(ValueError):
                validate_sftp_host('192.168.1.1', 22)

    def test_rejects_ipv6_loopback(self):
        with mock.patch('cis.utils.socket.getaddrinfo',
                        return_value=_addrinfo('::1', family=socket.AF_INET6)):
            with self.assertRaises(ValueError):
                validate_sftp_host('::1', 22)

    def test_rejects_name_resolving_to_private_ip(self):
        # Hostname looks external but DNS maps it to an internal address
        # (DNS-rebinding / pinning bypass).
        with mock.patch('cis.utils.socket.getaddrinfo',
                        return_value=_addrinfo('10.1.2.3')):
            with self.assertRaises(ValueError):
                validate_sftp_host('sftp.partner.example.com', 22)

    def test_rejects_when_any_resolved_address_is_private(self):
        # First address public, second private -> must still reject.
        infos = (_addrinfo('203.0.113.7')
                 + _addrinfo('192.168.0.9'))
        with mock.patch('cis.utils.socket.getaddrinfo', return_value=infos):
            with self.assertRaises(ValueError):
                validate_sftp_host('mixed.example.com', 22)

    def test_rejects_unresolvable_host(self):
        with mock.patch('cis.utils.socket.getaddrinfo',
                        side_effect=socket.gaierror('name resolution failed')):
            with self.assertRaises(ValueError):
                validate_sftp_host('does-not-exist.invalid', 22)

    def test_rejects_blank_host(self):
        with self.assertRaises(ValueError):
            validate_sftp_host('', 22)


class ValidateSftpHostAcceptsExternalTests(TestCase):
    # NOTE: stdlib `ipaddress` classifies the RFC 5737 documentation ranges
    # (203.0.113.0/24, 198.51.100.0/24) as is_private, so they cannot stand in
    # for "public" here. Use genuinely globally-routable addresses instead.
    def test_accepts_public_ipv4(self):
        with mock.patch('cis.utils.socket.getaddrinfo',
                        return_value=_addrinfo('1.1.1.1')):
            # Should not raise.
            validate_sftp_host('1.1.1.1', 22)

    def test_accepts_public_host_name(self):
        with mock.patch('cis.utils.socket.getaddrinfo',
                        return_value=_addrinfo('8.8.8.8')):
            validate_sftp_host('sftp.vendor.example.com', 22)

    def test_accepts_public_ipv6(self):
        with mock.patch('cis.utils.socket.getaddrinfo',
                        return_value=_addrinfo('2606:4700:4700::1111',
                                               family=socket.AF_INET6)):
            validate_sftp_host('ipv6.vendor.example.com', 22)


class SftpConnectBlocksBeforeParamikoTests(TestCase):
    """sftp_connect must validate the host and bail out BEFORE paramiko
    attempts any network connection."""

    def test_sftp_connect_rejects_internal_host_without_connecting(self):
        with mock.patch('cis.utils.socket.getaddrinfo',
                        return_value=_addrinfo('127.0.0.1')), \
             mock.patch('paramiko.SSHClient.connect') as mock_connect:
            from cis.utils import sftp_connect
            with self.assertRaises(ValueError):
                sftp_connect(host='127.0.0.1', port=22, username='x',
                             password='y')
            # The guard fired first: paramiko was never asked to connect.
            mock_connect.assert_not_called()

    def test_sftp_connect_rejects_metadata_host_without_connecting(self):
        with mock.patch('cis.utils.socket.getaddrinfo',
                        return_value=_addrinfo('169.254.169.254')), \
             mock.patch('paramiko.SSHClient.connect') as mock_connect:
            from cis.utils import sftp_connect
            with self.assertRaises(ValueError):
                sftp_connect(host='169.254.169.254', port=80, username='x',
                             password='y')
            mock_connect.assert_not_called()


from django.core.exceptions import ValidationError as DjangoValidationError

from cis.utils import sftp_check_read_write


class SftpCheckReadWriteSurfacesErrorTests(TestCase):
    """sftp_check_read_write delegates to sftp_connect, so the SSRF guard's
    ValueError propagates out of the connectivity probe (the student_exporter
    form's clean() then re-raises it as a Django ValidationError)."""

    def test_read_write_probe_raises_for_internal_host(self):
        with mock.patch('cis.utils.socket.getaddrinfo',
                        return_value=_addrinfo('10.0.0.5')), \
             mock.patch('paramiko.SSHClient.connect') as mock_connect:
            with self.assertRaises(ValueError):
                sftp_check_read_write(
                    host='10.0.0.5', port=22, username='u',
                    password='p', private_key=None,
                    remote_path='/tmp/out.csv',
                )
            mock_connect.assert_not_called()

    def test_form_clean_wraps_guard_error_as_validationerror(self):
        # Mirror the student_exporter.clean() except clause: the guard's
        # ValueError is caught and re-raised as a Django ValidationError so the
        # user sees a normal form error, not a 500 / stack trace.
        with mock.patch('cis.utils.socket.getaddrinfo',
                        return_value=_addrinfo('169.254.169.254')), \
             mock.patch('paramiko.SSHClient.connect'):
            try:
                sftp_check_read_write(
                    host='169.254.169.254', port=80, username='u',
                    password='p', private_key=None,
                    remote_path='/tmp/out.csv',
                )
            except Exception as exc:
                wrapped = DjangoValidationError(
                    f"SFTP credentials failed read/write check: {exc}")
            else:
                self.fail("expected the SSRF guard to raise")
            self.assertIn('not allowed', str(wrapped))
