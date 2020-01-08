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

#### Multistage Dockerfile
# to build wca in three flavors:
# 1. devel: development version (without verision)
# 2. pex: pex based Dockerfile that includes version number based on .git repo
# 3. standalone: empty image with just and not any development tools

## Testing
# 1. Build
# docker build -t wca:latest .

# 2. Run
# sudo docker run -it --privileged --rm wca -c /wca/configs/extra/static_measurements.yaml -0
# should output some metrics

# ------------------------ devel ----------------------
FROM centos:7 AS devel

RUN yum -y update && yum -y install python36 python-pip which make git
RUN pip3.6 install pipenv

# 2LM binries for topology discovery (WIP) -- TO BE REMOVED FROM master/1.0.x
RUN yum install -y wget lshw
RUN (cd /etc/yum.repos.d/; \
        wget https://copr.fedorainfracloud.org/coprs/jhli/ipmctl/repo/epel-7/jhli-ipmctl-epel-7.repo; \
        wget https://copr.fedorainfracloud.org/coprs/jhli/safeclib/repo/epel-7/jhli-safeclib-epel-7.repo)
RUN yum install -y ndctl ndctl-libs ndctl-devel libsafec ipmctl
# --- TODO: consider moving that to init container just responsilbe for preparing this data

WORKDIR /wca


COPY Pipfile Pipfile
COPY Pipfile.lock Pipfile.lock
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8
RUN pipenv install --dev --deploy
ENV PYTHONPATH=/wca



# note: Cache will be propably invalidated here.
COPY configs ./configs

COPY examples/external_package.py ./examples
COPY examples/hello_world_runner.py ./examples
COPY examples/hello_world_runner_with_dateutil.py ./examples
COPY examples/http_storage.py ./examples
COPY examples/__init__.py ./examples

COPY wca ./wca

ENTRYPOINT ["pipenv", "run", "python3.6", "wca/main.py"]

# ------------------------ pex ----------------------
# "pex" stage includes pex file in /usr/bin/
FROM devel AS pex
COPY . .
RUN make wca_package
RUN cp /wca/dist/wca.pex /usr/bin/
ENTRYPOINT ["/usr/bin/wca.pex"]

## ------------------------ standalone ----------------------
## Building final container that consists of wca only.
FROM centos:7 AS standalone
RUN yum -y update && yum -y install python36
COPY --from=pex /wca/dist/wca.pex /usr/bin/
ENTRYPOINT ["/usr/bin/wca.pex"]
