from dataclasses import dataclass
from wca.storage import Storage
import logging
import requests

log = logging.getLogger(__name__)


@dataclass
class HTTPStorage(Storage):

    http_endpoint: str = 'http://127.0.0.1:8000'

    def store(self, metrics):
        log.info('sending!')
        try:
            requests.post(
                self.http_endpoint,
                json={metric.name: metric.value for metric in metrics},
                timeout=1
            )
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
            log.warning('timeout!')
