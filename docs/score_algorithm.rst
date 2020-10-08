########################################
Guide to usage of Score Prometheus rules
########################################

**Note: please read last paragraph *Limitations and notes* before using the solution.**

.. contents:: Table of Contents


********
Overview
********

Overview of the main algorithm
##############################

We constructed a heuristic for automatic assessment of how well a workload match a node with
Intel PMEM memory installed ran in 2LM (or HMEM) mode. The heuristic is trying to reach two goals:

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
of the same workload (assuming that there exists a common label,
for detail please read paragraph **Workload identification**).

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

    "Score", "PMEM upper bound of memory usage"
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


Results for our example workloads
#################################

Below we provide a screenshot of Grafana dashboard provided by us for visualization of final and
transitional results of the algorithm. For our testing workloads the score values are widely scattered.
As a far best workload with *score=1.1* is considered *redis-memtier-big*.

.. image:: score_sorted_list.png
  :width: 300
  :alt: Image showing sorted list of scores of workloads from our testing cluster

Workloads characterization
##########################

For each workload the heuristic approximates (among others):

- **memory bandwidth** requirement (traffic from caches to RAM memory) with division on read/write,
  **what must be noted Intel RDT** is required to be enabled on the node for this to work,
- **working set size** requirement (number of touched memory pages in a period of time).

All this is calculated based on historical data (as default history window is set to 7 days).
Please refer to `prometheus_rule.score.yaml <../examples/kubernetes/monitoring/prometheus/prometheus_rule.score.yaml>`_.

Choosing cut-off Score value
############################

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
File `wca-config <../examples/kubernetes/monitoring/wca/wca-config.yaml>` defines proper
configuration for defined in this file usage.

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

- `prometheus_rule.score.yaml <../examples/kubernetes/monitoring/prometheus/prometheus_rule.score.yaml>`_ (or generated by script described in next paragraph if one wants to change default history window length);
- `prometheus_rule.pmem.yaml <../examples/kubernetes/monitoring/prometheus/prometheus_rule.pmem.yaml>`_ if there is no PMEM node on the cluster (this rule adds virtual PMEM node metrics); **NOTE: we defined the most common configuration of PMEM node in the rules**

This could be accomplished using command:

.. code-block:: shell

    kubectl apply -n prometheus -f examples/kubernetes/monitoring/prometheus/prometheus_rule.score.yaml \
                                   examples/kubernetes/monitoring/prometheus/prometheus_rule.pmem.yaml

Configuring the Score
#####################

2LM or HMEM mode
****************

A little changes must be done to adjust the rules for **HMEM** PMEM mode. By default the rules file is
adjusted for 2LM mode.
If score are targeted at **HMEM** mode please run replace commands:

.. code-block:: shell

    perl -i -pe "s/expr: \'0.5\' # pmem_mode_wss_weight/expr: \'1.0\' # pmem_mode_wss_weight/g" examples/kubernetes/monitoring/prometheus/prometheus_rule.score.yaml
    perl -i -pe "s/expr: \'96\' # pmem_mode_wss_weight/expr: \'192\' # pmem_mode_wss_weight/g" examples/kubernetes/monitoring/prometheus/prometheus_rule.pmem.yaml


History window length
*********************

We approximate workloads resource requirements by using
**quantile** and **quantile_over_time** prometheus functions:

.. code-block:: yaml

    - record: app_mbw_flat
      expr: 'quantile(0.95, quantile_over_time(0.95, task_mbw_flat_ignore_initialization[7d])) by (app, source)'
    - record: app_wss
      expr: 'quantile(0.95, quantile_over_time(0.95, task_wss_ignore_initialization[7d])) by (app, source) / 1e9'

We use **0.95-quntile** to get rid off outliers and fit requirements to peak traffic.

By default the period length is set to **7 days**, but can be changed using
commands (by filling proper value instead of `NEW_WINDOW_LENGTH`):

.. code-block:: shell

    perl -i -pe "s/7d/new_window_length/g" examples/kubernetes/monitoring/prometheus/prometheus_rule.score.yaml

Prometheus query language supports time
durations specified as a number, followed immediately by one of the following
units: s - seconds, m - minutes, h - hours, d - days, w - weeks, y - years.


****************************
Visualization of the results
****************************

Prometheus query for score
##########################

Please use Prometheus query to list potential candidates (those with smaller value better suit 2LM/HMEM nodes):

.. code-block:: yaml

    sort(profile_app_score_max)

Grafana dashboard
#################

We prepared Grafana dashboard `graphana dashboard <../examples/kubernetes/monitoring/grafana/2lm_dashboards/2lm_score_dashboard.yaml>`_
for visualization of the results mentioned in `Scores for our testing workloads`_.
The dashboard requires Grafana with `boom table plugin <https://grafana.com/grafana/plugins/yesoreyeram-boomtable-panel>`_.


*********************
Limitations and notes
*********************

There are few limitations of our solution, which depending on usage can constitute a problem:

- requires automatic method of assigning tasks to workloads
- we support only workloads with defined CPU/MEM requirements,
- our method of estimating WSS (working set size) uses /proc/{pid}/smaps kernel API,
  which may have non negligible overhead (the overhead is tried to be mitigated
  by long sampling and resets interval - 60s/15minutes),
- not detecting workloads where all workloads tasks are short-lived.

Ignoring tasks first N minutes of execution
###########################################

We on purpose ignore first N minutes (by default N=30) of execution of each task.
There two reasons why such approach was implemented:

- ignore any costly initialization phase, which could result in overestimatation of parameters,
- ignore short living tasks, as our method of calculating WSS needs at least few minutes for observing a task,
- ignore wrongly configured tasks.

Drawback of the approach is that we will not characterize workloads with only short living tasks.

Workload identification
#######################

The algorithm requires that there will be a way to identify all instances of a workload. In the simplest case a common
label on all pods identifying the workload they belong to exists (e.g. following
`kubernetes recommended scheme of labelling <https://kubernetes.io/docs/concepts/overview/working-with-objects/common-labels/#labels>`_ 
provides needed common label).
