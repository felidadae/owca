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


# Building stage first: wca.
FROM centos:7 AS wca

RUN echo "" && rpm --import https://packages.confluent.io/rpm/5.2/archive.key
COPY /configs/confluent_repo/confluent.repo /etc/yum.repos.d/confluent.repo

RUN yum -y update
RUN yum -y install epel-release
RUN yum -y install python36 python-pip which make git
RUN yum install -y librdkafka1 librdkafka-devel-1.0.0_confluent5.2.2-1.el7.x86_64 gcc python36-devel.x86_64

RUN pip install pipenv

WORKDIR /wca

RUN [ ! -d confluent-kafka-python ] && git clone https://github.com/confluentinc/confluent-kafka-python
RUN cd confluent-kafka-python && git checkout v1.0.1

# Cache will be propably invalidated here.
COPY . .

RUN git clean -fdx
RUN pipenv install --dev
RUN pipenv run make wca_package OPTIONAL_FEATURES=kafka_storage


# Building final container that consists of wca only.
FROM centos:7

ENV CONFIG=/etc/wca/wca_config.yml \
    EXTRA_COMPONENT=example.external_package:ExampleDetector \
    LOG=info \
    OWN_IP=0.0.0.0 \
    ENV_UNIQ_ID=0

RUN yum install -y epel-release
RUN yum install -y python36

COPY --from=wca /wca/dist/wca.pex /usr/bin/

ENTRYPOINT \
    python36 /usr/bin/wca.pex \
        --config $CONFIG \
        --register $EXTRA_COMPONENT \
        --log $LOG \
        -0 \
        $WCA_EXTRA_PARAMS
