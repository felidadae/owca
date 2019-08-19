===============================
Allocation algorithm interface
===============================

**This software is pre-production and should not be deployed to production servers.**

.. contents:: Table of Contents

Introduction
------------

Resource allocation interface allows to provide plugin with resource control logic. Such component
can enforce isolation based on platform and tasks resources usage metrics.

To enable allocation feature, the agent has to be configured to use the ``AllocationRunner`` component.
The runner requires `Allocator`_, to be provided. Allocation decisions are based
on results from ``allocate`` method from `Allocator`_.

Configuration 
-------------

Example of minimal configuration that uses ``AllocationRunner``:

.. code:: yaml

    # Basic configuration to dump metrics on stderr with NOPAnomaly detector
    runner: !AllocationRunner
      node: !MesosNode
      allocator: !NOPAllocator

``runner`` is responsible for discovering tasks running on ``node``, provides this information to
``allocator`` and then reconfigures resources like cpu shares/quota, cache or memory bandwidth.
All information about existing allocations, detected anomalies or other metrics are stored in
corresponding storage classes.

``AllocationRunner`` class has the following required and optional attributes:

.. code-block:: python

    class AllocationRunner(MeasurementRunner):
        """Runner is responsible for getting information about tasks from node,
        calling allocate() callback on allocator, performing returning allocations
        and storing all allocation related metrics in allocations_storage.

        Because Allocator interface is also detector, we store serialized detected anomalies
        in anomalies_storage and all other measurements in metrics_storage.

        Arguments:
            node: component used for tasks discovery
            allocator: component that provides allocation logic
            metrics_storage: storage to store platform, internal, resource and task metrics
                (defaults to DEFAULT_STORAGE/LogStorage to output for standard error)
            anomalies_storage: storage to store serialized anomalies and extra metrics
                (defaults to DEFAULT_STORAGE/LogStorage to output for standard error)
            allocations_storage: storage to store serialized resource allocations
                (defaults to DEFAULT_STORAGE/LogStorage to output for standard error)
            action_delay: iteration duration in seconds (None disables wait and iterations)
                (defaults to 1 second)
            rdt_enabled: enables or disabled support for RDT monitoring and allocation
                (defaults to None(auto) based on platform capabilities)
            rdt_mb_control_required: indicates that MB control is required,
                if the platform does not support this feature the WCA will exit
            rdt_cache_control_required: indicates tha L3 control is required,
                if the platform does not support this feature the WCA will exit
            extra_labels: additional labels attached to every metric
                (defaults to empty dict)
            allocation_configuration: allows fine grained control over allocations
                (defaults to AllocationConfiguration() instance)
            remove_all_resctrl_groups (bool): remove all RDT controls groups upon starting
                (defaults to False)
            event_names: perf counters to monitor
                (defaults to instructions, cycles, cache-misses, memstalls)
            enable_derived_metrics: enable derived metrics ips, ipc and cache_hit_ratio
                (based on enabled_event names), default to False
            task_label_generators: component to generate additional labels for tasks
        """

        def __init__(
                self,
                node: nodes.Node,
                allocator: Allocator,
                metrics_storage: storage.Storage = DEFAULT_STORAGE,
                anomalies_storage: storage.Storage = DEFAULT_STORAGE,
                allocations_storage: storage.Storage = DEFAULT_STORAGE,
                action_delay: Numeric(0, 60) = 1.,  # [s]
                rdt_enabled: Optional[bool] = None,  # Defaults(None) - auto configuration.
                rdt_mb_control_required: bool = False,
                rdt_cache_control_required: bool = False,
                extra_labels: Dict[Str, Str] = None,
                allocation_configuration: Optional[AllocationConfiguration] = None,
                remove_all_resctrl_groups: bool = False,
                event_names: Optional[List[str]] = None,
                enable_derived_metrics: bool = False,
                task_label_generators: Dict[str, TaskLabelGenerator] = None,
        ):
        ...


``AllocationConfiguration`` contains static configuration to perform normalization of specific resource allocations.

.. code-block:: python

    @dataclass
    class AllocationConfiguration:
        # Default value for cpu.cpu_period [ms] (used as denominator).
        cpu_quota_period: Numeric(1000, 1000000) = 1000

        # Multiplier of AllocationType.CPU_SHARES allocation value.
        # E.g. setting 'CPU_SHARES' to 2.0 will set 2000 shares effectively
        # in cgroup cpu controller.
        cpu_shares_unit: Numeric(1000, 1000000) = 1000

        # Default resource allocation for last level cache (L3) and memory bandwidth
        # for root RDT group.
        # Root RDT group is used as default group for all tasks, unless explicitly reconfigured by
        # allocator.
        # `None` (the default value) means no limit (effectively set to maximum available value).
        default_rdt_l3: Str = None
        default_rdt_mb: Str = None

``Allocator``
--------------------------------------------------------------------

``Allocator`` subclass must implement an ``allocate`` function with following signature:

.. code:: python

    class Allocator(ABC):

        @abstractmethod
        def allocate(
                self,
                platform: Platform,
                tasks_measurements: TasksMeasurements,
                tasks_resources: TasksResources,
                tasks_labels: TasksLabels,
                tasks_allocations: TasksAllocations,
        ) -> (TasksAllocations, List[Anomaly], List[Metric]):
            ...

All but ``TasksAllocations`` input arguments types are documented in `detection document <detection.rst>`_.

Both ``TaskAllocations`` and ``TasksAllocations`` structures are simple python dict types defined as follows:

.. code:: python

    class AllocationType(Enum, str):
        QUOTA = 'cpu_quota'
        SHARES = 'cpu_shares'
        RDT = 'rdt'
        CPUSET = 'cpu_set'

    TaskId = str
    TaskAllocations = Dict[AllocationType, Union[float, int, RDTAllocation]]
    TasksAllocations = Dict[TaskId, TaskAllocations]

    # example
    tasks_allocations = {
        'some-task-id': {
            'cpu_quota': 0.6,
            'cpu_shares': 0.8,
            'rdt': RDTAllocation(name='hp_group', l3='L3:0=fffff;1=fffff', mb='MB:0=20;1=5')
        },
        'other-task-id': {
            'cpu_quota': 0.5,
            'rdt': RDTAllocation(name='hp_group', l3='L3:0=fffff;1=fffff', mb='MB:0=20;1=5')
        }
        'one-another-task-id': {
            'cpu_quota': 0.7,
            'rdt': RDTAllocation(name='be_group', l3='L3:0=000ff;1=000ff', mb='MB:0=1;1=1'),
        }
        'another-task-with-own-rdtgroup': {
            'cpu_quota': 0.7,
            'rdt': RDTAllocation(l3='L3:0=000ff;1=000ff', mb='MB:0=1;1=1'),  # "another-task-with-own-rdtgroup" will be used as `name`
        }
        ...
    }


Please refer to `rdt`_ allocation type for definition of ``RDTAllocation`` structure.

``TasksAllocations`` is used as:

- an input representing currently enforced configuration,
- an output representing desired allocations that will be applied in the current ``AllocationRunner`` iteration.

``allocate`` function does not need to return ``TaskAllocations`` for all tasks.
For omitted tasks, allocations will not be affected.

``AllocationRunner`` is stateless and relies on operating system to store the state.

Note that, if the agent is restarted, then already applied allocations will not be reset 
(current state of allocation on system will be read and provided as input).

Supported allocations types
---------------------------

Following built-in allocations types are supported:

- ``cpu_quota`` - CPU Bandwidth Control called quota (normalized),
- ``cpu_shares`` - CPU shares for Linux CFS (normalized),
- ``rdt`` - Intel RDT resources.
- ``cpu_set`` - **experimental** support for cpu pinning(requires specific isolator for Mesos)

cpu_quota
^^^^^^^^^

``cpu_quota`` is normalized in respect to whole system capacity (all logical processor) and will be applied using cgroups cpu subsystem
using CFS bandwidth control.

Formula for calculating quota normalized to platform capacity:

.. code-block:: python

    effective_cpu_quota = cpu_quota * allocation_configuration.cpu_quota_period * platform.cpus

For example, with default ``cpu_period`` set to **100ms** on machine with **16** logical processor, setting ``cpu_quota`` to **0.25**, means that
hard limit on quarter on the available CPU resources, will effectively translated into **400ms** quota.

Note that, setting ``cpu_quota``:  

- to or above **1.0**, means disabling the hard limit at all (effectively set to it to -1 in cpu.cfs_quota_us),
- to **0.0**, limits the allowed time to the minimum allowed value (1ms).

CFS "period" is configured statically in ``AllocationConfiguration``.

Refer to `Kernel sched-bwc.txt <https://www.kernel.org/doc/Documentation/scheduler/sched-bwc.txt>`_ document for further reference.

cpu_shares
^^^^^^^^^^

``cpu_shares`` value is normalized against configured ``AllocationConfiguration.cpu_shares_unit``.

.. code-block:: python

    effective_cpu_shares = cpu_shares * allocation_configuration.cpu_shares_unit

Note that, setting ``cpu_shares``:  

- to **1.0** will be translated into ``AllocationConfiguration.cpu_shares_unit``
- to **0.0** will be translated into minimum number of shares allowed by system (effectively "2").

Refer to `Kernel sched-design <https://www.kernel.org/doc/Documentation/scheduler/sched-design-CFS.txt>`_ document for further reference.

rdt
^^^

.. code-block:: python

    @dataclass
    class RDTAllocation:
        name: str = None    # defaults to TaskId from TasksAllocations
        mb: str = None      # optional - when not provided does not change the existing allocation
        l3: str = None      # optional - when not provided does not change the existing allocation

You can use ``RDTAllocation`` class to configure Intel RDT resources.

``RDTAllocation`` wraps resctrl ``schemata`` file. Using ``name`` property allows to specify name for control group. 
Sharing control groups among tasks allows to save limited CLOSids resources.

``name`` field is optional and if not provided, the ``TaskID`` from parent ``TasksAllocations`` class will be used.

Allocation of available bandwidth for ``mb`` field is given format:

.. code-block::

    MB:<cache_id0>=bandwidth0;<cache_id1>=bandwidth1

expressed in percentage as described in `Kernel x86/intel_rdt_ui.txt <https://www.kernel.org/doc/Documentation/x86/intel_rdt_ui.txt>`_.

For example:

.. code-block::

    MB:0=20;1=100

If Software Controller is available and enabled during mount, the format is:

.. code-block::

    MB:<cache_id0>=bw_MBps0;<cache_id1>=bw_MBps1

where bw_MBps0 expresses bandwidth in MBps.


Allocation of cache bit mask for ``l3`` field is given format:

.. code-block::

    L3:<cache_id0>=<cbm>;<cache_id1>=<cbm>;...

For example:

.. code-block::

    L3:0=fffff;1=fffff


Note that the configured values are passed as is to resctrl filesystem without validation and in case of error, warning is logged.

Refer to `Kernel x86/intel_rdt_ui.txt <https://www.kernel.org/doc/Documentation/x86/intel_rdt_ui.txt>`_ document for further reference.


cpu_set
^^^^^^^
**Experimental** support for cpu pinning:

- requires specific isolator for Mesos
- may conflict with ``cpu manager`` feature in Kubernetes

TODO: example configuration

Extended topology information
-----------------------------

Platform object will provide enough information to be able to construct raw configuration for rdt resources, including:

- number of cache ways, number of minimum number of cache ways required to allocate
- number of sockets

based on ``/sys/fs/resctrl/info/`` and ``procfs``

.. code-block:: python

    class Platform:
        ...
        rdt_information: RDTInformation
        ...

    @dataclass
    class RDTInformation:
        cbm_mask: Optional[str]  # based on /sys/fs/resctrl/info/L3/cbm_mask
        min_cbm_bits: Optional[str]  # based on /sys/fs/resctrl/info/L3/min_cbm_bits
        rdt_mb_control_enabled: bool  # based on 'MB:' in /sys/fs/resctrl/info/L3/cbm_mask
        num_closids: Optional[int]  # based on /sys/fs/resctrl/info/L3/num_closids
        mb_bandwidth_gran: Optional[int]  # based on /sys/fs/resctrl/info/MB/bandwidth_gran
        mb_min_bandwidth: Optional[int]  # based on /sys/fs/resctrl/info/MB/bandwidth_gran

Refer to `Kernel x86/intel_rdt_ui.txt <https://www.kernel.org/doc/Documentation/x86/intel_rdt_ui.txt>`_ document for further reference.

``TaskAllocations`` metrics
----------------------------

Returned ``TasksAllocations`` will be encoded in Prometheus exposition format:

.. code-block:: ini

    # TYPE allocation gauge
    allocation{allocation_type="cpu_quota",cores="28",cpus="56",host="igk-0107",wca_version="0.1.dev252+g7f83b7f",sockets="2",task_id="root-staging13-stress_ng-default--0-0-6d1f2268-c3dd-44fd-be0b-a83bd86b328d"} 1.0 1547663933289
    allocation{allocation_type="cpu_shares",cores="28",cpus="56",host="igk-0107",wca_version="0.1.dev252+g7f83b7f",sockets="2",task_id="root-staging13-stress_ng-default--0-0-6d1f2268-c3dd-44fd-be0b-a83bd86b328d"} 0.5 1547663933289
    allocation{allocation_type="rdt_l3_cache_ways",cores="28",cpus="56",domain_id="0",group_name="be",host="igk-0107",wca_version="0.1.dev252+g7f83b7f",sockets="2",task_id="root-staging13-stress_ng-default--0-0-6d1f2268-c3dd-44fd-be0b-a83bd86b328d"} 1 1547663933289
    allocation{allocation_type="rdt_l3_cache_ways",cores="28",cpus="56",domain_id="1",group_name="be",host="igk-0107",wca_version="0.1.dev252+g7f83b7f",sockets="2",task_id="root-staging13-stress_ng-default--0-0-6d1f2268-c3dd-44fd-be0b-a83bd86b328d"} 1 1547663933289
    allocation{allocation_type="rdt_l3_mask",cores="28",cpus="56",domain_id="0",group_name="be",host="igk-0107",wca_version="0.1.dev252+g7f83b7f",sockets="2",task_id="root-staging13-stress_ng-default--0-0-6d1f2268-c3dd-44fd-be0b-a83bd86b328d"} 2 1547663933289
    allocation{allocation_type="rdt_l3_mask",cores="28",cpus="56",domain_id="1",group_name="be",host="igk-0107",wca_version="0.1.dev252+g7f83b7f",sockets="2",task_id="root-staging13-stress_ng-default--0-0-6d1f2268-c3dd-44fd-be0b-a83bd86b328d"} 2 1547663933289

    # TYPE allocation_duration gauge
    allocation_duration{cores="28",cpus="56",host="igk-0107",wca_version="0.1.dev252+g7f83b7f",sockets="2"} 0.002111196517944336 1547663933289

    # TYPE allocations_count counter
    allocations_count{cores="28",cpus="56",host="igk-0107",wca_version="0.1.dev252+g7f83b7f",sockets="2"} 660 1547663933289

    # TYPE allocations_ignored_count counter
    allocations_ignored_count{cores="28",cpus="56",host="igk-0107",wca_version="0.1.dev252+g7f83b7f",sockets="2"} 0 1547663933289


Generating additional labels for tasks
--------------------------------------
Please refer to `Generating additional labels for tasks <detection.rst>`_.