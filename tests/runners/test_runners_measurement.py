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

from unittest.mock import Mock, patch

import pytest

from tests.testing import (assert_metric, redis_task_with_default_labels,
                           prepare_runner_patches, TASK_CPU_USAGE, WCA_MEMORY_USAGE,
                           DEFAULT_METRIC_VALUE, task, task_data, platform_mock)
from wca import storage
from wca.containers import Container
from wca.detectors import TaskData
from wca.mesos import MesosNode
from wca.metrics import MissingMeasurementException, MetricName, Metric, METRICS_METADATA
from wca.perf_uncore import UncoreEventConfigError, Event
from wca.resctrl import ResGroup
from wca.runners.measurement import (MeasurementRunner, _build_tasks_metrics,
                                     _prepare_tasks_data, TaskLabelRegexGenerator,
                                     TaskLabelGenerator, append_additional_labels_to_tasks)


@pytest.mark.parametrize('rdt_enabled, resctrl_available, monitoring_available, access_ok, ok', [
    (None, False, False, True, True),
    (None, True, False, True, True),
    (True, False, False, True, False),
    (True, True, True, True, True),
    (True, True, False, True, False),
    (True, True, True, False, False),
])
def test_measurements_runner_init_and_checks(rdt_enabled, resctrl_available,
                                             monitoring_available, access_ok, ok):
    # auto rdt
    runner = MeasurementRunner(
        node=Mock(spec=MesosNode),
        metrics_storage=Mock(spec=storage.Storage),
        rdt_enabled=rdt_enabled,
    )

    platform_mock = Mock(rdt_information=Mock(
        is_monitoring_enabled=Mock(return_value=monitoring_available)))

    with patch('wca.resctrl.check_resctrl', return_value=resctrl_available), \
            patch('wca.security.are_privileges_sufficient', return_value=access_ok), \
            patch('wca.platforms.collect_platform_information',
                  return_value=(platform_mock, None, None)):
        if ok:
            # ok no error
            assert runner._initialize() is None
        else:
            # fails
            assert runner._initialize() == 1


@prepare_runner_patches
@pytest.mark.parametrize('subcgroups', ([], ['/T/c1'], ['/T/c1', '/T/c2']))
def test_measurements_runner(subcgroups):
    # Node mock
    t1 = redis_task_with_default_labels('t1', subcgroups)
    t2 = redis_task_with_default_labels('t2', subcgroups)

    runner = MeasurementRunner(
        node=Mock(spec=MesosNode,
                  get_tasks=Mock(return_value=[t1, t2])),
        metrics_storage=Mock(spec=storage.Storage, store=Mock()),
        rdt_enabled=False,
        gather_hw_mm_topology=False,
        extra_labels=dict(extra_label='extra_value')
    )
    runner._wait = Mock()
    # Mock to finish after one iteration.
    runner._initialize()
    runner._iterate()

    # Check output metrics.
    got_metrics = runner._metrics_storage.store.call_args[0][0]

    # Internal wca metrics are generated (wca is running, number of task under control,
    # memory usage and profiling information)
    assert_metric(got_metrics, MetricName.WCA_UP, dict(extra_label='extra_value'))
    assert_metric(got_metrics, MetricName.WCA_TASKS, expected_metric_value=2)
    # wca & its children memory usage (in bytes)
    assert_metric(got_metrics, MetricName.WCA_MEM_USAGE_BYTES,
                  expected_metric_value=WCA_MEMORY_USAGE * 2 * 1024)

    # Measurements metrics about tasks, based on get_measurements mocks.
    cpu_usage = TASK_CPU_USAGE * (len(subcgroups) if subcgroups else 1)
    assert_metric(got_metrics, MetricName.TASK_CPU_USAGE_SECONDS, dict(task_id=t1.task_id),
                  expected_metric_value=cpu_usage)
    assert_metric(got_metrics, MetricName.TASK_CPU_USAGE_SECONDS, dict(task_id=t2.task_id),
                  expected_metric_value=cpu_usage)


@prepare_runner_patches
@patch('wca.runners.measurement.time.sleep')
def test_measurements_wait(sleep_mock):
    with patch('time.time', return_value=1):
        runner = MeasurementRunner(
            node=Mock(spec=MesosNode,
                      get_tasks=Mock(return_value=[])),
            metrics_storage=Mock(spec=storage.Storage, store=Mock()),
            rdt_enabled=False,
            extra_labels={}
        )

        runner._initialize()
        runner._iterate()
        sleep_mock.assert_called_once_with(1.0)

    with patch('time.time', return_value=1.3):
        runner._iterate()
        sleep_mock.assert_called_with(0.7)
        assert runner._last_iteration == 1.3

    with patch('time.time', return_value=2.5):
        runner._iterate()
        sleep_mock.assert_called_with(0)


_task_cpu_usage_metadata = METRICS_METADATA[MetricName.TASK_CPU_USAGE_SECONDS]


@pytest.mark.parametrize('tasks_data, expected_metrics', [
    ({}, []),
    ({'t1_task_id': task_data('/t1', labels={'app': 'redis'})}, []),
    ({'t1_task_id': task_data('/t1', labels={'app': 'redis'},
                              measurements={'task_cpu_usage_seconds': DEFAULT_METRIC_VALUE})},
     [Metric(MetricName.TASK_CPU_USAGE_SECONDS, labels={'app': 'redis'},
             value=DEFAULT_METRIC_VALUE, unit=_task_cpu_usage_metadata.unit,
             granularity=_task_cpu_usage_metadata.granularity, help=_task_cpu_usage_metadata.help,
             type=_task_cpu_usage_metadata.type
             )
      ])
])
def test_build_tasks_metrics(tasks_data, expected_metrics):
    got_metrics = _build_tasks_metrics(tasks_data)
    assert expected_metrics == got_metrics


@patch('wca.cgroups.Cgroup')
@patch('wca.perf.PerfCounters')
@patch('time.time', return_value=12345.6)
@patch('wca.containers.Container.get_measurements',
       Mock(return_value={'task_cpu_usage_seconds': 13}))
def test_prepare_tasks_data(*mocks):
    t = task('/t1', labels={'label_key': 'label_value'}, resources={'cpu': 3})
    containers = {
        t: Container('/t1', platform_mock)
    }

    tasks_data = _prepare_tasks_data(containers)

    assert tasks_data == {
        't1_task_id':
            TaskData(
                t.name, t.task_id, t.cgroup_path, t.subcgroups_paths,
                t.labels, t.resources,
                {'task_up': 1, 'task_last_seen': 12345.6, 'task_subcontainers': 0,
                    'task_cpu_usage_seconds': 13}
            )
    }


@patch('wca.cgroups.Cgroup')
@patch('wca.resctrl.ResGroup.get_measurements',
       side_effect=MissingMeasurementException())
@patch('wca.perf.PerfCounters')
def test_prepare_task_data_resgroup_not_found(*mocks):
    containers = {
        task('/t1', labels={'label_key': 'label_value'}, resources={'cpu': 3}):
            Container('/t1', platform_mock, resgroup=ResGroup('/t1'))
    }
    with pytest.raises(MissingMeasurementException):
        tasks_measurements, tasks_resources, tasks_labels = \
            _prepare_tasks_data(containers)


@patch('wca.cgroups.Cgroup.get_measurements', side_effect=MissingMeasurementException())
@patch('wca.perf.PerfCounters')
def test_prepare_task_data_cgroup_not_found(*mocks):
    containers = {
        task('/t1', labels={'label_key': 'label_value'}, resources={'cpu': 3}):
            Container('/t1', platform_mock)
    }
    with pytest.raises(MissingMeasurementException):
        tasks_measurements, tasks_resources, tasks_labels = \
            _prepare_tasks_data(containers)


@pytest.mark.parametrize('source_val, pattern, repl, expected_val', (
        ('__val__', '__(.*)__', r'\1', 'val'),
        ('example/devel/staging-13/redis.small', r'.*/.*/.*/(.*)\..*', r'\1', 'redis'),
        ('example/devel/staging-13/redis.small', r'non_matching_pattern', r'',
         'example/devel/staging-13/redis.small'),
))
def test_task_label_regex_generator(source_val, pattern, repl, expected_val):
    task1 = task('/t1', labels={'source_key': source_val})
    task_label_regex_generator = TaskLabelRegexGenerator(pattern, repl, 'source_key')
    assert expected_val == task_label_regex_generator.generate(task1)


@patch('wca.runners.measurement.log')
def test_append_additional_labels_to_tasks__generate_returns_None(log_mock):
    """Generate method for generator returns None."""

    class TestTaskLabelGenerator(TaskLabelGenerator):
        def generate(self, task):
            return None

    task1 = task('/t1', labels={'source_key': 'source_val'})
    append_additional_labels_to_tasks(
        {'target_key': TestTaskLabelGenerator()},
        [task1])
    log_mock.debug.assert_called_once()


@patch('wca.runners.measurement.log')
def test_append_additional_labels_to_tasks__overwriting_label(log_mock):
    """Should not overwrite existing previously label."""
    task1 = task('/t1', labels={'source_key': '__val__'})
    append_additional_labels_to_tasks(
        {'source_key': TaskLabelRegexGenerator('__(.*)__', '\\1', 'non_existing_key')},
        [task1])
    assert task1.labels['source_key'] == '__val__'
    log_mock.debug.assert_called_once()


@pytest.mark.parametrize('event, expected_output', [
    ('some_event_name/uncore_imc/event=0x80,umask=3/',
     ('some_event_name', 128, 'uncore_imc', 3, 0, 0)),
    ('some_event_name/uncore_cha/event=0x80,umask=3,config1=0x1',
     ('some_event_name', 128, 'uncore_cha', 3, 0, 1)),
    ('some_event_name/uncore_upi/event=0x0/', ('some_event_name', 0, 'uncore_upi', 0, 0, 0)),
    ('some_event_name/uncore_upi/config=0x80', ('some_event_name', 0, 'uncore_upi', 0, 128, 0))
])
def test_parse_uncore_event_input(event, expected_output):
    assert MeasurementRunner._parse_uncore_event_input(event) == expected_output


@pytest.mark.parametrize('event, exception', [
    ('some_event', AssertionError),
    ('some_event_name/uncore_imc/umask=3/', UncoreEventConfigError),
    ('/uncore_imc/event=0x80,umask=3/', AssertionError),
    ('some_event_name/uncore_imc/event=0x80,umask=3,config5=0x23/', UncoreEventConfigError)
])
def test_parse_uncore_event_input_fail(event, exception):
    with pytest.raises(exception):
        MeasurementRunner._parse_uncore_event_input(event)


@pytest.mark.parametrize('event, expected_output', [
    ('platform_rpq_occupancy',
     (Event(name=MetricName.PLATFORM_RPQ_OCCUPANCY, event=0x80), 'uncore_imc')),
    ('platform_rpq_occupancy/uncore_imc/event=0x80,umask=0/',
     (Event(name=MetricName.PLATFORM_RPQ_OCCUPANCY, event=0x80), 'uncore_imc')),
    ('some_unknown_event', (None, '')),
    ('some_unknown_event/uncore_imc/event=0x80,umask=0', (None, '')),
    ('platform_upi_rxl_flits',
     (Event(name=MetricName.PLATFORM_UPI_RXL_FLITS, event=0x3, umask=0xf), 'uncore_upi'))
])
def test_get_event_if_known(event, expected_output):
    assert MeasurementRunner._get_event_if_known(event) == expected_output


@pytest.mark.parametrize('event_name, event_value, umask, config, config1, expected_output', [
    ('some_metric', 128, 0, 0, 0,
     Event(name='some_metric', event=128, umask=0, config=0, config1=0)),
    ('some_metric', 0, 0, 0, 128,
     Event(name='some_metric', event=0, umask=0, config=0, config1=128))
])
def test_get_unknown_event(event_name, event_value, umask, config, config1, expected_output):
    assert MeasurementRunner._get_unknown_event(event_name, event_value,
                                                umask, config, config1) == expected_output
    assert event_name in METRICS_METADATA
