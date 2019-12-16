=====================================================
WCA - Workload Collocation Agent
=====================================================

.. image:: https://travis-ci.com/intel/workload-collocation-agent.svg?branch=master
    :target: https://travis-ci.com/intel/workload-collocation-agent

.. contents:: Table of Contents

**This software is pre-production and should not be deployed to production servers.**

Introduction
============

Workload Collocation Agent's goal is to reduce interference between collocated tasks and increase tasks 
density while ensuring the quality of service for high priority tasks. Chosen approach allows to 
enable real-time resource isolation management to ensure that high priority jobs meet their 
Service Level Objective (SLO) and best-effort jobs effectively utilize as many idle resources as possible.

Resource usage can be increased by:

- collocating best effort and high priority tasks to exploit resources that are underutilized by high priority applications,
- collocating tasks that do not compete for shared resources on the platform.

.. image:: docs/overview.png

WCA abstracts compute node, workloads, monitoring and resource allocation.
An externally provided algorithm is responsible for allocating resources or anomaly detection logic. WCA
and the algorithm exchange information about current resource usage, isolation actuations or detected
anomalies. WCA stores information about detected anomalies, resource allocation and platform utilization metrics to a remote storage such as Kafka.

The diagram below puts WCA in context of a cluster and monitoring infrastructure:

.. image:: docs/context.png

For context regarding `Mesos see this document <docs/mesos.rst>`_ and for `Kubernetes see this document <docs/kubernetes.rst>`_.


See `WCA Architecture 1.7.pdf`_ for further details.


Getting started
===============

WCA is targeted at and tested on Centos 7.6
(WCA should work on earlier versions of centos or other Linux distributions, however it is tested only on centos 7.6).

*Note*: for full production installation please follow this detailed `installation guide <docs/install.rst>`_.

Steps needed to install WCA dependencies and build WCA pex file:

.. code-block:: shell
    
    # Install required software.
    sudo yum install git python3 make which python3-pip -y
    python3 -mpip install --user pipenv
    export PATH=$PATH:~/.local/bin

    # Clone the repository & build.
    git clone https://github.com/intel/workload-collocation-agent
    cd workload-collocation-agent
    
    export LC_ALL=en_US.utf8  # required for centos docker image
    make venv  # creates venv by pipenv
    make wca_package

or using docker:

.. code-block:: shell

    # needed only on host, where pex file is run
    sudo yum install python3

    # needed on host, where pex file is builded
    sudo yum install make

    # pex file will be copied to ./dist/wca.pex
    make wca_package_in_docker

Steps to run WCA:

.. code-block:: shell

    # Configuration files used in below commands requires creating a cgroup with name `task1`.
    sudo mkdir -p /sys/fs/cgroup/{cpu,cpuset,cpuacct,memory,perf_event}/task1

    # Add a process to the cgroup to monitor it using WCA. Might be skipped.
    sudo bash -c 'echo $PROCESS_PID > /sys/fs/cgroup/{cpu,cpuset,cpuacct,memory,perf_event}/task1/tasks'

    # Example of running agent in measurements-only mode with predefined static list of tasks
    sudo dist/wca.pex --config $PWD/configs/extra/static_measurements.yaml --root

    # Example of static allocation with predefined rules on predefined list of tasks.
    sudo dist/wca.pex --config $PWD/configs/extra/static_allocator.yaml --root

    # The same as 2nd command, but run from source code - does **not** 
    #   work with docker option of installing dependencies.
    sudo env PYTHONPATH=. `pipenv --py` wca/main.py --config $PWD/configs/extra/static_allocator.yaml --root

Used configuration files:

- `measurements-only config <configs/extra/static_measurements.yaml>`_,
- `static allocator with predifined rules <configs/extra/static_allocator.yaml>`_ (`predifined rules <configs/extra/static_allocator_config.yaml>`_).

Running these commands outputs metrics in Prometheus format to standard error like this:

.. code-block:: ini

    # HELP platform_cpu_usage Logical CPU usage in 1/USER_HZ (usually 10ms).Calculated using values based on /proc/stat.
    # TYPE platform_cpu_usage counter
    platform_cpu_usage{cpu="0",host="gklab-126-081"} 813285 1575624886157
    platform_cpu_usage{cpu="1",host="gklab-126-081"} 828325 1575624886157

    # HELP platform_mem_numa_free_bytes NUMA memory free per NUMA node based on /sys/devices/system/node/* (MemFree:)
    # TYPE platform_mem_numa_free_bytes gauge
    platform_mem_numa_free_bytes{host="gklab-126-081",numa_node="0"} 15852359680 1575624886157

    # HELP task_cpu_usage_seconds Time taken by task based on cpuacct.usage (total kernel and user space).
    # TYPE task_cpu_usage_seconds counter
    task_cpu_usage_seconds{application="task1",application_version_name="",host="gklab-126-081",task_id="task1",task_name="task1"} 7.319848155 1575625088768

    # HELP task_instructions Hardware PMU counter for number of instructions.
    # TYPE task_instructions counter
    task_instructions{application="task1",application_version_name="",cpu="0",host="gklab-126-081",task_id="task1",task_name="task1"} 44191995093.0 1575625088768
    task_instructions{application="task1",application_version_name="",cpu="1",host="gklab-126-081",task_id="task1",task_name="task1"} 0.0 1575625088768

    # HELP task_last_seen Time the task was last seen.
    # TYPE task_last_seen counter
    task_last_seen{application="task1",application_version_name="",host="gklab-126-081",task_id="task1",task_name="task1"} 1575625087.7695165 1575625088768

    # HELP task_mem_numa_pages Number of used pages per NUMA node(key: hierarchical_total is used if available or justtotal with warning), from cgroup memory controller from memory.numa_stat file.
    # TYPE task_mem_numa_pages gauge
    task_mem_numa_pages{application="task1",application_version_name="",host="gklab-126-081",numa_node="0",task_id="task1",task_name="task1"} 0 1575625088768

    # HELP task_mem_page_faults Number of page faults for task.
    # TYPE task_mem_page_faults counter
    task_mem_page_faults{application="task1",application_version_name="",host="gklab-126-081",task_id="task1",task_name="task1"} 0 1575625088768

    # HELP task_mem_usage_bytes Memory usage_in_bytes per tasks returned from cgroup memory subsystem.
    # TYPE task_mem_usage_bytes gauge
    task_mem_usage_bytes{application="task1",application_version_name="",host="gklab-126-081",task_id="task1",task_name="task1"} 0 1575625088768

    # HELP task_scaling_factor_max Perf subsystem metric scaling factor, max value of all perf per task metrics.
    # TYPE task_scaling_factor_max gauge
    task_scaling_factor_max{application="task1",application_version_name="",host="gklab-126-081",task_id="task1",task_name="task1"} 1.0 1575625088768

    # HELP wca_information Special metric to cover some meta information like wca_version or cpu_model or platform topology (to be used instead of include_optional_labels)
    # TYPE wca_information gauge
    wca_information{cores="4",cpu_model="Intel(R) Core(TM) i7-4790 CPU @ 3.60GHz",cpus="8",host="gklab-126-081",sockets="1",wca_version="1.0.7.dev691+g1ccb801.d20191205"} 1 1575625088768

    # HELP wca_tasks Number of discovered tasks
    # TYPE wca_tasks gauge
    wca_tasks{host="gklab-126-081"} 1 1575625088768



When reconfigured, other built-in components allow to:

- store those metrics in Kafka (KafkaStorage) or expose in Prometheus format (LogStorage)
- integrate with Mesos or Kubernetes,
- enable anomaly detection,
- or enable anomaly prevention (allocation) to mitigate interference between workloads.

Configuration
=============

WCA introduces simple but extensible mechanism to inject dependencies into classes and build complete software stack of components.
WCA main control loop is based on ``Runner`` base class that implements
single ``run`` blocking method. Depending on ``Runner`` class used, the WCA is run in different execution mode (e.g. detection,
allocation).

Refer to full of list of `Components`_ for further reference.

Available runners:

- ``MeasurementRunner`` simple runner that only collects data without calling detection/allocation API.
- ``DetectionRunner`` implements the loop calling ``detect`` function in
  regular and configurable intervals. See `detection API <docs/detection.rst>`_ for details.
- ``AllocationRunner`` implements the loop calling ``allocate`` function in
  regular and configurable intervals. See `allocation API <docs/allocation.rst>`_ for details.

Conceptually ``Runner`` reads a state of the system (both metrics and workloads),
passes the information to external component (an algorithm), logs the algorithm input and output using implementation of  `Storage <wca/storage.py#L40>`_
and allocates resources if instructed.

Following snippet is an example configuration of a runner:

.. code-block:: yaml

    runner: !SomeRunner
        node: !SomeNode
        callback_component: !ClassImplementingCallback
        storage: !SomeStorage

After starting WCA with the above configuration, an instance of the class ``SomeRunner`` will be created. The instance's properties will be set to:

- ``node`` - to an instance of ``SomeNode``
- ``callback_component`` - to an instance of ``ClassImplementingCallback``
- ``storage`` - to an instance of ``SomeStorage``

Configuration mechanism allows to:

- Create and configure complex python objects (e.g. ``DetectionRunner``, ``MesosNode``, ``KafkaStorage``) using `YAML tags`_.
- Inject dependencies (with type checking support) into constructed objects using `dataclasses <https://docs.python.org/3/library/dataclasses.html>`_ annotations.
- Register external classes using ``-r`` command line argument or by using ``wca.config.register`` decorator API. This allows to extend WCA with new functionalities 
  (more information `about extending here <docs/extending.rst>`_) and is used to provide external components with e.g. anomaly logic like `Platform Resource Manager <https://github.com/intel/platform-resource-manager/tree/master/prm>`_.

.. _`YAML tags`: http://yaml.org/spec/1.2/spec.html#id2764295

See `external detector example <docs/external_detector_example.rst>`_ for more details.

Components
----------

Following built-in components are available (stable API; refer to `API documentation <docs/api.rst>`_ for full documentation):

- `MesosNode <docs/api.rst#mesosnode>`_ provides workload discovery on Mesos cluster node where `mesos containerizer <http://mesos.apache.org/documentation/latest/mesos-containerizer/>`_ is used (see the `Mesos docs here <docs/mesos.rst>`_)
- `KubernetesNode <docs/api.rst#kubernetesnode>`_ provides workload discovery on Kubernetes cluster node (see the docs `here <docs/kubernetes.rst>`_)
- `MeasurementRunner <docs/api.rst#measurementrunner>`_ implements simple loop that reads state of the system, encodes this information as metrics and stores them,
- `DetectionRunner <docs/api.rst#detectionrunner>`_ extends ``MeasurementRunner`` and additionally implements anomaly detection callback and encodes anomalies as metrics to enable alerting and analysis. See `Detection API <docs/detection.rst>`_ for more details.
- `AllocationRunner <docs/api.rst#allocationrunner>`_ extends ``MeasurementRunner`` and additionally implements resource allocation callback. See `Allocation API <docs/allocation.rst>`_ for more details.
- `NOPAnomalyDetector <docs/api.rst#nopanomalydetector>`_ dummy "no operation" detector that returns no metrics, nor anomalies. See `Detection API <docs/detection.rst>`_ for more details.
- `NOPAllocator <docs/api.rst#nopallocator>`_ dummy "no operation" allocator that returns no metrics, nor anomalies and does not configure resources. See `Detection API <docs/detection.rst>`_ for more details.
- `KafkaStorage <docs/api.rst#kafkastorage>`_ logs metrics to `Kafka streaming platform <https://kafka.apache.org/>`_ using configurable topics.
- `LogStorage <docs/api.rst#logstorage>`_ logs metrics to standard error or to a file at configurable location.
- `SSL <docs/api.rst#ssl>`_ to enabled secure communication with external components (more information `about SSL here <docs/ssl.rst>`_).

Following built-in components are available as provisional API:

- `StaticNode <docs/api.rst#staticnode>`_ to support static list of tasks (does not require full orchestration software stack),
- `StaticAllocator <docs/api.rst#staticallocator>`_ to support simple rules based logic for resource allocation.
- `NUMAAllocator <docs/api.rst#snumaallocator>`_ to optimize workload placement for NUMA systems

Officially supported third-party components:

- `Intel "Platform Resource Manager" plugin <https://github.com/intel/platform-resource-manager/tree/master/prm>`_ - machine learning based component for both anomaly detection and allocation.

:Warning: Note that, those components are run as ordinary python class, without any isolation and with process's privileges so there is no built-in protection against malicious external components.  
          For **security** reasons, **please use only built-in and officially supported components**. More about `security here <SECURITY.md>`_.


Workloads
=========

The project contains Dockerfiles together with helper scripts aimed at preparation of reference workloads to be run on Mesos cluster using Aurora framework.

To enable anomaly detection algorithm validation the workloads are prepared to:

- provide continuous stream of Application Performance Metrics using `wrappers <docs/wrappers.rst>`_ (all workloads),
- simulate varying load (patches to generate sine-like pattern of requests per second are available for `YCSB <workloads/ycsb/intel.patch>`_ and `rpc-perf <workloads/rpc_perf/intel_rpc-perf-ratelimit.patch>`_ ).
  

See `workloads directory <workloads>`_ for list of supported applications and load generators.

Further reading
===============

- `Installation guide <docs/install.rst>`_  
- `Measurement API <docs/measurement.rst>`_
- `Detection API <docs/detection.rst>`_
- `Allocation API <docs/allocation.rst>`_
- `Metrics list <docs/metrics.rst>`_
- `Metrics sources <docs/metrics_sources.rst>`_
- `Development guide <docs/development.rst>`_
- `External detector example <docs/external_detector_example.rst>`_
- `Wrappers guide <docs/wrappers.rst>`_
- `Mesos integration <docs/mesos.rst>`_
- `Kubernetes integration <docs/kubernetes.rst>`_
- `Logging configuration <docs/logging.rst>`_
- `Supported workloads and definitions </workloads>`_
- `WCA Architecture 1.7.pdf`_
- `Secure communication with SSL <docs/ssl.rst>`_
- `Security policy <SECURITY.md>`_
- `Configuration examples for Kubernetes and Mesos <configs/>`_
- `Other examples (e.g. how to add new component) <example/>`_
- `Extending WCA <docs/extending.rst>`_
- `Workload Collocation Agent API <docs/api.rst>`_

.. _`WCA Architecture 1.7.pdf`: docs/WCA_Architecture_v1.7.pdf
