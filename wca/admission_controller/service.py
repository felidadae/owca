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

import base64
import copy
from enum import Enum
import logging
from typing import Dict, List

import jsonpatch
from flask import Flask, jsonify, request

from wca.admission_controller.app_data_provider import AppDataProvider

log = logging.getLogger(__name__)


class AnnotatingService:
    def __init__(self, configuration: Dict[str, str]):
        self.data_provider: AppDataProvider = configuration['data_provider']
        self.app = Flask(__name__)
        self.hmem_only_threshold: float = configuration.get('hmem_threshold', 20.0)
        self.dram_only_threshold: float = configuration.get('dram_threshold', 80.0)
        self.monitored_namespaces: List[str] = \
            configuration.get('monitored_namespaces', ['default'])

        @self.app.route("/mutate", methods=["POST"])
        def mutate():
            return self._mutate_pod()

    def _create_patch(self, spec, modified_spec, message='Patching pod'):
        patch = jsonpatch.JsonPatch.from_diff(spec, modified_spec)
        return jsonify(
            {
                "response": {
                    "allowed": True,
                    "status": {"message": message},
                    "patch": base64.b64encode(str(patch).encode()).decode(),
                    "patchtype": "JSONPatch",
                }
            }
        )

    def _get_wss_to_mem_ratio(self, app_name):
        ratio_per_app = self.data_provider.get_wss_to_mem_ratio()
        if app_name in ratio_per_app:
            return str(ratio_per_app[app_name])
        return None

    def _get_wss_to_mem_ratio_annotation(self, wss_to_mem_ratio):
        ratio_key = 'wss-to-mem-ratio'
        if wss_to_mem_ratio:
            return {ratio_key: wss_to_mem_ratio}
        return {}

    def _get_memory_type_annotation(self, wss_to_mem_ratio: float):
        memory_type_key = 'memory-type'
        if wss_to_mem_ratio < self.hmem_only_threshold:
            memory_type = MemoryType.HMEM
        elif wss_to_mem_ratio > self.dram_only_threshold:
            memory_type = MemoryType.DRAM
        else:
            memory_type = '{},{}'.format(MemoryType.HMEM, MemoryType.DRAM)
        return {memory_type_key: memory_type}

    def _mutate_pod(self):
        annotations_key = "annotations"
        spec = request.json["request"]["object"]
        modified_spec = copy.deepcopy(spec)
        annotations = {}

        log.debug("[_mutate_pod] modified_spec={}".format(modified_spec))
        log.debug("[_mutate_pod] request={}".format(request.json["request"]))

        if request.json["request"]["namespace"] not in self.monitored_namespaces:
            return self._create_patch(spec, modified_spec)

        app_name = modified_spec["metadata"]["labels"]["app"]
        ratio = self._get_wss_to_mem_ratio(app_name)
        ratio_annotation = self._get_wss_to_mem_ratio_annotation(ratio)
        annotations.update(ratio_annotation)

        log.debug("Mutating pod of app={} with wss_to_mem_ratio={}".format(app_name, ratio))

        if ratio:
            memory_type_annotation = self._get_memory_type_annotation(float(ratio))
            annotations.update(memory_type_annotation)

        if not modified_spec["metadata"].get(annotations_key) and annotations:
            modified_spec["metadata"].update({annotations_key: {}})
        if annotations:
            modified_spec["metadata"][annotations_key].update(annotations)

        return self._create_patch(spec, modified_spec)


class MemoryType(str, Enum):
    DRAM = 'dram'
    HMEM = 'hmem'
