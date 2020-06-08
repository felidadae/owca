from runner_analyzer import WStat, Stat

def test_calculate_common_baseline():
    baseline_1 = WStat(name='workload_a', latency=Stat(_avg=20, _min=10, _max=30, _stdev = 5),
                       throughput=Stat(_avg=1000, _min=950, _max=1100, _stdev=30), count=2)
    baseline_2 = WStat(name='workload_a', latency=Stat(_avg=20, _min=10, _max=30, _stdev = 5),
                       throughput=Stat(_avg=1000, _min=950, _max=1100, _stdev=30), count=2)
    baseline_3 = WStat(name='workload_a', latency=Stat(_avg=float('NaN'), _min=float('NaN'), _max=float('NaN'), _stdev = float('NaN')),
                       throughput=Stat(_avg=float('NaN'), _min=float('NaN'), _max=float('NaN'), _stdev=float('NaN')), count=0)
    baseline_1.merge_with_other(baseline_2)
    assert baseline_1.latency._avg == 20
    assert baseline_1.count == 4

    baseline_1.merge_with_other(baseline_3)
    assert baseline_1.latency._avg == 20
    assert baseline_1.count == 4

    baseline_3.merge_with_other(baseline_1)
    assert baseline_3.latency._avg == 20
    assert baseline_3.count == 4

