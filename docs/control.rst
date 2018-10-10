===========================
Control algorithm interface
===========================


Introduction
------------

Control interface allows to provide control logic based on gathered platform and resources metrics and enforce isolation
on compute resources (cpu, cache and access).

Control interface reuses existing Detector input and metric structures. Please use :ref:`detection document <detection.rst>`_ 
for further reference on ``Platform``, ``TaskResources``, ``TasksMeasurements`` and ``TaskLabels`` structures.

:ref:`text <path>`

Allocate resource callback 
--------------------------

You can configure system to reconfigure allocations on specific resources, but using ``ControlRunner`` type in
configuration file  ``config.yaml`` in following way:

.. code:: yaml

    runner: !ControlRunner
      node: !MesosNode
      delay: 1.                                 # [s]
      controller: Controller


``ControlRunner`` structure has following required and optional properties.


.. code:: yaml

    @dataclass
    class ControlRunner:

        # required
        node: MesosNode

        # optional with default values
        allocations: !AllocationsConfigurations
            quota_period = 100 
            cpu_min_shares = 2

        # optional
        delay: float = 1.                       # [s] 
        metrics_storage: Storage = None         # stores internal and input metrics for controll algorithm
        allocations_storage: Storage = None     # stores any allocations issued on tasks

        
``AllocationController`` class must implement following interface:

.. code:: python

    class AlloctionController(ABC):

        def allocate(
                self,
                platform: Platform,
                tasks_measurements: TasksMeasurements,
                tasks_resources: TasksResources,
                tasks_labels: TasksLabels,
                tasks_allocations: TasskAllocations,             # input TasksAllocations represent the current state of system.
            ) -> (List[TasksAllocations], List[Metric]):
            ...


where ``TasksAllocations`` structure is a mapping from task identfier to allocations and used as an input representing actually enforced configuration
and as an output for desired one.

There is no need to actually returns all allocations for every tasks every time. The ``ControlRunner`` is statefull (state is kept on OS level) and enforces only
those allocation for specified tasks returned during iteration. Note that, if ``OWCA`` service is restarted then, already applied allocations will not be reset.

.. code:: python
    
    TasksAllocations = Dict[TaskId, TaskAllocations]

    tasks_allocations = 


and ``TaskResources`` are mapping from resource name and resource allocation.

.. code:: python

    TaskAllocations = Dict[str, float]

    # Examples:
    task_allocations = dict(
        cpu_quota = 0.1,
        cpu_shares = 

        
    )


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
        MEMORY_BANDWIDTH = 'memory_bandwidth'   # only when supported by HW
        LLC_CACHE = 'llc_cache                  # only when supported by HW



CPU Quota managment
^^^^^^^^^^^^^^^^^^^












    




    




    


