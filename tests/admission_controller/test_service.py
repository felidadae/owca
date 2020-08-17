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
# limitations under the License
from wca.admission_controller.service import AnnotatingService
from wca.admission_controller.app_data_provider import AppDataProvider
from wca.prometheus import Prometheus
import base64

from unittest.mock import patch
import pytest
import jsonpatch

app_data_provider = AppDataProvider(prometheus=Prometheus('127.0.0.1', 1234))
annotating_service = AnnotatingService(configuration={'data_provider': app_data_provider})


@pytest.mark.parametrize('app_name,ratio_per_app,expected_output', [
    ('workload-1', {'workload-0': 21.3, 'workload-1': 81.76}, '81.76'),
    ('workload-2', {'workload-0': 21.3, 'workload-1': 81.76}, None)
])
def test_get_pmem_ratio(app_name, ratio_per_app, expected_output):
    with patch('wca.admission_controller.service.AppDataProvider.get_wss_to_mem_ratio',
               return_value=ratio_per_app):
        assert annotating_service._get_wss_to_mem_ratio(app_name) == expected_output


@patch('wca.admission_controller.service.AnnotatingService._get_wss_to_mem_ratio',
       return_value='12.3')
def test_mutate(ratio):
    request_json = {'request': {
                      'namespace': 'default',
                      'object': {
                         "apiVersion": "v1",
                         "kind": "Pod",
                         "metadata": {
                             "labels": {
                                 "app": "sysbench-memory-small",
                                 "workload": "sysbench-memory"}}}}}
    spec = request_json['request']['object']
    patched_spec = {"apiVersion": "v1",
                    "kind": "Pod",
                    "metadata": {
                        "labels": {
                            "app": "sysbench-memory-small",
                            "workload": "sysbench-memory"},
                        "annotations": {
                            "wss-to-mem-ratio": "12.3",
                            "memory-type": "hmem"}}}
    patch = jsonpatch.JsonPatch.from_diff(spec, patched_spec)
    with annotating_service.app.test_request_context('mocked_request', json=request_json):
        output = annotating_service._mutate_pod()
        assert output.json == {
                "response": {
                    "allowed": True,
                    "status": {"message": 'Patching pod'},
                    "patch": base64.b64encode(str(patch).encode()).decode(),
                    "patchtype": "JSONPatch",
                }
            }
