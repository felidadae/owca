# Copyright (c) 2020 Intel Corporation
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

import ssl
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from multiprocessing import Process

import pytest
import requests

from wca.security import HTTPSAdapter

pytestmark = [pytest.mark.long, pytest.mark.ssl]


class HTTPRequestHandlerForTest(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Passed')


def run_simple_https_server(ssl_context: ssl.SSLContext):
    server = HTTPServer(('127.0.0.1', 8080), HTTPRequestHandlerForTest)

    server.socket = ssl_context.wrap_socket(server.socket, server_side=True)

    server.serve_forever()


def test_good_certificate():
    # Disable due to https://github.com/urllib3/urllib3/issues/497
    requests.packages.urllib3.disable_warnings(
        requests.packages.urllib3.exceptions.SubjectAltNameWarning)

    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
    ssl_context.load_cert_chain('tests/ssl/goodkey.crt', 'tests/ssl/goodkey.key')
    server = Process(target=run_simple_https_server, args=(ssl_context,))
    server.start()
    time.sleep(0.5)
    try:
        s = requests.Session()
        s.mount('https://localhost:8080/', HTTPSAdapter())
        r = s.get('https://localhost:8080/', verify='tests/ssl/rootCA.crt')
        assert r.text == 'Passed'
        server.terminate()
    except Exception:
        server.terminate()
        raise


def test_wrong_certificate():
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
    ssl_context.load_cert_chain('tests/ssl/goodkey.crt', 'tests/ssl/goodkey.key')
    server = Process(target=run_simple_https_server, args=(ssl_context,))
    server.start()
    time.sleep(0.5)
    with pytest.raises(requests.exceptions.SSLError):
        s = requests.Session()
        try:
            s.mount('https://localhost:8080/', HTTPSAdapter())
            s.get('https://localhost:8080/', verify='tests/ssl/wrongRootCA.crt')
            server.terminate()
        except Exception:
            server.terminate()
            raise


def test_unsupported_rsa_1024():
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
    ssl_context.load_cert_chain('tests/ssl/rsa1024.crt', 'tests/ssl/rsa1024.key')
    server = Process(target=run_simple_https_server, args=(ssl_context,))
    server.start()
    time.sleep(0.5)
    with pytest.raises(requests.exceptions.SSLError):
        s = requests.Session()
        try:
            s.mount('https://localhost:8080/', HTTPSAdapter())
            s.get('https://localhost:8080/', verify='tests/ssl/rootCA.crt')
            server.terminate()
        except Exception:
            server.terminate()
            raise


def test_supported_rsa_2048():
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
    ssl_context.load_cert_chain('tests/ssl/rsa2048.crt', 'tests/ssl/rsa2048.key')
    server = Process(target=run_simple_https_server, args=(ssl_context,))
    server.start()
    time.sleep(0.5)
    with pytest.raises(requests.exceptions.SSLError):
        s = requests.Session()
        try:
            s.mount('https://localhost:8080/', HTTPSAdapter())
            s.get('https://localhost:8080/', verify='tests/ssl/rootCA.crt')
            server.terminate()
        except Exception:
            server.terminate()
            raise


def test_supported_tls_1_2():
    # Disable for older openssl versions.
    requests.packages.urllib3.disable_warnings(
        requests.packages.urllib3.exceptions.SubjectAltNameWarning)

    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
    ssl_context.load_cert_chain('tests/ssl/goodkey.crt', 'tests/ssl/goodkey.key')
    server = Process(target=run_simple_https_server, args=(ssl_context,))
    server.start()
    time.sleep(0.5)
    try:
        s = requests.Session()
        s.mount('https://localhost:8080/', HTTPSAdapter())
        r = s.get('https://localhost:8080/', verify='tests/ssl/rootCA.crt')
        assert r.text == 'Passed'
        server.terminate()
    except Exception:
        server.terminate()
        raise


def test_unsupported_tls_1_1():
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_1)
    ssl_context.load_cert_chain('tests/ssl/goodkey.crt', 'tests/ssl/goodkey.key')
    server = Process(target=run_simple_https_server, args=(ssl_context,))
    server.start()
    time.sleep(0.5)
    with pytest.raises(requests.exceptions.SSLError):
        s = requests.Session()
        try:
            s.mount('https://localhost:8080/', HTTPSAdapter())
            s.get('https://localhost:8080/', verify='tests/ssl/rootCA.crt')
            server.terminate()
        except Exception:
            server.terminate()
            raise


def test_unsupported_tls_1_0():
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1)
    ssl_context.load_cert_chain('tests/ssl/goodkey.crt', 'tests/ssl/goodkey.key')
    server = Process(target=run_simple_https_server, args=(ssl_context,))
    server.start()
    time.sleep(0.5)
    with pytest.raises(requests.exceptions.SSLError):
        s = requests.Session()
        try:
            s.mount('https://localhost:8080/', HTTPSAdapter())
            s.get('https://localhost:8080/', verify='tests/ssl/rootCA.crt')
            server.terminate()
        except Exception:
            server.terminate()
            raise
