===========================
Control algorithm interface
===========================

Introduction
------------

Control interface allows to provide control logic based on gathered platform and resources metrics and enforce isolation
on compute resources (cpu, cache and access).

Configuration 
-------------

Example of minimal configuration to use ``ControlRunner`` structure in
configuration file  ``config.yaml``:

.. code:: yaml

    runner: !ControlRunner
      node: !MesosNode
      delay: 1                                 
      allocator: !ExampleAllocator

Provided  ``ControlRunner`` class has following required and optional attributes.

.. code:: python

    @dataclass
    class ControlRunner:

        # Required
        node: MesosNode
        allocator: Allocator

        # Optional with default values
        delay: float = 1.                       # callback function call interval [s] 
        allocations: AllocationConfiguration = AllocationConfiguration()
        metrics_storage: Storage = LogStorage()         # stores internal and input metrics for control algorithm
        allocations_storage: Storage = LogStorage()     # stores any allocations issued on tasks
        anomalies_storage: Storage = LogStorage()       # stores any detected anomalies during control iteration

``AllocationsConfigurations`` structure contains static configuration to perform normalization of specific resource allocations.

.. code-block:: python

    @dataclass
    class AllocationConfiguration:

        # Default value for cpu.cpu_period [ms] (used as denominator).
        cpu_quota_period : int = 100               

        # Number of minimum shares, when ``cpu_shares`` allocation is set to 0.0.
        cpu_min_shares: int = 2                   
        # Number of shares to set, when ``cpu_shares`` allocation is set to 1.0.
        cpu_max_shares: int = 10000               

``Allocator`` structure and ``allocate`` resource callback function
--------------------------------------------------------------------
        
``Allocator`` class must implement at least one function with following signature:

.. code:: python

    class Allocator(ABC):

        def allocate(self,
                platform: Platform,
                tasks_measurements: TasksMeasurements,
                tasks_resources: TasksResources,
                tasks_labels: TasksLabels,
                tasks_allocations: TasksAllocations,             
            ) -> (TasksAllocations, List[Anomaly], List[Metric]):
            ...


Control interface reuses existing ``Detector`` input and metric structures. Please use `detection document <detection.rst>`_ 
for further reference on ``Platform``, ``TaskResources``, ``TasksMeasurements``, ``Anomaly`` and ``TaskLabels`` structures.

``TasksAllocations`` structure is a mapping from task identifier to allocations and defined as follows:

.. code:: python
    
    TaskId = str
    TasksAllocations = Dict[TaskId, TaskAllocations]
    TaskAllocations = Dict[AllocationType, float]

    # example
    tasks_allocations = {
        'some-task-id': {
            'cpu_quota': 0.6,
            'cpu_shares': 0.8,
        },
        'other-task-id': {
            'cpu_quota': 0.6,
        }
        ...
    }

This structure is used as an input representing actually enforced configuration and as an output for desired allocations that will be applied in the current ``ControlRunner`` iteration.

There is no need to actually returns all allocations for every tasks every time. The ``ControlRunner`` is stateful (state is kept on OS level) and applies only
those allocation for specified tasks returned during iteration if needed. Note that, if ``OWCA`` service is restarted, then already applied allocations will not be reset (
current state of allocation on system will be read and provided as input).

Supported allocations types
---------------------------

Following builtin allocations types are supported:

- ``cpu_quota`` - CPU Bandwidth Control called quota 
- ``cpu_shares`` - CPU shares for Linux CFS 
- ``memory_bandwidth`` - Limiting memory bandwidth (Intel MBA)
- ``llc_cache`` - Maximum cache occupancy (Intel CAT)
- ``rdt_MB`` -  User specified available bandwidth
- ``rdt_L3`` - User specified cache bit mask

The builtin allocation types are defined using following ``AllocationType`` enumeration:

.. code-block:: python

    class AllocationType(Enum, str):

        QUOTA = 'cpu_quota'
        SHARES = 'cpu_shares'
        MEMORY_BANDWIDTH = 'memory_bandwidth'
        LLC_CACHE = 'llc_cache'
        RDT_MB = 'rdt_MB'
        RTD_L3 = 'rtd_L3'

Details of **cpu_quota** allocation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``cpu_quota`` is normalized in respect to whole system capacity (all logical processor) that will be applied on cgroups cpu subsystem
using CFS bandwidth control.

For example, with default ``cpu_period`` set to **100ms** on machine with **16** logical processor, setting ``cpu_quota`` to **0.25**, which semantically means
hard limit on quarter on the available CPU resources, will effectively translated into **400ms** for(quota over **100ms** for period.

.. code-block:: python

    effective_cpu_quota = cpu_quota * cpu_period

Refer to `Kerenl sched-bwc.txt <https://www.kernel.org/doc/Documentation/scheduler/sched-bwc.txt>`_ document for further reference.

Details of **cpu_shares** allocation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``cpu_shares`` is normalized to values given in ``AlloctionConfiguraiton`` structure:

- **1.0** will be translated into ``max_cpu_shares``
- **0.0** will be translated into ``min_cpu_shares``

and values between will be normalized according following formula:

.. code-block:: python

    effective_cpu_shares = cpu_shares * (max_cpu_shares - min_cpu_shares) + min_cpu_shares

Refer to `Kernel sched-design <https://www.kernel.org/doc/Documentation/scheduler/sched-design-CFS.txt>`_ document for further reference.


Details of **llc_cache** allocation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Allocation for LLC cache allocation will be normalized to all available cache ways and rounded to minimum required number of consecutive ways.
Additionally will be distributed across workloads to minimize both overlap of cache ways for across all tasks (if possible) and amount of reconfiguration required to perform isolation.

Refer to `Kernel x86/intel_rdt_ui.txt`_ document for further reference.


Details of **memory_bandwidth** allocation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Allocation for memory bandwidth is set equally across all NUMA nodes and translated to percentage (as required by resctrl filesystem API).

Refer to `Kernel x86/intel_rdt_ui.txt`_ document for further reference.


Details of **rdt_MB** allocation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Allocation of available bandwidth is in given format:

.. code-block::

    MB:<cache_id0>=bandwidth0;<cache_id1>=bandwidth1;...

For example:

.. code-block::

    MB:0=20;1=100

Refer to `Kernel x86/intel_rdt_ui.txt`_ document for further reference.


Details of **rdt_L3** allocation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Allocation of cache bit mask is in given format:

.. code-block::

    L3:<cache_id0>=<cbm>;<cache_id1>=<cbm>;...

For example:

.. code-block::

    L3:0=fffff;1=fffff


Refer to `Kernel x86/intel_rdt_ui.txt`_ document for further reference.


Extended topology information
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Platform object will provide enough infomration to be able to construct raw configuration for rdt resources, including:

- number of cache_ways, number of minimum number of cache ways required to allocate
- number of sockets

based on ``/sys/fs/resctrl/info/`` and ``procfs``

.. code-block:: python

    class Platform:
        ...

        rdt_min_cbm_bits: str
        rdt_cbm_mask: str
        rdt_min_bandwidth: str
        ...


Refer to `Kernel x86/intel_rdt_ui.txt`_ document for further reference.

Allocations metrics
-------------------

Returned allocations will be encode as metrics and stored using storage.

When stored using `KafkaStorage` returned allocations will be encoded as follows in ``Prometheus`` exposition format:


.. code-block:: ini

    allocation(task_id='some-task-id', type='llc_cache', ...<other common and task specific labels>) 0.2 1234567890000
    allocation(task_id='some-task-id', type='cpu_quota', ...<other common and task specific labels>) 0.2 1234567890000


.. _`Kernel x86/intel_rdt_ui.txt`: https://www.kernel.org/doc/Documentation/x86/intel_rdt_ui.txt
