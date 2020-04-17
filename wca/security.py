# Copyright (c) 2018 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import ctypes
import logging
import os
import socket
import ssl
from kazoo.handlers.threading import SequentialThreadingHandler
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
from dataclasses import dataclass
from typing import Optional, Union
from wca import logger
from wca.config import ValidationError, Path
from wca.security_kazoo import create_tcp_connection


LIBC = ctypes.CDLL('libc.so.6', use_errno=True)

log = logging.getLogger(__name__)

# See http://man7.org/linux/man-pages/man2/perf_event_open.2.html for details on the file and values
PARANOID_FILE = '/proc/sys/kernel/perf_event_paranoid'
ALLOW_CPU_EVENTS = 0

# The constant and enums needs to be redefined in Python as ctypes does not allow to access them
# as they are precompiler macros.
# Value: https://elixir.bootlin.com/linux/v3.10.108/source/include/uapi/linux/capability.h#L104
CAP_DAC_OVERRIDE = 2
# Value: https://elixir.bootlin.com/linux/v3.10.108/source/include/uapi/linux/capability.h#L142
CAP_SETUID = 128

# Value: https://elixir.bootlin.com/linux/v3.10.108/source/include/uapi/linux/prctl.h#L78
PR_GET_SECUREBITS = 27

# Value: https://elixir.bootlin.com/linux/v3.10.108/source/include/uapi/linux/securebits.h#L31
# https://elixir.bootlin.com/linux/v3.10.108/source/include/uapi/linux/securebits.h#L8
SECBIT_NO_SETUID_FIXUP = 4

# Version 3 does not seem to work and version 2 is deprecated.
# See: http://man7.org/linux/man-pages/man2/capget.2.html#DESCRIPTION
LINUX_CAPABILITY_VERSION_1 = 0x19980330

GLOBAL_ROOT_UID = 0

HTTP_RESPONSE_MAX_SIZE = 1024


# We need a class that can be mapped to __user_cap_header_struct.
# See: http://man7.org/linux/man-pages/man2/capget.2.html#DESCRIPTION
class UserCapHeaderStruct(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]


# We need a class that can be mapped to __user_cap_data_struct.
# See: http://man7.org/linux/man-pages/man2/capget.2.html#DESCRIPTION
class UserCapDataStruct(ctypes.Structure):
    _fields_ = [
        ("effective", ctypes.c_uint32),
        ("permitted", ctypes.c_uint32),
        ("inheritable", ctypes.c_uint32),
    ]


class GettingCapabilitiesFailed(Exception):
    pass


def are_privileges_sufficient(
        write_to_cgroup: bool = True, use_resctrl: bool = False, use_perf: bool = False) -> bool:
    """Check if user have sufficient privilages to collect specific metrics types."""

    if not (write_to_cgroup or use_resctrl or use_perf):
        return True

    uid = os.geteuid()

    # Root can do everything.
    if uid == GLOBAL_ROOT_UID:
        return True

    capabilities = _get_capabilities()

    log.debug("Process capabilities: effective - {}, permitted - {}, inheritable - {}"
              .format(capabilities.effective, capabilities.permitted, capabilities.inheritable))

    are_sufficient_privileges = True
    error_log_message = ""

    if write_to_cgroup:
        has_cap_dac_override = capabilities.effective & CAP_DAC_OVERRIDE == CAP_DAC_OVERRIDE
        if not has_cap_dac_override:
            error_log_message += " CAP_DAC_OVERRIDE set."
            are_sufficient_privileges = False

    if use_resctrl:
        secure_bits = _get_securebits()
        has_cap_setuid = capabilities.effective & CAP_SETUID == CAP_SETUID
        has_secbit_no_setuid_fixup = secure_bits & SECBIT_NO_SETUID_FIXUP
        if not has_cap_setuid or not has_secbit_no_setuid_fixup:
            error_log_message += " CAP_SETUID and SECBIT_NO_SETUID_FIXUP set."
            are_sufficient_privileges = False

    if use_perf:
        paranoid = _read_paranoid()
        if not (paranoid <= ALLOW_CPU_EVENTS):
            error_log_message += ' "/proc/sys/kernel/perf_event_paranoid" set to (0 or -1).'
            are_sufficient_privileges = False

    if are_sufficient_privileges is not True:
        log.error("Insufficient privileges! For unprivileged "
                  "user it is needed to have:" + error_log_message)

    return are_sufficient_privileges


def _get_securebits():
    secure_bits = LIBC.prctl(PR_GET_SECUREBITS)
    return secure_bits


def _get_capabilities():
    header = UserCapHeaderStruct()
    header.pid = os.getpid()
    header.version = LINUX_CAPABILITY_VERSION_1
    data = UserCapDataStruct()
    err = LIBC.capget(ctypes.byref(header), ctypes.byref(data))
    if err != 0:
        raise GettingCapabilitiesFailed("Unable to get capabilities of {}".format(os.getpid()))
    return data


def _read_paranoid() -> int:
    with open(PARANOID_FILE, 'r') as f:
        return int(f.read())


# Won't run if `SECBIT_NO_SETUID_FIXUP` is not set.
class SetEffectiveRootUid:
    def __enter__(self):
        self.uid = os.geteuid()
        if self.uid != 0:
            os.seteuid(0)
            log.log(logger.TRACE, "Effective user id from {} to 0".format(self.uid))

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            log.warning("Exception {} with message {} thrown".format(exc_type, exc_val))
        if self.uid != 0:
            os.seteuid(self.uid)
            log.log(logger.TRACE, "Effective user id from 0 to {}".format(self.uid))
            self.uid = 0


@dataclass
class SSL:
    """rst

    Common configuration for SSL communication.

    - ``server_verify``: **Union[bool, Path(absolute=True, mode=os.R_OK)]** = *True*
    - ``client_cert_path``: **Optional[Path(absolute=True, mode=os.R_OK)]** = *None*
    - ``client_key_path``: **Optional[Path(absolute=True, mode=os.R_OK)]** = *None*

    """
    server_verify: Union[bool, Path(absolute=True, mode=os.R_OK)] = True
    client_cert_path: Optional[Path(absolute=True, mode=os.R_OK)] = None
    client_key_path: Optional[Path(absolute=True, mode=os.R_OK)] = None

    def __post_init__(self):
        if self.client_key_path and not self.client_cert_path:
            # There is only client key path, that is wrong, throw error.
            raise ValidationError(
                    'Provided client key without certificate!')

    def get_client_certs(self):
        """Return client cert and key path.
        """
        if self.client_cert_path and self.client_key_path:
            # Both are provided, so return tuple.
            return (self.client_cert_path, self.client_key_path)

        # Otherwise return None or path to .pem file which consists client cert and key.
        return self.client_cert_path


SECURE_CIPHERS = ':'.join([
    #   Commented algorithms are not supported in Centos7
    'ECDHE-ECDSA-AES128-GCM-SHA256',
    'ECDHE-RSA-AES128-GCM-SHA256',
    'DHE-RSA-AES128-GCM-SHA256',
    #   'ECDHE-ECDSA-AES128-CCM',
    'ECDHE-ECDSA-AES128-SHA256',
    'ECDHE-RSA-AES128-SHA256',
    #   'ECDHE-ECDSA-AES256-CCM',
    #   'DHE-RSA-AES128-CCM',
    'DHE-RSA-AES128-SHA256',
    #   'DHE-RSA-AES256-CCM',
    'DHE-RSA-AES256-SHA256',
    'DHE-DSS-AES128-GCM-SHA256',
    'DHE-DSS-AES128-SHA256',
    'DHE-DSS-AES256-SHA256',
    #   '@SECLEVEL=2',
    ])

# Disable unsecure protocols.
SECURE_OPTIONS = 0
SECURE_OPTIONS |= ssl.OP_NO_SSLv2
SECURE_OPTIONS |= ssl.OP_NO_SSLv3
SECURE_OPTIONS |= ssl.OP_NO_TLSv1
SECURE_OPTIONS |= ssl.OP_NO_TLSv1_1
SECURE_OPTIONS |= ssl.OP_NO_COMPRESSION


class HTTPSAdapter(HTTPAdapter):
    """The HTTPs Adapter for urllib3. Provides better security.
    """
    def init_poolmanager(self, *args, **kwargs):
        ssl_context = create_urllib3_context(options=SECURE_OPTIONS, ciphers=SECURE_CIPHERS)
        kwargs['ssl_context'] = ssl_context
        return super(HTTPSAdapter, self).init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        ssl_context = create_urllib3_context(options=SECURE_OPTIONS, ciphers=SECURE_CIPHERS)
        kwargs['ssl_context'] = ssl_context
        return super(HTTPSAdapter, self).proxy_manager_for(*args, **kwargs)


class SecureSequentialThreadingHandler(SequentialThreadingHandler):
    def create_connection(self, *args, **kwargs):
        return create_tcp_connection(socket, options=SECURE_OPTIONS, ciphers=SECURE_CIPHERS,
                                     *args, **kwargs)
