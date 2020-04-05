from unittest.mock import patch

from runner import run_workloads, single_3stage_experiment, \
        NODES_CAPACITIES, WORKLOADS_SET, \
        random_with_total_utilization_specified, \
        WaitPeriod


@patch('runner.default_shell_run')
def test_run_workloads(mock):
    workloads_run_order = ['w3', 'w1', 'w2']
    workloads_counts = {'w1': 18, 'w2': 30, 'w3': 2}
    run_workloads(workloads_run_order, workloads_counts)


def mock_count_run(command):
    mock_count_run.call_ += 1


@patch('runner.default_shell_run', side_effect=mock_count_run)
def test_single_3stage_experiment(mock):
    workloads_counts = {'w1': 2, 'w2': 1}
    mock_count_run.call_ = 0
    single_3stage_experiment('0', workloads_counts, {WaitPeriod.SCALE_DOWN: 60,
                                                     WaitPeriod.STABILIZE: 60*15})
    assert mock_count_run.call_ == 18


def test_random_with_total_utilization_specified():
    iterations, workloads, utilization = random_with_total_utilization_specified(
        (0.25, 0.35), (0.65, 0.8), NODES_CAPACITIES, WORKLOADS_SET)
    print(workloads)
    assert len(workloads) > 10
    assert iterations < 100
