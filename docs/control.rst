===========================
Control algorithm interface
===========================

.. contents:: Table of Contents

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
      action_delay: 1                                  # [s]
      allocator: !ExampleAllocator



Provided  ``ControlRunner`` class has following required and optional attributes.

.. code:: python

    @dataclass
    class ControlRunner:

        # Required
        node: MesosNode
        allocator: Allocator

        # Optional with default values
        action_delay: float = 1.                        # callback function call interval [s]
        # Default static configuration for allocation
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


Please refer to `rdt`_ for definition of RDTAllocation.

This structure is used as an input representing actually enforced configuration and as an output for desired allocations that will be applied in the current ``ControlRunner`` iteration.

There is no need to actually returns all allocations for every tasks every time. The ``ControlRunner`` is stateful (state is kept on OS level) and applies only
those allocation for specified tasks returned during iteration if needed. Note that, if ``OWCA`` service is restarted, then already applied allocations will not be reset (
current state of allocation on system will be read and provided as input).

Supported allocations types
---------------------------

Following builtin allocations types are supported:

- ``cpu_quota`` - CPU Bandwidth Control called quota (normalized)
- ``cpu_shares`` - CPU shares for Linux CFS (normalized)
- ``rdt`` - Intel RDT (raw access)

The builtin allocation types are defined using following ``AllocationType`` enumeration:

.. code-block:: python

    class AllocationType(Enum, str):

        QUOTA = 'cpu_quota'
        SHARES = 'cpu_shares'
        RDT = 'rdt'

cpu_quota
^^^^^^^^^

``cpu_quota`` is normalized in respect to whole system capacity (all logical processor) that will be applied on cgroups cpu subsystem
using CFS bandwidth control.

For example, with default ``cpu_period`` set to **100ms** on machine with **16** logical processor, setting ``cpu_quota`` to **0.25**, which semantically means
hard limit on quarter on the available CPU resources, will effectively translated into **400ms** for(quota over **100ms** for period.

.. code-block:: python

    effective_cpu_quota = cpu_quota * cpu_period

Refer to `Kerenl sched-bwc.txt <https://www.kernel.org/doc/Documentation/scheduler/sched-bwc.txt>`_ document for further reference.

cpu_shares
^^^^^^^^^^

``cpu_shares`` is normalized to values given in ``AlloctionConfiguraiton`` structure:

- **1.0** will be translated into ``max_cpu_shares``
- **0.0** will be translated into ``min_cpu_shares``

and values between will be normalized according following formula:

.. code-block:: python

    effective_cpu_shares = cpu_shares * (max_cpu_shares - min_cpu_shares) + min_cpu_shares

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

``RDTAllocation`` wraps resctrl ``schemata`` file. Using ``name`` property allow to one to specify name for control group to be used
for given task to save limited CLOSids and isolate RDT resources for multiple containers at once.

``name`` field is optional and if not provided, the ``TaskID`` from parent structure will be used.

Allocation of available bandwidth for ``mb`` field is given format:

.. code-block::

    MB:<cache_id0>=bw_MBps0;<cache_id1>=bw_MBps1

For example:

.. code-block::

    MB:0=20;1=100


Allocation of cache bit mask for ``l3`` field is given format:

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
