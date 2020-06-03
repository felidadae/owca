************************
Score algorithm overview
************************

We constructed a heuristic for automatic assessment of how well a workload match a node with
Intel PMEM memory installed ran in 2LM mode. The heuristic is trying to reach two goals:
1) use as much of memory as possible on PMEM nodes 2) minimize chance of worse than DRAM
performance of scheduled on PMEM nodes workloads. The 2) is approached with idea that performance
can be degraded mostly when any of memory bandwidth, L4 cache (in 2LM mode DRAM runs as a next
level cache) shared resources are saturated.

The heuristic assigns to each workload a single positive rational number – thus creating a sorted list if
taking into consideration all workloads. That single number, we call a workload’s score.
Lower the number, better a workload fits the PMEM node according to our heuristic.
The value of score does not depends on different workloads, but only on workload innate features.

But what the algorithm considers a *workload*? As a workload the solution treats a Kubernetes
*statefulset* or a *deployment*. All pods of a statefulset/deployment are treated as instances of the same workload.

The algorithm is implemented as a set of Prometheus rules. Thanks to that can be easily visualized,
simply understood and tweaked by a cluster operator.


Score value interpretation
##########################

Nice feature of the algorithms is that the score value has intuitive interpretation, which is explained below.

Having a workload with score of value *S*, by scheduling only instances of that workload to PMEM node we
should according to the heuristic maximally use 1/S * 100% capacity of memory of that node.
By sticking to that limit *(1/S * 100%)* the node shared resources such as CPU, memory, memory
bandwidth and L4 cache should not be saturated.

For example, if score=2 is assigned to a workload A, it means that by scheduling only that workload to a PMEM node,
we can maximally use 50% (½*100%) of memory of that node not having expected by heuristic shared resource saturation.

.. csv-table::
	:header: "Value", "Memory max usage"
	:widths: 5, 5

    "1", "100%"
    "1.5", "75%"
    "2", "50%"
    "3", "33%"
    "10", "10%"

As we see score of value 10 indicates that the workload does not fit PMEM node at all – scheduling it into PMEM
is a waste of space which could be used by another workload with better score.

If a workload has score lower than 1, by putting it into equation, we get memory usage which is bigger than 100%.
To keep the simple interpretation, just treat the score higher than 100% as having wider margin of safety of
a workload performance and left more space for workloads with worse score value.

Scores for our testing workloads
################################

Below we provide screenshot of additional Graphana dashboard provided by us for visualization of final and
transitional results of the algorithm. For our testing workloads the score values are widely scattered.
As a far best workload with score=0.88 is considered redis-memtier-big.
[image showing list of scores for workloads from our cluster]


Workloads characterization
##########################

The heuristic approximates for each workload among others:
- peak memory bandwidth used (traffic from caches to RAM memory) with division on read/write,
- peak working set size (number of touched memory pages in a short period of time).
All this is calculated based on historical data (as default history window is set to 7 days).

Setting cut-off Score value
###########################

The created workloads list, ranked by the best the Score, can be used to manually place workloads
to make the best use of PMEM.

We recommend to schedule only workloads with score of value  S_cutoff <= 1.5 on PMEM nodes.
If workloads are scheduled manually, make sure only 1/S_cutoff * 100% of total available
memory is used by workloads.

Our additional tool WCA-Scheduler can perform that task automatically taking into consideration more factors.


Gathering required metrics
##########################

The score is calculated based on the metrics provided by WCA or cAdvisor.

WCA
***
For calculating Score some metrics which are provided by WCA agent are needed.

To WCA expose needed metrics, it is necessary to set in its configuration file:
- gather_hw_mm_topology set as True;
- enable_derived_metrics set as True;
- In event_names enable Task_offcore_requests_demand_data_rd, Task_offcore_requests_demand_rfo

`node` and `metrics_storage` should not be changed. Node is responsible for communication with the Kubernetes API,
and metric storage for displaying metrics in the Prometheus format.

Field changes may be required for `cgroup_driver` on another using driver by Docker,
and ‘monitored_namespaces’ form ‘default’ when workloads running in another Kubernetes namespace.

cAdvisor
********

Future work. It’s not yet fully supported.

Calculating the Score by use Prometheus rules.
##############################################

The Score is calculated by rules in Prometheus.

Configuring the Prometheus
**************************

Prometheus is required for the score implementation to work. We provide an example way of
deploying Prometheus in our repository.

No deployed Prometheus on the cluster
*************************************

We use configuration prepared in the repository under the path `examples/kubernetes/monitoring` by using
kustomize (https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/).
It deploys all monitoring required for calculating the Score.

Existing Prometheus on the cluster
**********************************

In case Prometheus is already deployed it is only required to deploy rules defined in
the file `examples/kubernetes/monitoring/prometheus/prometheus_rule.score.yaml` or
generated by script described in next paragraph.

Configuring the Score
#####################

As mentioned in $(Workloads characterization) the approximators of workloads features are calculated
as maximum value (in reality we do not calculate max value but 95 percentile for cutting off outliers)
over period of time. By default the period length is set to 7 days, but can be changed using
script `examples/kubernetes/monitoring/prometheus/generate_score_prometheus_rule.py`.

Smaller the length of period higher chance of not capturing high traffic behavior of the workload,
bigger higher chance that the feature will be usually overestimated (resulting in
undersubscription of the node).

.. code-block:: shell

    python3 generator_prometheus_rules.py --features_history_period 7d –output prometheus_rules_score.yaml

`features_history_period` is time used in rules. Prometheus query language supports time
durations specified as a number, followed immediately by one of the following
units: s - seconds, m - minutes, h - hours, d - days, w - weeks, y - years.

Grafana dashboard
*****************

We prepared graphana dashboard for visualization of the results mentioned in $(Scores for our testing workloads).
The dashbord yaml file is available at: `examples/kubernetes/monitoring/prometheus/graphana_score.yaml`

