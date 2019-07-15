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


FROM tensorflow/tensorflow:1.10.1-devel-py3
RUN git clone https://github.com/tensorflow/benchmarks
RUN ln -sfn /usr/bin/python2 /usr/bin/python
RUN apt-get update
RUN apt -y install wget
RUN apt-get -y install zlib1g-dev build-essential

WORKDIR /opt
RUN wget https://www.python.org/ftp/python/3.6.6/Python-3.6.6.tgz
RUN tar -xvf Python-3.6.6.tgz
WORKDIR /opt/Python-3.6.6
RUN ./configure
RUN make
RUN make install

RUN cd /root/benchmarks && git checkout 44aeb98
RUN /usr/bin/python3.5 /root/benchmarks/scripts/tf_cnn_benchmarks/tf_cnn_benchmarks.py --datasets_use_prefetch=True --batch_group_size=1 --device=cpu --data_format=NHWC --data_name=cifar10 --batch_size=128 --model=resnet56 --train_dir=/saved_model/ --num_epochs=2
COPY dist/tensorflow_benchmark_training_wrapper.pex /
COPY dist/tensorflow_benchmark_prediction_wrapper.pex /
