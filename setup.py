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

from setuptools import setup, find_packages
import os
import json

# Taking all packages from Pipfile.lock except for:
# * confluent_kafka, unless INCLUDE_UNSAFE_CONFLUENT_KAFKA_WHEEL is set to 'yes'.
install_requires = ['%s%s' % (name, spec['version'])
                    for name, spec in
                    json.load(open('Pipfile.lock'))['default'].items()]
if os.environ.get('INCLUDE_UNSAFE_CONFLUENT_KAFKA_WHEEL', 'no') == 'yes':
    print('Warning: bundling confluent_kafka package with binary libraries, '
          'some of them are outdated and contains security vulnerabilities.')
else:
    install_requires = [item for item in install_requires if "confluent-kafka" not in item]

packages = ['wca', 'wca.extra', 'wca.runners']

print("Install requires:")
print(install_requires)
print("Packages bundled:")
print(packages)

setup(
    name='wca',
    author='Intel',
    description='Workload Collocation Agent',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Environment :: Console',
        'Intended Audience :: System Administrators',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 3.6',
        'Topic :: System :: Distributed Computing',
    ],
    install_requires=install_requires,
    packages=packages,
    python_requires=">=3.6",
    use_scm_version=True,
)
