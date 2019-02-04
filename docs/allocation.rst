===============================
Allocation algorithm interface
===============================

**This software is pre-production and should not be deployed to production servers.**

Note: **This API is not considered stable, but work in progress** - please see https://github.com/intel/owca/pull/10 for status of implementation.

.. contents:: Table of Contents

Introduction
------------

Resource allocation interface allows to provide control logic based on gathered platform and resources metrics and enforce isolation
on compute resources (cpu, cache and memory).

Configuration 
-------------

Example of minimal configuration to use as ``AllocationRuner`` structure in
configuration file  ``config.yaml``:

.. code:: yaml

    # Basic minimal configuration to dump metrics on stderr with NOPAnomaly detector
    runner: !AllocationRunner
      ignore_privileges_check: true
      node: !MesosNode
        mesos_agent_endpoint: 'http://127.0.0.1:5051'
      action_delay: 4.
      metrics_storage: !LogStorage
        output_filename: metrics.logs
      anomalies_storage: !LogStorage
        output_filename: anomalies.logs
      allocations_storage: !LogStorage
        output_filename: allocations.logs
      allocator: !StaticAllocator
        config: /home/ppalucki/owca/example/static_alloc_config.yaml
      rdt_enabled: true

Provided  ``AllocationRunner`` class has the following required and optional attributes.

.. code:: python

    @dataclass
    class AllocationRunner:

        # Required
        node: nodes.Node
        allocator: Allocator
        metrics_storage: storage.Storage                # stores internal and input metrics for allocation algorithm
        anomalies_storage: storage.Storage              # stores any detected anomalies during allocation iteration
        allocations_storage: storage.Storage            # stores any allocations issued on tasks

        # Optional
        action_delay: float = 1.                        # callback function call interval [s]
        rdt_enabled: bool = True
        rdt_mb_control_enabled: bool = None  # None means will be automatically set during configure_rdt
        extra_labels: Dict[str, str] = field(default_factory=dict)
        ignore_privileges_check: bool = False
        allocation_configuration: AllocationConfiguration = \
            field(default_factory=AllocationConfiguration)


``AllocationConfigurations`` structure contains static configuration to perform normalization of specific resource allocations.

.. code-block:: python

    @dataclass
    class AllocationConfiguration:

        # Default value for cpu.cpu_period [ms]
        cpu_quota_period: int = 1000

        # Multipler of AllocationType.CPU_SHARES allocation value. E.g. setting
        # 'CPU_SHARES' to 2.0 will set 2000 (with default values) effectively
        # in cgroup cpu controlller.
        cpu_shares_unit: int = 1000

        # Default Allocation for default root group during initilization.
        # It will be used as default for all tasks (None will set to maximum available value).
        default_rdt_l3: str = None
        default_rdt_mb: str = None

``Allocator`` structure and ``allocate`` resource callback function
--------------------------------------------------------------------
        
``Allocator`` class must implement one function with following signature:

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

Allocation interface reuses existing ``Detector`` input and metric structures. Please refer to `detection document <detection.rst>`_ 
for further reference on ``Platform``, ``TaskResources``, ``TasksMeasurements``, ``Anomaly`` and ``TaskLabels`` structures.

``TasksAllocations`` structure is a mapping from task identifier to allocations and defined as follows:

.. code:: python

    TaskId = str
    TasksAllocations = Dict[TaskId, TaskAllocations]
    TaskAllocations = Dict[AllocationType, Union[float, RDTAllocation]]

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


Please refer to `rdt`_ for definition of ``RDTAllocation``.

This structure is used as an input representing currently enforced configuration and as an output representing desired allocations that will be applied in the current ``AllocationRunner`` iteration.

``allocate`` function  may return ``TaskAllocations`` for some tasks only. Resources allocated to tasks that no returned ``TaskAllocations`` describes will not be affected.

The ``AllocationRunner`` is stateful and relies on operating system to store the state. 

Note that, if ``OWCA`` service is restarted, then already applied allocations will not be reset 
(current state of allocation on system will be read and provided as input).

Supported allocations types
---------------------------

Following built-in allocations types are supported:

- ``cpu_quota`` - CPU Bandwidth Control called quota (normalized)
- ``cpu_shares`` - CPU shares for Linux CFS (normalized)
- ``rdt`` - Intel RDT (raw access)

The built-in allocation types are defined using following ``AllocationType`` enumeration:

.. code-block:: python

    class AllocationType(Enum, str):

        QUOTA = 'cpu_quota'
        SHARES = 'cpu_shares'
        RDT = 'rdt'

cpu_quota
^^^^^^^^^

``cpu_quota`` is normalized in respect to whole system capacity (all logical processor) and will be applied using cgroups cpu subsystem
using CFS bandwidth control.

For example, with default ``cpu_period`` set to **100ms** on machine with **16** logical processor, setting ``cpu_quota`` to **0.25**, means that
hard limit on quarter on the available CPU resources, will effectively translated into **400ms** quota.

Setting it to or above 1.0, means disabling the hard limit at all (effectivelty set to it to -1 in tego cgroup filesystem).
Setting to to 0.0 or close to zero, limit the allowed time to mimimum (1ms).

Base ``cpu_period`` value is configured in ``AllocationConfiguration`` structure during ``AllocationRunner`` initialization.

Formula for calculating quota for cgroup subsystem:

.. code-block:: python

    effective_cpu_quota = cpu_quota_normalized * allocation_configuration.cpu_quota_period * platform_cpus

Refer to `Kernel sched-bwc.txt <https://www.kernel.org/doc/Documentation/scheduler/sched-bwc.txt>`_ document for further reference.

cpu_shares
^^^^^^^^^^

``cpu_shares`` value is normalized against configured ``AllocationConfiguration.cpu_shares_unit``.

- **1.0** will be translated into ``AllocationConfiguration.cpu_shares_unit``
- **0.0** will be translated into mimimum numper of shares allowed by system (effectively "2").

.. code-block:: python

    effective_cpu_shares = cpu_shares_normalized * AllocationConfiguration.cpu_shares_unit

Refer to `Kernel sched-design <https://www.kernel.org/doc/Documentation/scheduler/sched-design-CFS.txt>`_ document for further reference.


rdt
^^^

.. code-block:: python

    @dataclass
    class RDTAllocation:
        name: str = None  # defaults to TaskId from TasksAllocations
        mb: str = None  # optional - when no provided doesn't change the existing allocation
        l3: str = None  # optional - when no provided doesn't change the existing allocation

You can use ``RDTAllocation`` structure to configure Intel RDT available resources.

``RDTAllocation`` wraps resctrl ``schemata`` file. Using ``name`` property allows one to specify name for control group to be used
for given task to save limited CLOSids and isolate RDT resources for multiple containers at once.

``name`` field is optional and if not provided, the ``TaskID`` from parent structure will be used.

Allocation of available bandwidth for ``mb`` field is given format:

.. code-block::

    MB:<cache_id0>=bandwidth0;<cache_id1>=bandwidth1

expressed in percentage points as described in `Kernel x86/intel_rdt_ui.txt <https://www.kernel.org/doc/Documentation/x86/intel_rdt_ui.txt>`_.

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


Extended topology information
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Platform object will provide enough information to be able to construct raw configuration for rdt resources, including:

- number of cache ways, number of minimum number of cache ways required to allocate
- number of sockets

based on ``/sys/fs/resctrl/info/`` and ``procfs``

.. code-block:: python

    class Platform:
        ...

        # rdt information
        rdt_mb_control_enabled: bool     # based on 'MB:' in /sys/fs/resctrl/schemata
        rdt_cbm_mask: Optional[str]      # based on /sys/fs/resctrl/info/L3/cbm_mask
        rdt_min_cbm_bits: Optional[str]  # based on /sys/fs/resctrl/info/L3/min_cbm_bits

        ...


Refer to `Kernel x86/intel_rdt_ui.txt <https://www.kernel.org/doc/Documentation/x86/intel_rdt_ui.txt>`_ document for further reference.

``TaskAllocations`` metrics
----------------------------

Returned ``TaskAllocations`` will be encoded as metrics and logged using ``Storage``.

When stored using ``KafkaStorage`` returned ``TaskAllocations`` will be encoded in ``Prometheus`` exposition format:

.. code-block:: ini

    # TYPE allocation gauge
    allocation{allocation_type="cpu_quota",cores="28",cpus="56",host="igk-0107",owca_version="0.1.dev252+g7f83b7f",sockets="2",task_id="root-staging13-stress_ng-default--0-0-6d1f2268-c3dd-44fd-be0b-a83bd86b328d"} 1.0 1547663933289
    allocation{allocation_type="cpu_shares",cores="28",cpus="56",host="igk-0107",owca_version="0.1.dev252+g7f83b7f",sockets="2",task_id="root-staging13-stress_ng-default--0-0-6d1f2268-c3dd-44fd-be0b-a83bd86b328d"} 0.5 1547663933289
    allocation{allocation_type="rdt_l3_cache_ways",cores="28",cpus="56",domain_id="0",group_name="be",host="igk-0107",owca_version="0.1.dev252+g7f83b7f",sockets="2",task_id="root-staging13-stress_ng-default--0-0-6d1f2268-c3dd-44fd-be0b-a83bd86b328d"} 1 1547663933289
    allocation{allocation_type="rdt_l3_cache_ways",cores="28",cpus="56",domain_id="1",group_name="be",host="igk-0107",owca_version="0.1.dev252+g7f83b7f",sockets="2",task_id="root-staging13-stress_ng-default--0-0-6d1f2268-c3dd-44fd-be0b-a83bd86b328d"} 1 1547663933289
    allocation{allocation_type="rdt_l3_mask",cores="28",cpus="56",domain_id="0",group_name="be",host="igk-0107",owca_version="0.1.dev252+g7f83b7f",sockets="2",task_id="root-staging13-stress_ng-default--0-0-6d1f2268-c3dd-44fd-be0b-a83bd86b328d"} 2 1547663933289
    allocation{allocation_type="rdt_l3_mask",cores="28",cpus="56",domain_id="1",group_name="be",host="igk-0107",owca_version="0.1.dev252+g7f83b7f",sockets="2",task_id="root-staging13-stress_ng-default--0-0-6d1f2268-c3dd-44fd-be0b-a83bd86b328d"} 2 1547663933289

    # TYPE allocation_duration gauge
    allocation_duration{cores="28",cpus="56",host="igk-0107",owca_version="0.1.dev252+g7f83b7f",sockets="2"} 0.002111196517944336 1547663933289

    # TYPE allocations_count counter
    allocations_count{cores="28",cpus="56",host="igk-0107",owca_version="0.1.dev252+g7f83b7f",sockets="2"} 660 1547663933289

    # TYPE allocations_ignored_count counter
    allocations_ignored_count{cores="28",cpus="56",host="igk-0107",owca_version="0.1.dev252+g7f83b7f",sockets="2"} 0 1547663933289
