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


import os
from common import application_host_ip, command, image_name, \
    initContainers, json, securityContext, pod, volumeMounts

#----------------------------------------------------------------------------------------------------
###
# Params which can be modified by exporting environment variables.
###

# Batch size and epochs.
tensorflow_train_batch_size = os.environ.get('tensorflow_train_batch_size', '100')
tensorflow_train_epochs = os.environ.get('tensorflow_train_epochs', '100')
#----------------------------------------------------------------------------------------------------

command.append(
    "/wrapper.pex --command 'training --dataset_path '/' --batch_size {batch_size} --epochs {epochs}' "
    "--stderr 0 --kafka_brokers '{kafka_brokers}' --kafka_topic {kafka_topic} "
    "--log_level {log_level} "
    "--metric_name_prefix 'tensorflow_train_' "
    "--slo {slo} --sli_metric_name tensorflow_train_images_processed --inverse_sli_metric_value "
    "--peak_load 1 --load_metric_name const "
    "--labels \"{labels}\"".format(batch_size=tensorflow_train_batch_size,
                                   epochs=tensorflow_train_epochs,
                                   kafka_brokers=wrapper_kafka_brokers,
                                   log_level=wrapper_log_level,
                                   kafka_topic=wrapper_kafka_topic,
                                   labels=str(wrapper_labels), slo=slo))

json_format = json.dumps(pod)
print(json_format)
