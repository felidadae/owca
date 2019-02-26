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

setup(
    name='owca',
    author='Intel',
    description='Orchestration-aware Workload Collocation Agent',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Environment :: Console',
        'Intended Audience :: System Administrators',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 3.6',
        'Topic :: System :: Distributed Computing',
    ],
    install_requires=[
          'requests==2.20.1',
          'ruamel.yaml==0.15.37',
          'colorlog==3.1.4',
          'logging-tree==1.7',
          'dataclasses==0.6',
          'confluent-kafka==0.11.4'
    ],
    tests_require=[
          'pytest',
          'pytest-cov',
          'flake8'
    ],
    packages=find_packages(),
    python_requires=">=3.6",
    use_scm_version=True,
    setup_requires=[
        'setuptools_scm'
    ],
)
