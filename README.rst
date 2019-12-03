=====================================================
WCA - Workload Collocation Agent
=====================================================

.. image:: https://travis-ci.com/intel/workload-collocation-agent.svg?branch=master
    :target: https://travis-ci.com/intel/workload-collocation-agent

.. contents:: Table of Contents

**This software is pre-production and should not be deployed to production servers.**

Introduction
============

Workload Collocation Agent's goal is to reduce interference between collocated tasks and increase tasks density while ensuring the quality of
service for high priority tasks. Chosen approach allows to enable real-time resource isolation management
to ensure that high priority jobs meet their Service Level Objective (SLO) and best-effort jobs
effectively utilize as many idle resources as possible.

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

For context regarding Mesos see `this document <docs/mesos.rst>`_ and for Kubernetes see `this document <docs/kubernetes.rst>`_.

See `WCA Architecture 1.7.pdf`_ for further details.


Getting started
===============

------------

WCA is targeted at and tested on Centos 7.5.

*Note*: for full production installation please follow this detailed `installation guide <docs/install.rst>`_.

.. code-block:: shell

    # Install required software.
    sudo yum install epel-release -y
    sudo yum install git python36 make which -y
    python3.6 -m ensurepip --user
    python3.6 -m pip install --user pipenv
    export PATH=$PATH:~/.local/bin

    # Clone the repository & build.
    git clone https://github.com/intel/workload-collocation-agent
    cd workload-collocation-agent
    
    export LC_ALL=en_US.utf8 #required for centos docker image
    make venv
    make wca_package

    # Prepare tasks manually (only cgroups are required)
    sudo mkdir /sys/fs/cgroup/{cpu,cpuacct,perf_event}/task1

    # Example of running agent in measurements-only mode with predefined static list of tasks
    sudo dist/wca.pex --config $PWD/configs/extra/static_measurements.yaml --root

    # Example of static allocation with predefined rules on predefined list of tasks.
    sudo dist/wca.pex --config $PWD/configs/extra/static_allocator.yaml --root


Running those commands outputs metrics in Prometheus format to standard error like this:

.. code-block:: ini

    # HELP cache_misses Linux Perf counter for cache-misses per container.
    # TYPE cache_misses counter
    cache_misses{cores="4",cpus="8",host="gklab-126-081",wca_version="0.1.dev655+g586f259.d20190401",sockets="1",task_id="task1"} 0.0 1554139418146

    # HELP cpu_usage_per_cpu [1/USER_HZ] Logical CPU usage in 1/USER_HZ (usually 10ms).Calculated using values based on /proc/stat
    # TYPE cpu_usage_per_cpu counter
    cpu_usage_per_cpu{cores="4",cpu="0",cpus="8",host="gklab-126-081",wca_version="0.1.dev655+g586f259.d20190401",sockets="1"} 5103734 1554139418146
    cpu_usage_per_cpu{cores="4",cpu="1",cpus="8",host="gklab-126-081",wca_version="0.1.dev655+g586f259.d20190401",sockets="1"} 6860714 1554139418146

    # HELP cpu_usage_per_task [ns] cpuacct.usage (total kernel and user space)
    # TYPE cpu_usage_per_task counter
    cpu_usage_per_task{cores="4",cpus="8",host="gklab-126-081",wca_version="0.1.dev655+g586f259.d20190401",sockets="1",task_id="task1"} 0 1554139418146

    # HELP instructions Linux Perf counter for instructions per container.
    # TYPE instructions counter
    instructions{cores="4",cpus="8",host="gklab-126-081",wca_version="0.1.dev655+g586f259.d20190401",sockets="1",task_id="task1"} 0.0 1554139418146

    # HELP memory_usage [bytes] Total memory used by platform in bytes based on /proc/meminfo and uses heuristic based on linux free tool (total - free - buffers - cache).
    # TYPE memory_usage gauge
    memory_usage{cores="4",cpus="8",host="gklab-126-081",wca_version="0.1.dev655+g586f259.d20190401",sockets="1"} 6407118848 1554139418146

    # TYPE wca_tasks gauge
    wca_tasks{cores="4",cpus="8",host="gklab-126-081",wca_version="0.1.dev655+g586f259.d20190401",sockets="1"} 1 1554139418146

    # TYPE wca_up counter
    wca_up{cores="4",cpus="8",host="gklab-126-081",wca_version="0.1.dev655+g586f259.d20190401",sockets="1"} 1554139418.146581 1554139418146


When reconfigured, other built-in components allow to:

- store those metrics in Kafka, 
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
  (more information `here <docs/extending.rst>`_) and is used to provide external components with e.g. anomaly logic like `Platform Resource Manager <https://github.com/intel/platform-resource-manager/tree/master/prm>`_.

.. _`YAML tags`: http://yaml.org/spec/1.2/spec.html#id2764295

See `external detector example <docs/external_detector_example.rst>`_ for more details.

Components
----------

Following built-in components are available (stable API):

- `MesosNode <wca/mesos.py#L76>`_ provides workload discovery on Mesos cluster node where `mesos containerizer <http://mesos.apache.org/documentation/latest/mesos-containerizer/>`_ is used (see the docs `here <docs/mesos.rst>`_)
- `KubernetesNode <wca/kubernetes.py#L71>`_ provides workload discovery on Kubernetes cluster node (see the docs `here <docs/kubernetes.rst>`_)
- `MeasurementRunner <wca/runners/measurement.py#L42>`_ implements simple loop that reads state of the system, encodes this information as metrics and stores them,
- `DetectionRunner <wca/runners/detection.py#L59>`_ extends ``MeasurementRunner`` and additionally implements anomaly detection callback and encodes anomalies as metrics to enable alerting and analysis. See `Detection API <docs/detection.rst>`_ for more details.
- `AllocationRunner <wca/runners/allocation.py#L155>`_ extends ``MeasurementRunner`` and additionally implements resource allocation callback. See `Allocation API <docs/allocation.rst>`_ for more details.
- `NOPAnomalyDetector <wca/detectors.py#L164>`_ dummy "no operation" detector that returns no metrics, nor anomalies. See `Detection API <docs/detection.rst>`_ for more details.
- `NOPAllocator <wca/allocators.py#L98>`_ dummy "no operation" allocator that returns no metrics, nor anomalies and does not configure resources. See `Detection API <docs/detection.rst>`_ for more details.
- `KafkaStorage <wca/storage.py#L253>`_ logs metrics to `Kafka streaming platform <https://kafka.apache.org/>`_ using configurable topics.
- `LogStorage <wca/storage.py#L49>`_ logs metrics to standard error or to a file at configurable location.
- `SSL <wca/security.py#L116>`_ to enabled secure communication with external components (more information `here <docs/ssl.rst>`_).

Following built-in components are available as provisional API:

- `StaticNode <wca/extra/static_node.py#L28>`_ to support static list of tasks (does not require full orchestration software stack),
- `StaticAllocator <wca/extra/static_allocator.py#L108>`_ to support simple rules based logic for resource allocation.

Officially supported third-party components:

- `Intel "Platform Resource Manager" plugin <https://github.com/intel/platform-resource-manager/tree/master/prm>`_ - machine learning based component for both anomaly detection and allocation.

:Warning: Note that, those components are run as ordinary python class, without any isolation and with process's privileges so there is no built-in protection against malicious external components.  
          For **security** reasons, **please use only built-in and officially supported components**. More about security `here <SECURITY.md>`_.


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

.. _`WCA Architecture 1.7.pdf`: docs/WCA_Architecture_v1.7.pdf
