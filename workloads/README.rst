##################################################################################
This software is pre-production and should not be deployed to production servers.
##################################################################################

=========
Workloads
=========

Description
===========

This folder contains:

- dockerfiles to build workloads images,
- aurora job definitions,
- ansible playbook `run_workloads.yaml`_ to schedule all workloads on Aurora cluster.

Building wrappers
=================

Wrapper module provides a framework for parsing application output and
sending metrics in prometheus format to a Kafka broker.

.. code-block:: sh

    tox -e wrapper_package

Wrapper executables are as ``dist/wrapper_*.pex`` files.

Building docker images with wrappers
====================================

Note that:

- most workload images require wrapper pex files (`Building wrappers`_),
- workload images are build from **repository top-level** (to have access to wrapper pex files),
- the convention is to prefix images names with string ``owca/``, e.g. ``owca/cassadra_stress``,
- sub directorires here e.g. ``cassandra_stress`` match image names.

To build image:

.. code-block:: sh

    # in repository top-level directory
    docker build -f workloads/stress_ng/Dockerfile -t owca/stress_ng .


Running individual Aurora jobs
==============================

Aurora files (``*.aurora``) contains definition of Aurora jobs.
Each aurora file includes `<common.aurora>`_ that defines
common required parameters.

The list of common parameters is:

======================= ======================== ======================================= ================================================
Name                    Required(default)        Description                             Example(s)
======================= ======================== ======================================= ================================================
workload_name           yes                      Identifies a pair of application        - cassandra_ycsb
                                                 and its load generator (if              - twemcache_rpc_perf
                                                 in use).                                - tensorflow_inference
workload_version_name   no (default)             Used to seperate between different      - small
                                                 configuration of a given workload;      - big
                                                 for instance one may want to run
                                                 two instances of a cassandra_ycsb
                                                 workload differenting in ycsb
                                                 thread count and target QPS -
                                                 then two versions of a workload
                                                 can be created.
job_name                yes                      Used as Aurora job_name (last part      twemcache_rpcperf.default--twemcache--11211.0
                                                 of job_key in aurora documentation
                                                 nomenclature) and for aurora
                                                 Service/Job class instances
                                                 name property.
job_id                  yes                      Name of an application being a          - cassandra
                                                 component of the workload. This         - ycsb
                                                 parameter is used in                    - memcached
                                                 `run_workloads.yaml`_                   - mutilate
                                                                                         - rpc-perf
job_uniq_id             yes                      A workload instance unique identifier   - 11211 (memcache port)
                                                 (unique among instances running on      - 6789 (redis port)
                                                 the same host).                         - 0 (instance counter)
replica_index           no (0)                   For some workloads, a component         - 0
                                                 application can have multiple           - 1
                                                 replicas sharing the same job_uniq_id,
                                                 e.g. mutliple load generators stressing
                                                 the same DB application; replica_index
                                                 allows to differience between
                                                 the replicas.
application             yes                      Added as a label to produced metrics    - cassandra
                                                 to identify stressed application.       - twemcache
load_generator          yes                      Added as a label to produced metrics    - ycsb
                                                 to identify load generator.             - rpc-perf
cluster                 no (example)             Aurora cluster name                     example
role                    no ($USER)               Aurora job role                         root
env_uniq_id             yes                      Aurora unique staging                   127
                                                 environment identfier (must be 
                                                 an integer).
communication_port      yes                      Used to establish communication         - 11211 (memcache port)
                                                 between a load generator and
                                                 an application.
application_host_ip     for load generator jobs  An application host IP; used by         100.65.213.12
                                                 a load generator.
own_ip                  yes                      Used to specify host were job will      100.65.174.12
                                                 be scheduled.
image_name              yes                      docker image name                       owca/ycsb
image_tag               yes                      docker image tag
slo                     no (empty)               SLA target (unit should match           80000
                                                 unit in which SLI metric is
                                                 expressed).
cpu                     no (1 cpu)               How many logical processors             2
                                                 should be allocated to the job
ram                     no (1 GB)                How many GB of RAM memory should        16
                                                 be allocated to the task
disk                    no (1 GB)                How many GB of disc space should        4
                                                 be allocated to the task
wrapper_kafka_borker    for jobs using wrapper   Address of Kafka borker to store        100.65.174.12:5050
                                                 performance metrics.
wrapper_kafka_topic     for jobs using wrapper   Name of the topic to store performance  owca_workloads_twemcache_rpc_perf
                                                 metrics in Kafka.
wrapper_log_level       no (DEBUG)               Log level for wrapper.                  WARNING
======================= ======================== ======================================= ================================================

A workload specific variables are documented in the workload aurora files.


Scheduling workloads
===============================

Use `run_workloads.yaml`_ playbook to run workloads on Aurora cluster.

Playbook requires ``Aurora client`` being installed on ansible host machine (please follow `official instructions
<http://aurora.apache.org/documentation/latest/operations/installation/#installing-the-client>`_ to install and
configure the client properly).

`run_workloads.yaml`_ playbook requires an inventory based on `run_workloads_inventory.template.yaml`_.
The template constitute an example how to configure a composition of workloads.

To run a workload instance on a specific cluster node we use aurora constraints mechanism.
In our solution this requires to mark Mesos nodes with an attribute named ``own_ip``.
Then to assign a job to a specific node the value of the parameter ``own_ip`` needs to match
the value of a mesos attribute set on the node.
For more information about aurora constrainst and mesos attributes can be found in
`official aurora documentation <http://aurora.apache.org/documentation/latest/features/constraints/>`_.

.. _`run_workloads.yaml`: run_workloads.yaml
.. _`run_workloads_inventory.template.yaml`: run_workloads_inventory.template.yaml

Inventory structure
------------------------------------------
As it was noted, the reference for creating an inventory is a file `run_workloads_inventory.template.yaml`_.
The template file contains comments aimed at helping to understand the structure.

.. _`run_workloads_inventory.template.yaml`: run_workloads_inventory.template.yaml

Below resource allocation definition for a workload. It will be applied to all hosts.

.. code-block:: yml

    application_hosts:
        hosts:
            # ....
        vars:
            # ....
            workloads:
                cassandra_ycsb:                # workload_name
                    default:                   # workload_version_name
                        cassandra:             # job_id
                            resources:
                                cpu: 8
                                disk: 4
                        ycsb:                  # job_id
                            resources:
                                cpu: 1.5

We can overwrite set values for a choosen host (we also need to set hash_behaviour to merge, please refer to
`doc <https://docs.ansible.com/ansible/2.4/intro_configuration.html#hash-behaviour>`_).
To achieve this we create dictionary ``workloads`` under the choosen host:

.. code-block:: yml

    application_hosts:
        hosts:
            10.10.10.9.4:
                env_uniq_id: 4
                workloads:                      # overwriting for a choosen host
                    default:
                        cassandra_ycsb:         #
                            resources:          #
                                cpu: 4          #

        vars:
            # ....
            workloads:
                cassandra_ycsb:                 # workload_name
                    default:
                        cassandra:              # job_id
                            resources:
                                cpu: 8
                                disk: 4
                        ycsb:
                            resources:
                                cpu: 1.5


Below we include an example configuration of a workload with comments marking values which translates
into common.aurora parameteres:

.. code-block:: yml

    docker_registry: 10.10.10.99:80
    # other params goes here ...
        workloads:
            cassandra_ycsb:                    # workload_name
                default:                       # workload_version_name
                    count: 2                   # two instances of the same workload
                    slo: 2500                  # slo
                    communication_port: 3333   # communication_port
                    cassandra:
                        image_name: cassandra  # image_name
                        image_tag: 3.11.3      # image_tag
                        resources:
                            cpu: 8             # cpu
                            disk: 4            # disk
                    ycsb:
                        count: 2               # two load generators stress the same cassandra instance
                        env:                   # any value passed here will be passed directly to aurora job (using environment variables)
                            ycsb_target: 2000  # check ycsb.aurora file for description of available parameters
                            ycsb_thread_count: 8                                                        
                        resources:
                            cpu: 1.5           # cpu
                big:                           # workload_version_name
                    ...

The rule of building aurora ``job_key`` (string identifying an aurora job, required argument in command ``aurora job create``) is:
``{{cluster}}/{{role}}/staging{{env_uniq_id}}/{{workload_name}}.{{workload_version_name}}--{{job_id}}--{{job_uniq_id}}.{{job_replica_index}}``.
The shell commands which will be executed by ansible as a result are as follow:

.. code-block:: sh

    # first instance of the workload
    # two replicas of load generators
    aurora job create example/root/staging127/cassandra_ycsb.default--ycsb--3333.0
    aurora job create example/root/staging127/cassandra_ycsb.default--ycsb--3333.1
    aurora job create example/root/staging127/cassandra_ycsb.default--cassandra--3333.0

    # second instance of the workload
    # two replicas of load generators
    aurora job create example/root/staging127/cassandra_ycsb.default--ycsb--3334.0
    aurora job create example/root/staging127/cassandra_ycsb.default--ycsb--3334.1
    aurora job create example/root/staging127/cassandra_ycsb.default--cassandra--3334.0


    # Here will goes commands for 'big' workload version
    aurora job create example/root/staging127/cassandra_ycsb.big--ycsb--3333.0
    # ...
