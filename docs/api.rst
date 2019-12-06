
==============================
Workload Collocation Agent API
==============================

**This software is pre-production and should not be deployed to production servers.**

.. contents:: Table of Contents


MeasurementRunner
=================


MeasurementRunner run iterations to collect platform, resource, task measurements
and store them in metrics_storage component.

- `node`: **type**:

    Component used for tasks discovery.

- ``metrics_storage``: **type** = `DEFAULT_STORAGE`

    Storage to store platform, internal, resource and task metrics.
    (defaults to DEFAULT_STORAGE/LogStorage to output for standard error)

- ``interval``: **Numeric(0,60)** = *1.*

    Iteration duration in seconds (None disables wait and iterations).
    (defaults to 1 second)

- ``rdt_enabled``: **Optional[bool]** = *None*

    Enables or disabled support for RDT monitoring.
    (defaults to None(auto) based on platform capabilities)

- ``gather_hw_mm_topology``: **bool** = *False*

    Gather hardware/memory topology based on lshw and ipmctl.
    (defaults to False)

- ``extra_labels``: **Optional[Dict[Str, Str]]** = *None*

    Additional labels attached to every metrics.
    (defaults to empty dict)

- ``event_names``: **List[str]** = `[]`

    Perf counters to monitor.
    (defaults to not collect perf counters - empty list of events)

- ``enable_derived_metrics``: **bool** = *False*

    Enable derived metrics ips, ipc and cache_hit_ratio.
    (based on enabled_event names, default to False)

- ``enable_perf_uncore``: **bool** = *None*

    Enable perf event uncore metrics.
    (defaults to None - automatic, if available enable)

- ``task_label_generators``: **Optional[Dict[str, TaskLabelGenerator]]** = *None*

    Component to generate additional labels for tasks.
    (optional)

- ``allocation_configuration``: **Optional[AllocationConfiguration]** = *None*

    Allows fine grained control over allocations.
    (defaults to AllocationConfiguration() instance)

- ``wss_reset_interval``: **int** = *0*

    Interval of reseting wss.
    (defaults to 0, not measured)

- ``include_optional_labels``: **bool** = *False*

    Include optional labels like: sockets, cpus, cpu_model
    (defaults to False)



AllocationRunner
================

Runner is responsible for getting information about tasks from node,
calling allocate() callback on allocator, performing returning allocations
and storing all allocation related metrics in allocations_storage.

Because Allocator interface is also detector, we store serialized detected anomalies
in anomalies_storage and all other measurements in metrics_storage.


- ``measurement_runner``: **MeasurementRunner**

    Measurement runner object.

- ``allocator``: **Allocator**

    Component that provides allocation logic.

- ``anomalies_storage``: **Storage** = `DEFAULT_STORAGE`

    Storage to store serialized anomalies and extra metrics.

- ``allocations_storage``: **tdwiboolype** = `DEFAULT_STORAGE`

    Storage to store serialized resource allocations.

- ``rdt_mb_control_required``: **bool** = *False*

    Indicates that MB control is required,
    if the platform does not support this feature the WCA will exit.

- ``rdt_cache_control_required``: **bool** = *False*

    Indicates tha L3 control is required,
    if the platform does not support this feature the WCA will exit.

- ``remove_all_resctrl_groups``: **bool** = *False*

    Remove all RDT controls groups upon starting.



DetectionRunner
===============

DetectionRunner extends MeasurementRunner with ability to callback Detector,
serialize received anomalies and storing them in anomalies_storage.

- ``measurement_runner``: **MeasurementRunner**

    Measurement runner object.

- ``allocator``: **AnomalyDetector**

    Component that provides allocation logic.

- ``anomalies_storages``: **Storage** = *DEFAULT_STORAGE*

    Storage to store serialized anomalies.



MesosNode
=========

Class to communicate with orchestrator: Mesos.
Derived from abstract Node class providing get_tasks interface.

- ``mesos_agent_endpoint``: **Url** = *'https://127.0.0.1:5051'*

    By default localhost.

- ``timeout``: **Numeric(1, 60)** = *5*

    Timeout to access kubernetes agent [seconds].

- ``ssl``: **Optional[SSL]** = *None*

    ssl object used to communicate with kubernetes



KubernetesNode
==============

Class to communicate with orchestrator: Kubernetes.
Derived from abstract Node class providing get_tasks interface.

- ``cgroup_driver``: **CgroupDriverType** = *CgroupDriverType.CGROUPFS*

    We need to know what cgroup driver is used to properly build cgroup paths for pods.
    Reference in source code for kubernetes version stable 1.13:
    https://github.com/kubernetes/kubernetes/blob/v1.13.3/pkg/kubelet/cm/cgroup_manager_linux.go#L207


- ``ssl``: **Optional[SSL]** = *None*

    ssl object used to communicate with kubernetes

- ``client_token_path``: **Optional[Path]** = *SERVICE_TOKEN_FILENAME*

    Default path is using by pods. You can override it to use wca outside pod.

- ``server_cert_ca_path``: **Optional[Path]** = *SERVICE_CERT_FILENAME*

    Default path is using by pods. You can override it to use wca outside pod.

- ``kubelet_enabled``: **bool** = *False*

    If true use **kubelet**, otherwise **kubeapi**.

- ``kubelet_endpoint``: **Url** = *'https://127.0.0.1:10250'*

    By default use localhost.

- ``kubeapi_host``: **Str** = *None*

- ``kubeapi_port``: **Str** = *None*

- ``node_ip``: **Str** = *None*

- ``timeout``: **Numeric(1, 60)** = *5*

    Timeout to access kubernetes agent [seconds].

- ``monitored_namespaces``: **List[Str]** =  *["default"]*

    List of namespaces to monitor pods in.



LogStorage
==========

Outputs metrics encoded in Prometheus exposition format
to standard error (default) or provided file (output_filename).

- ``output_filename``: **Optional[Path]** = *None*

    If set to None, then prints data to stderr.

- ``overwrite``: **bool** = *False*

    When set to True the `output_filename` file will always contain
    only last stored metrics.

- ``include_timestamp``: **Optional[bool]** = *None*

    Whether to add timestamps to metrics.
    If set to None while constructing (default value), then it will be
    set in the constructor to a value depending on the field `overwrite`:

    - with `overwrite` set to True, timestamps are not added
      (in order to minimise number of parameters needed to be
      set when one use node exporter),
    - with `overwrite` set to False, timestamps are added.

- ``filter_labels``: **Optional[List[str]]** = *None*




KafkaStorage
============

Storage for saving metrics in Kafka.

- ``topic``: **Str**

    name of a kafka topic where message should be saved

- ``brokers_ips``: **List[IpPort]** = *"127.0.0.1:9092"*

    list of addresses with ports of all kafka brokers (kafka nodes)

- ``max_timeout_in_seconds``: **Numeric(0, 5)** = *0.5*

    if a message was not delivered in maximum_timeout seconds
    self.store will throw FailedDeliveryException

- ``extra_config``: **Dict[Str, Str]** = *None*

    additionall key value pairs that will be passed to kafka driver
    https://github.com/edenhill/librdkafka/blob/master/CONFIGURATION.md
    e.g. {'debug':'broker,topic,msg'} to enable logging for kafka producer threads

- ``ssl``: **Optional[SSL]** = *None*

    secure socket layer object



FilterStorage
=============

Helper class to store metrics in multiple standard storages.
Additionally filters can be provided to filter metrics which will be provided to storages.

- ``storages``: **List[Storage]**

    list of storages

- ``filter``: **Optional[List[str]]** = *None*

    list of filters




NOPAnomalyDetector
==================

Dummy detector which does nothing.



NOPAllocator
============

Dummy allocator which does nothing.



AllocationConfiguration
=======================


- ``cpu_quota_period``: **Numeric** = *1000*

    Default value for cpu.cpu_period [ms] (used as denominator).

- ``cpu_shares_unit``: **Numeric** = *1000*

    Multiplier of AllocationType.CPU_SHARES allocation value.
    E.g. setting 'CPU_SHARES' to 2.0 will set 2000 shares effectively
    in cgroup cpu controller.

- ``default_rdt_l3``: **Str** = *None*

    Default resource allocation for last level cache (L3)
    for root RDT group. Root RDT group is used as default group for all tasks,
    unless explicitly reconfigured by allocator.
    `None` (the default value) means no limit (effectively set to maximum available value).

- ``default_rdt_mb``: **Str** = *None*

    Default resource allocation for memory bandwitdh
    for root RDT group. Root RDT group is used as default group for all tasks,
    unless explicitly reconfigured by allocator.
    `None` (the default value) means no limit (effectively set to maximum available value).




StaticNode
==========

Simple implementation of Node that returns tasks based on
provided list on tasks names.

Tasks are returned only if corresponding cgroups exists:

- ``/sys/fs/cgroup/cpu/(task_name)``
- ``/sys/fs/cgroup/cpuacct/(task_name)``
- ``/sys/fs/cgroup/perf_event/(task_name)``

Otherwise, the item is ignored.

Arguments:

- ``tasks``: **List[Str]**
- ``require_pids``: **bool** = *False*
- ``default_labels``: **Dict[Str, Str]** = *{}*
- ``default_resources``: **Dict[Str, Union[Str, float, int]]** = *{}*
- ``tasks_labels``: **Optional[Dict[str, Dict[str, str]]]** = *None*



NUMAAllocator
=============


Allocator aimed to minimize remote NUMA memory accesses for processes.

- ``algorithm``: **NUMAAlgorithm** = *'fill_biggest_first'*:

    User can choose from options: *'fill_biggest_first'*, *'minimize_migration'*
    to specify policy determining which task is chosen to be pinned.

    - *'fill_biggest_first'*

        Algorithm only cares about sum of already pinned task's memory to each numa node.
        In each step tries to pin the biggest possible task to numa node, where sum of
        pinned task is the lowest.

    - *'minimize_migrations'*

        Algorithm tries to minimize amount of memory which needs to be remigrated
        between numa nodes.  Into consideration takes information: where a task
        memory is allocated (on which NUMA nodes), which are nodes where the sum
        of pinned memory is the lowest and which are nodes where most
        free memory is available.

- ``loop_min_task_balance``: **float** = *0.0*:

    Minimal value of task_balance so the task is not skipped during rebalancing analysis
    by default turn off, none of tasks are skipped due to this reason


- ``free_space_check``: **bool** = *False*:

    If True, then do not migrate if not enough space on target numa node.


- ``migrate_pages``: **bool** = *True*:

    If use syscall "migrate pages" (forced, synchronous migrate pages of a task)


- ``migrate_pages_min_task_balance``: **Optional[float]** = *0.95*:

    Works if migrate_pages == True. Then if set tells,
    when remigrate pages of already pinned task.
    If not at least ``migrate_pages_min_task_balance * TASK_TOTAL_SIZE``
    bytes of memory resides on pinned node, then
    tries to remigrate all pages allocated on other nodes to target node.


- ``cgroups_cpus_binding``: **bool** = *True*:

    cgroups based cpu pinning


- ``cgroups_memory_binding``: **bool** = *False*:

    cgroups based memory binding


- ``cgroups_memory_migrate``: **bool** = *False*:

    cgroups based memory migrating; can be used only when
    cgroups_memory_binding is set to True


- ``dryrun``: **bool** = *False*:

    If set to True, do not make any allocations - can be used for debugging.




StaticAllocator
===============

Simple allocator based on rules defining relation between task labels
and allocation definition (set of concrete values).

The allocator reads allocation rules from a yaml file and directly
from constructor argument (passed as python dictionary).
Refer to configs/extra/static_allocator_config.yaml to see sample
input file for StaticAllocator.

A rule is an object with three fields:

- name,
- labels (optional),
- allocations.

First field is just a helper to name a rule.
Second field contains a dictionary, where each key is a task's label name and
the value is a regex defining the matching set of label values. If the field
is not included then all tasks match the rule.
The third field is a dictionary of allocations which should be applied to
matching tasks.

If there are multiple matching rules then the rules' allocations are merged and applied.

Arguments:

- ``rules``: **List[dict]** = *None*

    Direct way to pass rules.

- ``config``: **Path** = *None*

    Filepath of yaml config file with rules.



SSL
===


Common configuration for SSL communication.

- ``server_verify``: **Union[bool, Path(absolute=True, mode=os.R_OK)]** = *True*
- ``client_cert_path``: **Optional[Path(absolute=True, mode=os.R_OK)]** = *None*
- ``client_key_path``: **Optional[Path(absolute=True, mode=os.R_OK)]** = *None*




TaskLabelRegexGenerator
=======================

Generate new label value based on other label value.



