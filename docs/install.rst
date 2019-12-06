======================================
Building, installing and running WCA
======================================

**This software is pre-production and should not be deployed to production servers.**

.. contents:: Table of Contents

Building PEX distribution
=========================

Building requirements
---------------------

Please follow the instructions from `development guide <development.rst>`_ to prepare
following items:

- python 3.6
- git
- pip
- pipenv 
- make
- which (required by pipenv)
- source code of wca

Building executable binary (distribution)
-----------------------------------------

.. code:: shell

   make wca_package

File ``dist/wca.pex`` must be copied to ``/usr/bin/wca.pex``.

To build distribution file with support for storing metrics in Kafka please follow
`Building executable binary with KafkaStorage component enabled <kafka_storage.rst>`_ guide.

Running
========

Runtime requirements
--------------------

- Hardware with `Intel RDT <https://www.intel.com/content/www/us/en/architecture-and-technology/resource-director-technology.html>`_ support.
- Centos 7.5 with at least 3.10.0-862 kernel with support of `resctrl filesystem <https://www.kernel.org/doc/Documentation/x86/intel_rdt_ui.txt>`_.
- Python 3.6.x 

All other the software dependencies are bundled using `PEX <https://github.com/pantsbuild/pex>`_.

RDT enabling on Skylake processor
---------------------------------

It is possible to use RDT features on Skylake family of processors.
However, there are known issues mentioned in
`errata <https://www.intel.com/content/dam/www/public/us/en/documents/specification-updates/6th-gen-x-series-spec-update.pdf>`_:

- SKZ4  MBM does not accurately track write bandwidth,
- SKZ17 CMT counters may not count accurately,
- SKZ18 CAT may not restrict cacheline allocation under certain conditions,
- SKZ19 MBM counters may undercount.

To enable RDT please add kernel boot time parameters ``rdt=cmt,mbmtotal,mbmlocal,l3cat``
(`kernel documenatation <https://github.com/torvalds/linux/blob/f4eb1423e43376bec578c5696635b074c8bd2035/Documentation/admin-guide/kernel-parameters.txt#L4093>`_).


Python 3.6 Centos installation (recommended)
--------------------------------------------

:Note: For Centos 7.6 Python 3.6 is already available, so you **do not** need to install epel-release.

The recommended way of installing Python 3.6.x is to use `Software Collections <https://www.softwarecollections.org/en/>`_.
SCL repository is maintained by a CentOS SIG.

Please use `official installation guide <https://www.softwarecollections.org/en/scls/rhscl/rh-python36/>`_ to install Python 3.6 on target hosts.

Then, verify that Python is installed correctly::

    /usr/bin/scl enable rh-python36 'python --version'

Should output::
    
    Python 3.6.3

Alternative options for Python 3.6 installation 
-----------------------------------------------

To simplify python interpreter management (no need to use ``scl`` tool as prefix), 
you can use Intel Distribution for Python according to `yum-based installation guide <https://software.intel.com/en-us/articles/installing-intel-free-libs-and-python-yum-repo>`_.
or use community maintained third-party ``epel`` repository and install ``python36`` package from there::

    yum install epel-release
    yum install python36

CentOS project does not support, nor provide ``epel`` repository.


Running WCA as non-root user
-----------------------------

WCA processes should not be run with root privileges. Following privileges are needed to run WCA as non-root user:

- `CAP_DAC_OVERRIDE`_ - to allow non-root use cgroups filesystem.

- `CAP_SETUID`_ capability and `SECBIT_NO_SETUID_FIXUP`_ secure bit set - to allow non-root use resctrl filesystem.  

- ``/proc/sys/kernel/perf_event_paranoid`` - `content of the file`_ must be set to ``0`` or ``-1`` to allow non-root
  user to collect all the necessary perf event information.

If it is impossible or undesired to run WCA with privileges outlined above, then you must add ``-0`` (or its
long form: ``--root``) argument when starting the process)

..  _`CAP_DAC_OVERRIDE`: https://elixir.bootlin.com/linux/v3.10.108/source/include/uapi/linux/capability.h#L104 
..  _`CAP_SETUID`: https://elixir.bootlin.com/linux/v3.10.108/source/include/uapi/linux/capability.h#L142
..  _`SECBIT_NO_SETUID_FIXUP`: https://elixir.bootlin.com/linux/v3.10.108/source/include/uapi/linux/securebits.h#L31  
..  _`content of the file`: https://linux.die.net/man/2/perf_event_open

Running as systemd service
--------------------------

Assumptions:

- ``/var/lib/wca`` directory exists
- ``wca`` user and group already exists
 
Please use following `template <../configs/systemd-unit/wca.service>`_ as systemd ``/etc/systemd/system/wca.service`` unit file::

    [Unit]
    Description=Workload Collocation Agent

    [Service]
    ExecStart=/usr/bin/scl enable rh-python36 '/usr/bin/wca.pex \
        --config /etc/wca/wca_config.yml \
        --register $EXTRA_COMPONENT \
        --log info'
    User=wca
    Group=wca
    # CAP_DAC_OVERRIDE allows to remove resctrl groups and CAP_SETUID allows to change effective uid to add tasks to the groups
    CapabilityBoundingSet=CAP_DAC_OVERRIDE CAP_SETUID
    AmbientCapabilities=CAP_DAC_OVERRIDE CAP_SETUID
    # We must avoid dropping capabilities after changing effective uid from root to wca
    SecureBits=no-setuid-fixup
    Restart=always
    RestartSec=5
    LimitNOFILE=500000
    WorkingDirectory=/var/lib/wca

    [Install]
    WantedBy=multi-user.target

where:

``$EXTRA_COMPONENT`` should be replaced with name of a class e.g. ``wca.allocators:NOPAllocator``.
Class name must comply with `pkg_resources <https://setuptools.readthedocs.io/en/latest/pkg_resources.html#id2>`_ format.
All dependencies of the class must be available in currently used `PYTHONPATH`.

You can use ``wca.allocators:NOPAllocator`` that is already bundled within ``dist/wca.pex`` file and does not have to be registered(if you decide to use it remove registration from `wca.service` file).

:note: Running wca with dedicated "wca" user is more secure, but requires enabling perf counters to be used by non-root users.
       You need to reconfigure ``perf_event_paranoid`` sysctl paramter like this:
       ``sudo sysctl -w kernel.perf_event_paranoid=-1`` or for persistent mode modify ``/etc/sysctl.conf`` and set
       ``kernel.perf_event_paranoid = -1``. Mode about perf_event_paranoid `here <https://www.kernel.org/doc/Documentation/sysctl/kernel.txt>`_

It is recommended to build a pex file with external component and its dependencies bundled. See `prm plugin from platform-resource-manager 
<https://github.com/intel/platform-resource-manager/tree/master/prm>`_ as an example of such an approach.

Config ``/etc/wca/wca_config.yml`` must exists. See an `example configuration file <../configs/mesos/mesos_example_allocator.yaml>`_ to be used with ``NOPAllocator``:

.. code-block:: yaml

    runner: !AllocationRunner
      config: !AllocationRunnerConfig
        node: !MesosNode
          mesos_agent_endpoint: 'http://127.0.0.1:5051'
        timeout: 5
        interval: 1.
        metrics_storage: !LogStorage
          output_filename: '/tmp/output_anomalies.log'    
        extra_labels:
          env_id: "$HOST_IP"
        anomalies_storage: !KafkaStorage
            brokers_ips: ['$KAFKA_BROKER_IP:9092']
            topic: wca_anomalies
            max_timeout_in_seconds: 5.
        allocator: !NOPAllocator
            ...
        ...
            

Apply following changes to the file above:

- ``$KAFKA_BROKER`` must be replaced with IP address of Kafka broker,
- ``$HOST_IP`` may be replaced with host IP address to tag all metrics originating from WCA process

Following configuration is required in order to use ``MesosNode`` component to discover new tasks:

- `Mesos containerizer <http://mesos.apache.org/documentation/latest/mesos-containerizer/>`_ (``--containerizers=mesos``) must be used.
- Mesos agent must be `configured <http://mesos.apache.org/documentation/latest/configuration/agent/#isolation>`_ to support following `isolators <http://mesos.apache.org/documentation/latest/mesos-containerizer/#isolators>`_ 
   - ``filesystem/linux``,
   - ``docker/volume``,
   - ``docker/runtime``,
   - ``cgroups/cpu``,
   - ``cgroups/perf_event``.
- Mesos agent must expose operator API over `secure socket <http://mesos.apache.org/documentation/latest/ssl/>`_. WCA TLS can be disabled in configuration by modifying ``mesos_agent_endpoint`` property.
- Mesos agent may be `configured <http://mesos.apache.org/documentation/latest/configuration/agent/#image_providers>`_ to use Docker registry to fetch images. 

