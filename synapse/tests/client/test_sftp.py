import logging

import paramiko
import pytest

from synapse.client import sftp


def test_authentication_failure_is_not_logged_before_reraising(monkeypatch, caplog):
    def fail_authentication(self, **kwargs):
        raise paramiko.AuthenticationException("Authentication failed.")

    monkeypatch.setattr(paramiko.SSHClient, "connect", fail_authentication)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(paramiko.AuthenticationException):
            sftp.connect_sftp("192.0.2.1", "user", "bad-password")

    assert caplog.records == []
