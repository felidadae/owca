************************
Score algorithm overview
************************

We constructed a heuristic for automatic assessment of how well a workload match a node with
Intel PMEM memory installed ran in 2LM mode. The heuristic is trying to reach two goals:

- use as much of memory as possible on PMEM nodes
- minimize a chance of worsening workloads performance (comparing to DRAM).

The second is approached with idea that performance can be degraded mostly when any of:

- memory bandwidth,
- L4 cache (in 2LM mode DRAM runs as a next level cache)

is saturated on a node.

*The heuristic assigns to each workload a single positive rational number*, thus creating a preference workloads list.
That single number, we call a workload's **score**.
**Lower** the number, **better** a workload fits the PMEM node according to our heuristic.
The value of score depends only on workload innate features and resources capacity of target PMEM node.

But what the algorithm considers a **workload**? The solution treats a Kubernetes
**statefulset** or a **deployment** as a workload. All pods of a statefulset/deployment are treated as instances
of the same workload.

The algorithm is implemented as a set of **Prometheus rules**. Thanks to that, it can be easily visualized,
simply understood and tweaked by a cluster operator.


Score value interpretation
##########################

Nice feature of the algorithms is that the score value has intuitive interpretation, which is explained below.

Let's assume we have workload A with score *S=score(workload=A)*.
When scheduling only that workload on PMEM node we should **maximally** use **1/S * 100%** capacity of memory of that node.

By sticking to **that upper bound of memory usage** *1/S * 100%* the node other resources such as: CPU, memory, memory
bandwidth and L4 cache, should not be saturated.

For example, if *S=score(workload=A)=2* is assigned to a workload *A*, it means that by scheduling
only that workload to a PMEM node, we can maximally use *50%* (0.5*100%) of memory.
By doing that we should not cause saturation of other resources on the node.

.. csv-table::

    "Score", "PMEM upper bound of memory usage"<
    "0.5", "200%"
    "0.75", "133%"
    "1", "100%"
    "1.5", "67%"
    "2", "50%"
    "3", "33%"
    "10", "10%"

As we see score of value *10* indicates that the workload does not fit PMEM node at all – scheduling it on a PMEM node
is a waste of space which could be used by another workload with better score.

If a workload has score lower than 1, then equation **1/S * 100%** gives number larger than 100% (e.g. S=0.5 --> 200%).
It is a **desired** situation. Having workloads with **smaller score than 1** we **increase safety margin**
for shared resources **saturation** on the node.


Scores for our testing workloads
################################

Below we provide a screenshot of Grafana dashboard provided by us for visualization of final and
transitional results of the algorithm. For our testing workloads the score values are widely scattered.
As a far best workload with *score=1.1* is considered *redis-memtier-big*.

.. image:: score_sorted_list.png
  :width: 300
  :alt: Image showing sorted list of scores of workloads from our testing cluster

Workloads characterization
##########################

For each workload the heuristic approximates (among others):

- peak **memory bandwidth** used (traffic from caches to RAM memory) with division on read/write,
- peak **working set size** (number of touched memory pages in a period of time).

All this is calculated based on historical data (as default history window is set to 7 days).
Please refer to `prometheus_rule.score.yaml <../examples/kubernetes/monitoring/prometheus/prometheus_rule.score.yaml>`_.

Setting cut-off Score value
###########################

The created workloads scores list can be used to manually place workloads
to make the best use of nodes with PMEM memory modules installed.

We recommend to schedule only workloads with score of value  **S <= S_cutoff** where **S_cutoff=1.5** on PMEM nodes.
If workloads are scheduled manually, make sure only **1/S_cutoff * 100%** of total available
memory is used by workloads.

Our additional tool `WCA-Scheduler <wca-scheduler.rst>`_ can perform that task automatically
taking into consideration more factors.


**************
Configuration
**************

Gathering required metrics
##########################

The score is calculated based on the metrics provided by `WCA` or `cAdvisor`.

WCA
***
For calculating Score some metrics provided by WCA agent are needed.
Please use below defined configuration file for WCA agent as a template.

.. code-block:: yaml

  runner: !MeasurementRunner
  interval: 5.0
  node: !KubernetesNode
    cgroup_driver: cgroupfs
    monitored_namespaces: ["default"]
    kubeapi_host: !Env KUBERNETES_SERVICE_HOST
    kubeapi_port: !Env KUBERNETES_SERVICE_PORT
    node_ip: !Env HOST_IP

  metrics_storage: !LogStorage
    overwrite: True
    output_filename: /var/lib/wca/metrics.prom

  extra_labels:
    node: !Env HOSTNAME
  event_names:
    - task_cycles
    - task_instructions
    - task_offcore_requests_demand_data_rd
    - task_offcore_requests_demand_rfo
  enable_derived_metrics: True
  uncore_event_names:
    - platform_cas_count_reads
    - platform_cas_count_writes
    - platform_pmm_bandwidth_reads
    - platform_pmm_bandwidth_writes

  wss_reset_interval: 1
  gather_hw_mm_topology: True

``node`` and ``metrics_storage`` should not be changed. Node is responsible for communication with the Kubernetes API,
and metric storage for displaying metrics in the Prometheus format.

Field changes may be required for ``cgroup_driver`` on another using driver by Docker,
and ``monitored_namespaces`` form ‘default’ when workloads running in another Kubernetes namespace.

It is necessary to set in its configuration file:

- ``gather_hw_mm_topology set`` as *True*;
- ``enable_derived_metrics set`` as *True*;
- In ``event_names`` enable
    - **task_offcore_requests_demand_data_rd**
    - **task_offcore_requests_demand_rfo**

cAdvisor
********

Future work. It’s not yet fully supported.

Prometheus rules
################

The score algorithm is implemented as `a set of Prometheus rules <../examples/kubernetes/monitoring/prometheus/prometheus_rule.score.yaml>`_.

Configuring the Prometheus
**************************

Prometheus is required for the score implementation to work. We provide an example way of
deploying Prometheus in our repository.

No deployed Prometheus on the cluster
*************************************

We use configuration prepared in the repository under the path `examples/kubernetes/monitoring` by using
`kustomize` (https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/).
It deploys all monitoring required for calculating the Score.

Existing Prometheus on the cluster
**********************************

In case Prometheus is already deployed it is only required to deploy rules defined in
the files:
- `prometheus_rule.score.yaml <../examples/kubernetes/monitoring/prometheus/prometheus_rule.score.yaml>`_
(or generated by script described in next paragraph if one wants to change default history window length);
- `prometheus_rule.pmem.yaml <../examples/kubernetes/monitoring/prometheus/prometheus_rule.pmem.yaml>`_ if there is no
PMEM node on the cluster (this rule adds virtual PMEM node metrics); **NOTE: we defined the most common configuration
of PMEM node in the rule, please contact us if the configuration must be changed**

This could be accomplished using command:

.. code-block:: shell

    kubectl apply -n prometheus -f examples/kubernetes/monitoring/prometheus/prometheus_rule.score.yaml \
                                   examples/kubernetes/monitoring/prometheus/prometheus_rule.pmem.yaml

Configuring the Score
#####################

As mentioned in `Workloads characterization`_ the approximators of workloads features are calculated
as peak value using **max** and **quantile_over_time** prometheus functions:

.. code-block:: yaml

    - record: app_mbw_flat
      expr: 'max(quantile_over_time(0.95, task_mbw_flat[7d:2m])) by (app)'
    - record: app_wss
      expr: 'max(quantile_over_time(0.95, task_wss_referenced_bytes[7d:2m])) by (app) / 1e9'

By default the period length is set to 7 days, but can be changed using
`generator_prometheus_rules.py script <../examples/kubernetes/scripts/generator_prometheus_rules.py>`_ or manually.

.. code-block:: shell

    python3 examples/kubernetes/scripts/generator_prometheus_rules.py --features_history_period 7d –output prometheus_rules_score.yaml

`features_history_period` is time used in rules. Prometheus query language supports time
durations specified as a number, followed immediately by one of the following
units: s - seconds, m - minutes, h - hours, d - days, w - weeks, y - years.

Grafana dashboard
*****************

We prepared Grafana dashboard `graphana dashboard <../examples/kubernetes/monitoring/grafana/2lm_dashboards/2lm_score_dashboard.yaml>`_
for visualization of the results mentioned in `Scores for our testing workloads`_.

Limitations
###########

There are few limitations of our solution, which depending on usage can constitute a problem:

- no support for **versions** of statefulset/deployment, which means, that a statefulset/deployment is considered as
    the same workload as long as the **name** of the statefulset/deployment matches.
- requirements of some workload can be overestimated,
    e.g. if workload is wrongly configured and keeps restarting after a short period of time
- we support only workloads with defined CPU/MEM requirements.