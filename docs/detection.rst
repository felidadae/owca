=========================================================
Anomaly detection algorithm interface and structures
=========================================================

**This software is pre-production and should not be deployed to production servers.**

.. contents:: Table of Contents

Terminology
-----------

- **Counter** type of metric - is a monotonically increasing counter,
- **Gauge** type of metric - value that can arbitrarily go up and down,
- **Task** represents single Mesos task, that matches single currently running Aurora job 
  instance and is running in single Linux container (using Mesos containerizer)

Check `Prometheus metrics types`_ for further reference

.. _`Prometheus metrics types`: https://prometheus.io/docs/concepts/metric_types


Supported orchestration systems
-------------------------------
We support both Mesos and Kubernetes (Kubernetes is currently supported only in the detect mode).

As a reference configuration file use one located in `configs`_ directory.

.. _`configs`: /configs


Detector callback API
----------------------

You can configure system to detect and report anomalies in following way in ``config.yaml``:

.. code-block:: yaml

    runner: !DetectionRunner
      node: !MesosNode
      delay: 1.                                 # [s]
      detector: !ExampleAnomalyDetector      # implementation of abstract AnomalyDetector class
        example_config_int: 1
        example_config_list: [1, 4]


where ``ExampleAnomalyDetector`` class must implement following interface:

.. code-block:: python

    class AnomalyDetector(ABC):

        def detect(self,
                    platform: Platform,
                    tasks_measurements: TasksMeasurements,
                    tasks_resources: TasksResources
                    ) -> (List[Anomaly], List[Metric]):
            ...


Example implementation:

.. code-block:: python

    class ExampleAnomalyDetector:

        def __init__(self, example_config_int, example_config_list):
            self.example_config_list = example_config_list
            ...

        def detect(self, platform: Platform,
                         tasks_measurements: TasksMeasurements,
                         tasks_resources: TasksResources,
                         tasks_labels: TasksLabels,
                         ) -> (List[Anomaly], List[Metric]):
            return [], []

All config values provided under ``detector`` key in configuration are treated as simple types (including lists and dict),
and are passed to constructor as keywords parameters.

To be able to use externally provided implementation it is necessary to register external component
using command line like this:

.. code:: bash

     wca --config some_mesos_config.yaml --component external_package.external_module:ContentionAnomalyDetector --level debug

After that you can instantiate this class using configuration file.

In example above ``ContentionAnomalyDetector`` implements all required methods of ``AnomalyDetector``.
            
``AnomalyDetector`` defines interface where ``Platform`` class represents capacity and utilization information 
covering whole system and ``TasksMeasurements`` class represents individual measurements for specific Mesos tasks running on this node.
``TasksResources``` class represents initial resource assigment as defined in orchestration software API (e.g. Mesos/Aurora).

Implementation of ``AnomalyDetector`` is responsible for returning new immutable instances of ``Anomaly`` and in 
specific case of "resource contention" should return subclass called ``ContentionAnomaly`` with extended context.
Additionally for debugging purposes can return any metrics that will be stored in persistent storage (e.g. Kafka).

``detect`` function is called in periodical manner depending on ``delay`` specified by configuration file.

Note, that most of measurements provided to detection algorithm are raw type of counters (monotonically increasing) and 
``AnomalyDetector`` is responsible to calculate derivative (difference) based on ``delay`` to calculate rate of increase 
(e.g. instructions per second, bytes per second and so on).


Types and structures
---------------------

Platform type definition
========================

.. code:: python
    
    # Helper types
    CpuId = int  # 0-based logical processor number (matches the value of "processor" in /proc/cpuinfo)

    @dataclass
    class Platform:
        
        # Topology:
        sockets: int  # number of sockets
        cores: int    # number of physical cores in total (sum over all sockets) 
        cpus: int     # logical processors equal to the output of "nproc" Linux command

        # Utilization (usage):
        cpus_usage: Dict[CpuId, int]     # counter like, sum of all modes based on /proc/stat "CPU line" with 10ms resolution expressed in [ms]
        total_memory_used: int      # [bytes] based on /proc/meminfo (gauge like) difference between MemTotal and MemAvail (or MemFree)

        timestamp: float # [unit timestamp] just after all necessary data was collected for platform object (time.time())


Example ``Platform`` instance
=============================

This is example of how to ``Platform`` instance looks like on two sockets "Intel(R) Xeon(R) CPU E5-2660 v4" with 377 GB RAM system:

.. code-block:: python

    platform = Platform(

        # Topology
        sockets = 2,
        cores = 28,
        cpus = 56,

        # Additional information about platform.
        cpu_model = "Intel(R) Xeon(R) CPU E5-2660 v4"

        # Utilization
        cpus_usage = {
            0: 4412451, 
            1: 4747332,
            ...,
            7: 3469724,
        },
        total_memory_used = 6759489536,  # in bytes (about 6GB)
    )


``Metric`` type
===============


.. code-block:: python

    MetricValue = Union[float, int]

    class MetricName(Enum, str):
        INSTRUCTIONS = 'instructions'
        CYCLES = 'cycles'
        LLC_MISSES = 'cache_misses'
        CPU_USAGE = 'cpu_usage'  # cpuacct.usage (total kernel and user space) in [ns]
        MEM_BW = 'memory_bandwidth' # counter like [bytes]

    class MetricType(Enum, str):
        GAUGE = 'gauge'      # arbitrary value (can go up and down)
        COUNTER = 'counter'  # monotonically increasing counter

    @dataclass
    class Metric:
        name: Union[str, MetricName]
        value: MetricValue
        labels: Dict[str, str]
        type: MetricType = None
        help: str = None

    Measurements = Dict[MetricName, MetricValue]


``TasksMeasurements`` and ``TaskResources`` types
=================================================

``TasksMeasurements`` is a nested mapping from task and metric name to value of metric. 
``TasksResources`` is a nested mapping from task and resource name to value of resource allocated
by task definition as defined in used orechstrator.

.. code:: python

    TaskId = str  # Mesos tasks id
    TasksMeasurements = Dict[TaskId, Measurements]
    TasksResources = Dict[TaskId, Dict[str,float]]

    # Example:
    tasks_measurements = {
        'ppalucki-devel-cassandra-0-f096985b-1f1e-4f94-b0b7-4728f5b476b2': {
            MetricName.INSTRUCTIONS: 12343141,
            MetricName.CYCLES: 2310124321,
            MetricName.LLC_MISSES: 21212312,
            MetricName.CPU_USAGE: 21212312,
            MetricName.MEM_BW: 21212312,
        },
        'ppalucki-devel-memcached-0-31db8f56-ea82-4404-8b58-baac8054900b': {
            MetricName.INSTRUCTIONS: 24233234,
            MetricName.CYCLES: 3110124321,
            MetricName.LLC_MISSES: 3293314311,
            MetricName.CPU_USAGE: 31212312,
            MetricName.MEM_BW: 51212312,
        },
    }

    tasks_resources = {
        'ppalucki-devel-cassandra-0-f096985b-1f1e-4f94-b0b7-4728f5b476b2': {
            'cpus': 8.0,
            'mem': 2000.0,
            'disk': 8000.0,
        },
    }
    # and example call of detect function
    anomalies, detection_metrics = anomaly_detector.detect(platform, tasks_measurements, tasks_resources)


``Anomaly`` type
=================

Anomaly represents instance of abnormal situation.
Every anomaly derives unique identifier to represents combinations of tasks and holds
context where and when (timestamp) this situation occurred.

In special case where tasks ids aren't provided the uuid is empty.

The context depends on type of anomaly. The only supported subtype is ``ContentionAnomaly`` type with the following structure.


``Anomaly`` type definition
===========================


.. code:: python

    class ContendedResource(Enum, str):

        MEMORY_BW = 'memory bandwidth'
        LLC = 'cache'
        CPUS = 'cpus'


    @dataclass
    class ContentionAnomaly:
        
        resource: ContendedResource
        contended_task_id: TaskId
        contending_task_ids: List[TaskId]

        # List of metrics describing context of contention
        metrics: List[Metric]

        # Type of anomaly (will be uses to label anomaly metrics)
        anomaly_type = 'contention'

        @property
        def uuid(self) -> str:
            """Globally unique identifier based only on tasks ids. Represents unique combination of tasks."""

            
``Anomaly`` creation example
============================

Example detection function returning one instance of ``Anomaly``:

.. code:: python

    def detect(platform, tasks_measurements, tasks_resources):

        anomalies = []

        all_tasks_ids = tasks_measurements.keys()

        if platform.total_memory_used > 0.8*platform.total_memory:
            anomalies.append(
                ContentionAnomaly(
                    contended_task_id = all_tasks_ids[0],
                    contending_task_ids = all_tasks_ids[1:],
                    resource = ContendedResource.MEMORY_BW,
                    metrics = [Metric(name="memory_usage_treshold", value=0.8*platform.total_memory type="gauge")]
                )
            )

        return anomalies



Representation of anomaly and metrics in persistent storage
------------------------------------------------------------


All stored information is labeled with platform information such as: *host*, *number of cores*, *number of sockets* and so on.
Additionally single anomaly object is serialized as multiple metrics that can be grouped by ``anomaly.uuid`` field to find correlated tasks.
If anomaly objects contains any additional related metrics, they will be marked with additional label type="anomaly" 
and uuid pointing to original contention instance.

Example message stored in Kafka using Prometheus exposition format:

.. code-block:: python

    # HELP instructions The total number of instructions executed by task.
    # TYPE instructions counter
    instructions{task_id="ppaluc-devel-memacache-0-sasd-cccc",sockets="2",cores="8",host="igk-016"} 123123123 1395066363000
    instructions{task_id="ppaluc-devel-cassandra-2-aaaa-bbbb",sockets="2",cores="8",host="igk-016"} 123123123 1395066363000
    ...

    # HELP cycles The total number of cycles executed by task.
    # TYPE cycles counter
    cycles{task_id="ppaluc-devel-memacache-0-sasd-cccc",sockets="2",cores="8",host="igk-016"} 329331431 1395066363000
    cycles{task_id="ppaluc-devel-cassandra-2-aaaa-bbbb",sockets="2",cores="8",host="igk-016"} 329331431 1395066363000
    ...

    # HELP llc_misses The total number of instructions executed by task.
    # TYPE llc_misses counter
    llc_misses{task_id="ppaluc-devel-memacache-0-sasd-cccc",sockets="2",cores="8",host="igk-016"} 1329331431 1395066363000
    llc_misses{task_id="ppaluc-devel-cassandra-2-aaaa-bbbb",sockets="2",cores="8",host="igk-016"} 3293314311 1395066363000
    ...


    # HELP platform_total_memory_usage_bytes The total usage of RAM in bytes.
    # TYPE platform_total_memory_usage_bytes gauge
    platform_total_memory_usage_bytes{host="igk-016"} 6759489536 1395066363000

    # HELP platform_llc_misses Number of misses system-wide.
    # TYPE platform_llc_misses counter
    platform_llc_misses{host="igk-016"} 1231231231 1395066363000

    # HELP platform_core_usage_ms Number of ms that given cpu was running (in all modes: kernel, user, irq handling and so on...)
    # TYPE platform_core_usage_ms counter
    platform_core_usage_ms{host="igk-016",cpu="0"} 4412451 1395066363000
    platform_core_usage_ms{host="igk-016",cpu="1"} 4747332 1395066363000

    # HELP platform_memory_bw Number of bytes transfered to and from socket and memory.
    # TYPE platform_memory_bw counter
    platform_memory_bw{host="igk-016",socket="0"} 23525923348480 1395066363000
    platform_memory_bw{host="igk-016",socket="1"} 13237177459112 1395066363000



    # HELP anomaly The total number of anomalies detected on host.
    # TYPE anomaly counter
    anomaly{type="contention", contended_task_id="task1", contending_task_id="task2",  resource="memory bandwidth", uuid="1234"} 1
    anomaly{type="contention", contended_task_id="task1", contending_task_id="task3", resource="memory bandwidth", uuid="1234"} 1
    memory_usage_treshold{contended_task_id="task1", uuid="1234", type="anomaly"} 10


**Note** that not all labels comments where showed for readability.
