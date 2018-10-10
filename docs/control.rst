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
        allocations: AllocationsConfigurations = DefaultAllocationConfiguration()

        # Optional and empty
        metrics_storage: Storage = LogStorage()         # stores internal and input metrics for control algorithm
        allocations_storage: Storage = LogStorage()     # stores any allocations issued on tasks

``AllocationsConfigurations`` structure contains static configuration to perform normalization of resource allocations.

.. code-block:: python

    @dataclass
    class AllocationsConfigurations:

        # Default value for cpu.cpu_period [ms] (used as denominator).
        cpu_quota_period : int = 100               

        # Number of minimum shares, when ``cpu_shares`` allocation is set to 0.0.
        cpu_min_shares: int = 2                   
        # Number of shares to set, when ``cpu_shares`` allocation is set to 1.0.
        cpu_max_shares: int = 10000               

``Allocator`` structure and ``allocate`` resource callback function
--------------------------------------------------------------------
        
``Allocator`` class must implement one function with following signature:

.. code:: python

    class Allocator(ABC):

        def allocate(self,
                platform: Platform,
                tasks_measurements: TasksMeasurements,
                tasks_resources: TasksResources,
                tasks_labels: TasksLabels,
                tasks_allocations: TasskAllocations,             
            ) -> (List[TasksAllocations], List[Metric]):
            ...


Control interface reuses existing ``Detector`` input and metric structures. Please use `detection document <detection.rst>`_ 
for further reference on ``Platform``, ``TaskResources``, ``TasksMeasurements`` and ``TaskLabels`` structures.

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

The builtin allocation types are defined using following ``AllocationType`` enumeration:

.. code-block:: python

    class AllocationType(Enum, str):

        QUOTA = 'cpu_quota'
        SHARES = 'cpu_shares'
        MEMORY_BANDWIDTH = 'memory_bandwidth'
        LLC_CACHE = 'llc_cache'

Details of **cpu_quota** allocation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``cpu_quota`` is normalized in respect to whole system capacity (all logical processor) that will be applied on cgroups cpu subsystem
using CFS bandwidth control.

For example, with default ``cpu_period`` set to **100ms** on machine with **16** logical processor, setting ``cpu_quota`` to **0.25**, which semantically means
hard limit on quarter on the available CPU resources, will effectively translated into **400ms** for(quota over **100ms** for period.

Details of `cpu_shares` allocation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``cpu_shares`` is normalized to values given in ``AlloctionConfiguraiton`` structure:

- **1.0** will be translated into ``max_cpu_shares``
- **0.0** will be translated into ``min_cpu_shares``

and values between will be normalized according following formula:

.. code-block:: python

    effective_cpu_shares = cpu_shares * (max_cpu_shares - min_cpu_shares) + min_cpu_shares

Details of `llc_cache` allocation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Allocation for LLC cache allocation will be normalized to all available cache ways and rounded to minimum required number of consecutive ways.
Additionally will be distributed across workloads to minimize both overlap of cache ways for across all tasks (if possible) and amount of reconfiguration required to perform isolation.

Details of **memory_bandwidth** allocation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Allocation for memory bandwidth is set equally across all NUMA nodes and translated to percentage (as required by resctrl filesystem API).


Allocations metrics
-------------------

Returned allocations will be encode as metrics and stored using storage.

When stored using `KafkaStorage` returned allocations will be encoded as follows in ``Prometheus`` exposition format:


.. code-block:: ini

    allocation(task_id='some-task-id', type='llc_cache', ...<other comomn and task specific labels>) 0.2 1234567890000
    allocation(task_id='some-task-id', type='cores', ...<other comomn and task specific labels>) 0.2 1234567890000
