# Do not really on artifacts created by make for all targets.
.PHONY: all venv flake8 unit wca_package wrapper_package clean tests check dist

all: venv check dist

venv:
	@echo Preparing virtual enviornment using pipenv.
	pipenv --version
	env PIPENV_QUIET=true pipenv install --dev

flake8: 
	@echo Checking code quality.
	pipenv run flake8 wca tests example workloads

unit: 
	@echo Running unit tests.
	pipenv run env PYTHONPATH=.:workloads/wrapper pytest --cov-report term-missing --cov=wca tests

junit: 
	@echo Running unit tests.
	pipenv run env PYTHONPATH=.:workloads/wrapper pytest --cov-report term-missing --cov=wca tests --junitxml=unit_results.xml -vvv -s

wca_package:
	@echo Building wca pex file.
	-rm .pex-build/wca*
	-rm dist/wca.pex
	-rm -rf wca.egg-info
	pipenv run env PYTHONPATH=. pex . -v -R component-licenses --cache-dir=.pex-build $(PEX_OPTIONS) -o dist/wca.pex -m wca.main:main
	./dist/wca.pex --version

wrapper_package: 
	@echo Building wrappers pex files.
	-sh -c 'rm -f .pex-build/*wrapper.pex'
	pipenv run pex . -D workloads/wrapper -v -R component-licenses --cache-dir=.pex-build $(PEX_OPTIONS) -o dist/wrapper.pex -m wrapper.wrapper_main
	pipenv run pex . -D workloads/wrapper -v -R component-licenses --cache-dir=.pex-build $(PEX_OPTIONS) -o dist/example_workload_wrapper.pex -m wrapper.parser_example_workload
	pipenv run pex . -D workloads/wrapper -v -R component-licenses --cache-dir=.pex-build $(PEX_OPTIONS) -o dist/specjbb_wrapper.pex -m wrapper.parser_specjbb
	pipenv run pex . -D workloads/wrapper -v -R component-licenses --cache-dir=.pex-build $(PEX_OPTIONS) -o dist/ycsb_wrapper.pex -m wrapper.parser_ycsb
	pipenv run pex . -D workloads/wrapper -v -R component-licenses --cache-dir=.pex-build $(PEX_OPTIONS) -o dist/rpc_perf_wrapper.pex -m wrapper.parser_rpc_perf
	pipenv run pex . -D workloads/wrapper -v -R component-licenses --cache-dir=.pex-build $(PEX_OPTIONS) -o dist/tensorflow_benchmark_training_wrapper.pex -m wrapper.parser_tensorflow_benchmark_training
	pipenv run pex . -D workloads/wrapper -v -R component-licenses --cache-dir=.pex-build $(PEX_OPTIONS) -o dist/tensorflow_benchmark_prediction_wrapper.pex -m wrapper.parser_tensorflow_benchmark_prediction
	pipenv run pex . -D workloads/wrapper -v -R component-licenses --cache-dir=.pex-build $(PEX_OPTIONS) -o dist/mutilate_wrapper.pex -m wrapper.parser_mutilate
	pipenv run pex . -D workloads/wrapper -v -R component-licenses --cache-dir=.pex-build $(PEX_OPTIONS) -o dist/cassandra_stress_wrapper.pex -m wrapper.parser_cassandra_stress
	pipenv run pex . -D workloads/wrapper -v -R component-licenses --cache-dir=.pex-build $(PEX_OPTIONS) -o dist/stress_ng_wrapper.pex -m wrapper.parser_stress_ng
	./dist/wrapper.pex --help >/dev/null

check: flake8 unit

dist: wca_package wrapper_package

clean:
	@echo Cleaning.
	rm -rf .pex-build
	rm -rf wca.egg-info
	rm -rf dist
	pipenv --rm
