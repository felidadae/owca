=================
Mesos integration
=================

**This software is pre-production and should not be deployed to production servers.**

.. contents:: Table of Contents

Mesos supported features
========================

- Monitoring
- Allocation

Mesos restrictions
==================

- Mesos version >= 1.2.x,
- `Mesos containerizer <http://mesos.apache.org/documentation/latest/containerizers/#Mesos>`_,
- `Tasks groups <http://mesos.apache.org/documentation/latest/nested-container-and-task-group/>`_ are currently not supported.

Required agent options
------------------------------

- ``containerizers=mesos`` - to enable PID based cgroup discovery,
- ``isolation=cgroups/cpu,cgroups/perf_event`` - to enable CPU shares management and perf event monitoring,
- ``perf_events=cycles`` and ``perf_interval=360days`` - to enable perf event subsystem cgroup management without actual counter collection.

Following exact setup was verified to work with provided `workloads </workloads>`_:

- Mesos version == 1.2.6
- Docker registry V2
- Aurora framework version == 0.18.0

Mesos agent was configured with non-default options:

- ``perf_events=cycles``
- ``perf_interval=360days``
- ``isolation=filesystem/linux,docker/volume,docker/runtime,cgroups/cpu,cgroups/perf_event``
- ``cgroups_enable_cfs=true``
- ``hostname_lookup=false``
- ``image_providers=docker``
- ``attributes/own_ip=HOST_IP``

Possible configuration options
==============================
In OWCA configuration file one can set below listed parameters.
Please refer to `example configuration file for mesos <../configs/mesos/mesos_external_detector.yaml>`_.

.. code-block:: python

    @dataclass
    class MesosNode(Node):
        mesos_agent_endpoint: str = 'https://127.0.0.1:5051'

        # A flag of python requests library to enable ssl_verify or pass CA bundle:
        # https://github.com/kennethreitz/requests/blob/5c1f72e80a7d7ac129631ea5b0c34c7876bc6ed7/requests/api.py#L41
        ssl_verify: Union[bool, str] = True

        # Timeout to access mesos agent.
        timeout: float = 5.

