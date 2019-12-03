# Copyright (c) 2019 Intel Corporation
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

import enum
from wca.metrics import METRICS_METADATA, MetricGranurality, MetricName, MetricMetadata


def prepare_csv_table(data, header=True, csv_header=False):
    if header:
        table = '.. csv-table::\n'
        table += '\t:header: "Name", "Help", "Enabled", "Unit", "Type", "Source", "Levels/Labels"\n'
        table += '\t:widths: 5, 5, 5, 5, 5, 5, 5 \n\n\t'
    elif csv_header:
        table = '"Name", "Help", "Enabled", "Unit", "Type", "Source", "Levels/Labels"\n'
    else:
        table = ''

    if header:
        pref = '\t'
    else:
        pref = ''

    table += ('\n%s'%(pref)).join(['"{}", "{}", "{}", "{}",  "{}", "{}", "{}"'.format(*row) for row in data])

    return table


def generate_title(title):
    return title + '\n' + ''.join(['=' for _ in range(len(title))])


def generate_subtitle(subtitle):
    return subtitle + '\n' + ''.join(['-' for _ in range(len(subtitle))])


METRICS_DOC_PATH = 'docs/metrics.rst'
METRICS_CSV_PATH = 'docs/metrics.csv'

INTRO = """
================================
Available metrics
================================

**This software is pre-production and should not be deployed to production servers.**

For searchable list of metrics `metrics as csv file <metrics.csv>`_ .

.. contents:: Table of Contents

"""

METRICS_SOURCES = """
Metrics sources
===============

Check out `metrics sources documentation <metrics_sources.rst>`_  to learn how measurement them.

"""


def generate_docs(csv=False):

    task_data = []

    platform_data = []

    internal_data = []

    for metric in MetricName.__members__.values():

        metadata = METRICS_METADATA.get(metric)
        if not metadata:
            print('Warning no metadata for metric! %s' % metric)
            continue

        if metadata.levels:
            levels = ', '.join(metadata.levels)
        else:
            levels = ''

        def value_or_str(v):
            if isinstance(v, enum.Enum):
                return str(v.value)
            else:
                return str(v)

        data = (
            metric,
            metadata.help,
            metadata.enabled,
            value_or_str(metadata.unit),
            value_or_str(metadata.type),
            metadata.source,
            levels
        )

        if metadata.granularity == MetricGranurality.TASK:
            task_data.append(data)
        elif metadata.granularity == MetricGranurality.PLATFORM:
            platform_data.append(data)
        elif metadata.granularity == MetricGranurality.INTERNAL:
            internal_data.append(data)

    tasks = generate_title("Task's metrics") + '\n\n' if not csv else ''
    tasks += prepare_csv_table(task_data, header=not csv, csv_header=csv) + '\n\n'

    platforms = generate_title("Platform's metrics") + '\n\n' if not csv else ''
    platforms += prepare_csv_table(platform_data, header=not csv) + '\n\n'

    internal = generate_title("Internal metrics") + '\n\n' if not csv else ''
    internal += prepare_csv_table(internal_data, header=not csv) + '\n\n'

    return tasks + '\n\n' + platforms + '\n\n' + internal


if __name__ == '__main__':
    with open(METRICS_DOC_PATH, 'w') as f:
        f.write(INTRO)
        f.write(METRICS_SOURCES)
        f.write(generate_docs())
    with open(METRICS_CSV_PATH, 'w') as f:
        f.write(generate_docs(csv=True))
