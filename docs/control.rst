===========================
Control algorithm interface
===========================


Introduction
------------

Control interface allows to provide control logic based on gathered platform and resources metrics and enforce isolation
on compute resources (cpu, cache and access).


You can configure system to reconfigure allocations on specific resources, but using ``ControlRunner`` type in
configuration file  ``config.yaml`` in following way:

.. code:: yaml

    runner: !ControlRunner
      node: !MesosNode
      delay: 1.                                 # [s]
      controller: !AllocationController

Provided by OWCA ``ControlRunner`` class has following required and optional properties.

.. code:: python

    @dataclass
    class ControlRunner:

        # Required
        node: MesosNode

        # Optional with default values
        delay: float = 1.                       # callback function call interval [s] 
        allocations: !AllocationsConfigurations
            cpu_min_shares: 100                   
            cpu_max_shares: 1000               

        # Optional and empty
        metrics_storage: Storage = None         # stores internal and input metrics for control algorithm
        allocations_storage: Storage = None     # stores any allocations issued on tasks

``AllocationsConfigurations`` structure contains static configuration for normalizing resource allocations.

.. code-block:: python

    @dataclass
    class AllocationsConfigurations: # Configuration for specific resources.

        # Default value for cpu.cpu_period [ms] (used as denominator).
        cpu_quota_period : int = 100               

        # Number of minimum shares, when ``cpu_shares`` allocation is set to 0.0.
        cpu_min_shares: int = 2                   

        # Number of shares to set, when ``cpu_shares`` allocation is set to 1.0.
        cpu_max_shares: int = 10000               

``AllocationController`` and ``allocate`` resource callback function
--------------------------------------------------------------------
        
``AllocationController`` class must implement one function with following signature:

.. code:: python

    class AlloctionController(ABC):

        def allocate(self,
                platform: Platform,
                tasks_measurements: TasksMeasurements,
                tasks_resources: TasksResources,
                tasks_labels: TasksLabels,
                tasks_allocations: TasskAllocations,             # input TasksAllocations represent the current state of system.
            ) -> (List[TasksAllocations], List[Metric]):
            ...


Control interface reuses existing ``Detector`` input and metric structures. Please use `detection document <detection.rst>`_ 
for further reference on ``Platform``, ``TaskResources``, ``TasksMeasurements`` and ``TaskLabels`` structures.

``TasksAllocations`` structure is a mapping from task identifier to allocations. 
and  defined as follows:

.. code:: python
    
    TaskId = str
    TasksAllocations = Dict[TaskId, TaskAllocations]
    TaskAllocations = Dict[str, float]

    # example
    tasks_allocations = {
        'some-task-id': {
            'cpu_quota': 0.6,
            'cpu_shares': 0.8
        },
        'other-task-id': {
            'cpu_quota': 0.6,
        }
        ...
    }

This structure is used as an input representing actually enforced configuration and as an output for desired allocations that will be applied in ``ControlRunner`` iteration.

There is no need to actually returns all allocations for every tasks every time. The ``ControlRunner`` is stateful (state is kept on OS level) and applies only
those allocation for specified tasks returned during iteration if needed.. Note that, if ``OWCA`` service is restarted then, already applied allocations will not be reset (
current state of allocation on system will be read).

Supported resources types
-------------------------

Following builtin resources are supported:

- ``cpu_quota`` - CPU Bandwidth Control called quota 
- ``cpu_shares`` - CPU shares for Linux CFS 
- ``memory_bandwidth`` - Limiting memory bandwidth (Intel MBA)
- ``llc_cache`` - Maximum cache occupancy (Intel CAT)

The builtin resources are defined using following enumeration:

.. code-block:: python

    class AllocatableResources(Enum):

        QUOTA = 'cpu_quota'
        SHARES = 'cpu_shares'
        MEMORY_BANDWIDTH = 'memory_bandwidth'
        LLC_CACHE = 'llc_cache'

Details of `cpu_quota` allocation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``cpu_quota`` is normalized in respect to whole system capacity (all logical processor) that will be applied on cpu cgroup subsystem
using CFS bandwidth control.

For example, with default ``cpu_period`` set to **100ms** on machine with **16** logical processor, setting ``cpu_quota`` to **0.25**, which semantically means
hard limit on quarter on the available CPU resources, will effectively translated into **400ms**.

Details of `cpu_shares` allocation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``cpu_shares`` is normalized to values given in ``AlloctionConfiguraiton`` structure:

- **1.0** will be translated into ``max_cpu_shares``.
- **0.0** will be translated into ``min_cpu_shares``.

Details of `llc_cache` allocation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Allocation for LLC cache allocation will be normalized to all available cache ways and rounded to minimum required number 
and distributed across workloads to minimize both overlap of cache ways for across all tasks (if possible) and amount of reconfiguration required to perform isolation.

Details of `memory_bandwidth` allocation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Allocation for memory bandwidth is set equally across all NUMB nodes and translated to percentage (as required by resctrl filesystem API).
