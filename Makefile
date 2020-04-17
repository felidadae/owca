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

# Shell variables which may customize behaviour of this Makefiles:
# 
# * ADDITIONAL_PEX_OPTIONS
# 	additional flags which can be passed to pex tool to be used while building distribution files
#
# * OPTIONAL_FEATURES
# 	space seperated list of optional features to be included in the build of pex files;
# 	optional features list:
# 	* kafka_storage


# For cache-dir $PWD is required, becuase pex 2.0.3 have some issues with relative directories.

SHELL := /bin/bash

PEX_OPTIONS = -v -R component-licenses --cache-dir=${PWD}/.pex-build $(ADDITIONAL_PEX_OPTIONS)
OPTIONAL_MODULES =
ifeq ($(OPTIONAL_FEATURES),kafka_storage) 
	OPTIONAL_MODULES = './confluent-kafka-python'
endif

define execute_in_venv
	source env/bin/activate && $(1) && deactivate
endef


# Do not really on artifacts created by make for all targets.
.PHONY: all venv flake8 unit wca_package bandit_pex wrapper_package clean tests check dist

all: venv check dist generate_docs

venv:
	@echo Preparing virtual enviornment.
	python3.6 -m venv env
	$(call execute_in_venv, pip install -r requirements.txt)

flake8:
	@echo Checking code quality.
	$(call execute_in_venv, flake8 wca tests examples)

check_outdated:
	@echo Checking out of date dependencies.
	$(call execute_in_venv, pip list --outdated | tee /dev/stderr | if [[ $$(wc -l) != 0 ]]; then echo "WARNING! Some of packageges are outdated. Consider updating the dependencies."; fi)

unit:
	@echo "Running unit tests (not ssl and not long)."
	$(call execute_in_venv, env PYTHONPATH=.:examples/workloads/wrapper pytest --cov-report term-missing --cov=wca tests --ignore=tests/e2e/test_wca_metrics.py -m "not long and not ssl")

unit_not_long:
	@echo "Running unit tests (not long)."
	$(call execute_in_venv, env PYTHONPATH=.:examples/workloads/wrapper pytest --cov-report term-missing --cov=wca tests --ignore=tests/e2e/test_wca_metrics.py -m "not long")

unit_all:
	@echo "Running unit tests (all)."
	$(call execute_in_venv, env PYTHONPATH=.:examples/workloads/wrapper pytest --cov-report term-missing --cov=wca tests --ignore=tests/e2e/test_wca_metrics.py)

junit:
	@echo "Running unit tests."
	$(call execute_in_venv, env PYTHONPATH=.:examples/workloads/wrapper pytest --cov-report term-missing --cov=wca tests --junitxml=unit_results.xml -vvv -s --ignore=tests/e2e/test_wca_metrics.py)

wca_package_in_docker: DOCKER_OPTIONS ?=
wca_package_in_docker: WCA_IMAGE ?= wca
wca_package_in_docker: WCA_TAG ?= $(shell git rev-parse HEAD)
wca_package_in_docker:
	@echo Building wca pex file inside docker and copying to ./dist/wca.pex
	# target: standalone
	sudo docker build --build-arg MAKE_WCA_PACKAGE=yes $(DOCKER_OPTIONS) --network host --target standalone -f Dockerfile -t $(WCA_IMAGE):$(WCA_TAG) .
	# Extract pex to dist folder
	rm -rf .cidfile && sudo docker create --cidfile=.cidfile $(WCA_IMAGE):$(WCA_TAG)
	CID=$$(cat .cidfile); \
	mkdir -p dist; \
	sudo docker cp $$CID:/usr/bin/wca.pex dist/ && \
	sudo docker rm $$CID && \
	sudo chown -R $$USER:$$USER dist/wca.pex && sudo rm .cidfile
	@echo WCA image name is: $(WCA_IMAGE):$(WCA_TAG)
	@echo WCA pex file: dist/wca.pex

wca_package_in_docker_with_kafka: WCA_IMAGE ?= wca
wca_package_in_docker_with_kafka: WCA_TAG ?= $(shell git rev-parse HEAD)
wca_package_in_docker_with_kafka:
	@echo "Building wca pex (version with Kafka) file inside docker and copying to ./dist/wca.pex"
	sudo docker build --network host -f Dockerfile.kafka -t $(WCA_IMAGE):$(WCA_TAG) .
	rm -rf .cidfile && sudo docker create --cidfile=.cidfile $(WCA_IMAGE):$(WCA_TAG)
	CID=$$(cat .cidfile); \
	mkdir -p dist; \
	sudo docker cp $$CID:/wca/dist/wca.pex dist/ && \
	sudo docker rm $$CID && \
	sudo chown -R $$USER:$$USER dist/wca.pex && sudo rm .cidfile
	@echo WCA image name is: $(WCA_IMAGE):$(WCA_TAG)
	@echo WCA pex file: dist/wca.pex
	# ---
	@echo "Please follow docs/kafka_storage.rst to be able to use created wca.pex"

wca_package:
	@echo Building wca pex file.
	-rm -f .pex-build/wca*
	-rm -rf .pex-build
	-rm -f dist/wca.pex
	-rm -rf wca.egg-info
	$(call execute_in_venv, pex . $(OPTIONAL_MODULES) $(PEX_OPTIONS) -o dist/wca.pex -m wca.main:main)
	./dist/wca.pex --version

wrapper_package_in_docker_with_kafka: WCA_IMAGE ?= wca
wrapper_package_in_docker_with_kafka: WCA_TAG ?= $(shell git rev-parse HEAD)
wrapper_package_in_docker_with_kafka:
	@echo "Building wrappers pex (versions with Kafka) file inside docker and copying to ./dist/"
	sudo docker build --build-arg MAKE_WRAPPER_PACKAGE=yes --network host -f Dockerfile.kafka -t $(WCA_IMAGE):$(WCA_TAG) .
	# Extract pex to dist folder
	rm -rf .cidfile && sudo docker create --cidfile=.cidfile $(WCA_IMAGE):$(WCA_TAG)
	CID=$$(cat .cidfile); \
	mkdir -p dist; \
	sudo docker cp $$CID:/wca/dist/. dist/ && \
	sudo docker rm $$CID && \
	sudo chown -R $$USER:$$USER dist/*.pex && sudo rm .cidfile
	@echo WCA image name is: $(WCA_IMAGE):$(WCA_TAG)
	@echo WCA pex file: dist/wca.pex
	# ---
	@echo "Please follow docs/kafka_storage.rst to be able to use created pex files."

wrapper_package:
	@echo "Building wrappers pex files."
	-sh -c 'rm -f .pex-build/*wrapper.pex'
	-rm -rf .pex-build

	$(call execute_in_venv, \
    pex . $(OPTIONAL_MODULES) -D examples/workloads/wrapper $(PEX_OPTIONS) -o dist/wrapper.pex -m wrapper.wrapper_main && \
	pex . $(OPTIONAL_MODULES) -D examples/workloads/wrapper $(PEX_OPTIONS) -o dist/example_workload_wrapper.pex -m wrapper.parser_example_workload && \
	pex . $(OPTIONAL_MODULES) -D examples/workloads/wrapper $(PEX_OPTIONS) -o dist/specjbb_wrapper.pex -m wrapper.parser_specjbb && \
	pex . $(OPTIONAL_MODULES) -D examples/workloads/wrapper $(PEX_OPTIONS) -o dist/ycsb_wrapper.pex -m wrapper.parser_ycsb && \
	pex . $(OPTIONAL_MODULES) -D examples/workloads/wrapper $(PEX_OPTIONS) -o dist/rpc_perf_wrapper.pex -m wrapper.parser_rpc_perf && \
	pex . $(OPTIONAL_MODULES) -D examples/workloads/wrapper $(PEX_OPTIONS) -o dist/mutilate_wrapper.pex -m wrapper.parser_mutilate && \
	pex . $(OPTIONAL_MODULES) -D examples/workloads/wrapper $(PEX_OPTIONS) -o dist/cassandra_stress_wrapper.pex -m wrapper.parser_cassandra_stress && \
	pex . $(OPTIONAL_MODULES) -D examples/workloads/wrapper $(PEX_OPTIONS) -o dist/stress_ng_wrapper.pex -m wrapper.parser_stress_ng && \
	pex . $(OPTIONAL_MODULES) -D examples/workloads/wrapper $(PEX_OPTIONS) -o dist/memtier_benchmark_wrapper.pex -m wrapper.parser_memtier && \
	pex . $(OPTIONAL_MODULES) -D examples/workloads/wrapper $(PEX_OPTIONS) -o dist/mysql_tpm_gauge_wrapper.pex -m wrapper.parser_mysql_tpm_gauge && \
	./dist/wrapper.pex --help >/dev/null)

#-----------------------------------------------------------------------------------------------
# Private or deprecated

# Do not build pex file, just copy python source and install dependencies into docker container.
_wca_docker_devel: WCA_IMAGE ?= wca
_wca_docker_devel: WCA_TAG ?= devel
_wca_docker_devel:
	@echo "Preparing development WCA container (only source code without pex)"
	sudo docker build --network host --target devel -f Dockerfile -t $(WCA_IMAGE):$(WCA_TAG) .
	@echo WCA image name is: $(WCA_IMAGE):$(WCA_TAG)
	@echo Push: sudo docker push $(WCA_IMAGE):$(WCA_TAG)
	@echo Run: sudo docker run --privileged -ti --rm $(WCA_IMAGE):$(WCA_TAG) -0 -c /wca/configs/extra/static_measurements.yaml


ENV_UNSAFE = env PYTHONPATH=. INCLUDE_UNSAFE_CONFLUENT_KAFKA_WHEEL=yes
_unsafe_wrapper_package:
	@echo Building wrappers pex files. Unsafe method, do not use in production environment.
	-sh -c 'rm -f .pex-build/*wrapper.pex'
	-rm -rf .pex-build

	$(call execute_in_venv, \
	$(ENV_UNSAFE) pex . -D examples/workloads/wrapper $(PEX_OPTIONS) -o dist/wrapper.pex -m wrapper.wrapper_main && \
	$(ENV_UNSAFE) pex . -D examples/workloads/wrapper $(PEX_OPTIONS) -o dist/example_workload_wrapper.pex -m wrapper.parser_example_workload && \
	$(ENV_UNSAFE) pex . -D examples/workloads/wrapper $(PEX_OPTIONS) -o dist/specjbb_wrapper.pex -m wrapper.parser_specjbb && \
	$(ENV_UNSAFE) pex . -D examples/workloads/wrapper $(PEX_OPTIONS) -o dist/ycsb_wrapper.pex -m wrapper.parser_ycsb && \
	$(ENV_UNSAFE) pex . -D examples/workloads/wrapper $(PEX_OPTIONS) -o dist/rpc_perf_wrapper.pex -m wrapper.parser_rpc_perf && \
	$(ENV_UNSAFE) pex . -D examples/workloads/wrapper $(PEX_OPTIONS) -o dist/mutilate_wrapper.pex -m wrapper.parser_mutilate && \
	$(ENV_UNSAFE) pex . -D examples/workloads/wrapper $(PEX_OPTIONS) -o dist/cassandra_stress_wrapper.pex -m wrapper.parser_cassandra_stress && \
	$(ENV_UNSAFE) pex . -D examples/workloads/wrapper $(PEX_OPTIONS) -o dist/stress_ng_wrapper.pex -m wrapper.parser_stress_ng && \
	$(ENV_UNSAFE) pex . -D examples/workloads/wrapper $(PEX_OPTIONS) -o dist/memtier_benchmark_wrapper.pex -m wrapper.parser_memtier && \
	./dist/wrapper.pex --help >/dev/null)
#-----------------------------------------------------------------------------------------------

check: flake8 unit check_outdated

dist: wca_package wrapper_package

clean:
	@echo Cleaning.
	rm -rf .pex-build
	rm -rf wca.egg-info
	rm -rf dist
	python3.6 -m venv env --clear

tester:
	@echo Integration tests.
	sh -c 'sudo chmod 700 $$(pwd)/tests/tester/configs/tester_example.yaml'
	sh -c 'sudo PEX_INHERIT_PATH=fallback PYTHONPATH="$$(pwd):$$(pwd)/tests/tester" dist/wca.pex -c $$(pwd)/tests/tester/configs/tester_example.yaml -r tester:IntegrationTester -r tester:MetricCheck -r tester:FileCheck --log=debug --root'

generate_docs:
	@echo Generate documentation.
	$(call execute_in_venv, env PYTHONPATH=. python util/docs.py)
