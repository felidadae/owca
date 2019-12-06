==============
Numa allocator
==============

**This software is pre-production and should not be deployed to production servers.**

.. contents:: Table of Contents

Fast start
==========

Assumptions:

- already installed WCA 
- already installed python3.6

Please base your configuration on provided below:

.. code-block:: yaml

    loggers:
      "wca.extra.numa_allocator": "debug"
      "wca.cgroups_allocations": "debug"
      "wca": "info"

    runner: !AllocationRunner
      measurement_runner: !MeasurementRunner
        interval: 5
        node: !MesosNode
          mesos_agent_endpoint: 'http://127.0.0.1:5051'
          timeout: 5

        enable_derived_metrics: true

        metrics_storage: !LogStorage
          output_filename: metrics.prom
          overwrite: true

        extra_labels:
          node: !Env HOSTNAME

      allocator: !NUMAAllocator

      allocations_storage: !LogStorage
        output_filename: allocations.prom
        overwrite: true
      anomalies_storage: !LogStorage
        output_filename: anomalies.prom
        overwrite: true

Run WCA agent as usually. Then NUMAAllocator will be run with default values - based on algorithm
*'fill_biggest_first'*.


Algorithm explanation
=====================

The goal of the allocator is to minimise remote memory NUMA nodes accesses by processes.

Further in text, by *task memory being pinned* we mean that at least
cgroup based cpu pinning was performed on the task; optionally other methods which helps in
keeping memory on chosen NUMA node might have been performed.
All available methods supported by the plugin are:

- cgroup based cpu pinning - which results in higher propability that new allocations of memory
  made a process will be done on NUMA node to which cpus was pinned task; cannot be disabled;

- cgroup based memory pinning - allow to assure that all new allocations of a task will be done
  on chosen NUMA node, however it may result in ""OutOfMemory" kills of processes, so we do not
  recommend to use it in most cases; optional;
  argument in NUMAAllocator: ``cgroups_memory_binding``

- syscall migrate_pages based method - allow to migrate pages of process from chosen NUMA nodes
  to a choosen node, in synchronous manner; it may make the service unavailable for the time
  of migration, however it used only in initialization stage of a task is the most effective; 
  optional; argument in NUMAAllocator: ``migrate_pages``

- autoNUMA - kernel method to automatically migrate pages between NUMA nodes, it may be used in
  parallel to this plugin; please refer to argument in NUMAAllocator ``loop_min_task_balance``


We provide two algorithms:

- ``algorithm``: **NUMAAlgorithm**

    - *'fill_biggest_first'*

        Algorithm only cares about sum of already pinned task's memory to each numa node.
        In each step tries to pin the biggest possible task to numa node, where sum of
        memories of pinned task is the lowest.

    - *'minimize_migrations'*

        Algorithm tries to minimize amount of memory which needs to be migrated
        between numa nodes.  Into consideration takes information: where a task
        memory is allocated (on which NUMA nodes), which are nodes where the sum
        of pinned memory is the lowest and which are nodes where most
        free memory is available. The core of algorithm is a function ``migration_minimizer_core``.

In calculations we use orchestrator assigned memory as task memory (if available).


Arguments documentation
=======================

- ``algorithm``: **NUMAAlgorithm** = *'fill_biggest_first'*:
        - *'fill_biggest_first'*

            Algorithm only cares about sum of already pinned task's memory to each numa node.
            In each step tries to pin the biggest possible task to numa node, where sum of
            pinned task is the lowest.

        - *'minimize_migrations'*

            Algorithm tries to minimize amount of memory which needs to be remigrated
            between numa nodes.  Into consideration takes information: where a task
            memory is allocated (on which NUMA nodes), which are nodes where the sum
            of pinned memory is the lowest and which are nodes where most
            free memory is available.

    - ``loop_min_task_balance``: **float** = *0.0*:

        Useful when autoNUMA used on system.
        Minimal value of task_balance so the task is not skipped during rebalancing analysis
        by default turn off, none of tasks are skipped due to this reason. 

    - ``free_space_check``: **bool** = *False*:

        If True, then do not migrate if not enough space on target numa node.


    - ``migrate_pages``: **bool** = *True*:

        If use syscall "migrate pages" (forced, synchronous migrate pages of a task)


    - ``migrate_pages_min_task_balance``: **Optional[float]** = *0.95*:

        Works if migrate_pages == True. Then if set tells,
        when remigrate pages of already pinned task.
        If not at least ``migrate_pages_min_task_balance * TASK_TOTAL_SIZE``
        bytes of memory resides on pinned node, then
        tries to remigrate all pages allocated on other nodes to target node.


    - ``cgroups_memory_binding``: **bool** = *False*:

        cgroups based memory binding


    - ``cgroups_memory_migrate``: **bool** = *False*:

        cgroups based memory migrating; can be used only when
        cgroups_memory_binding is set to True


    - ``dryrun``: **bool** = *False*:

        If set to True, do not make any allocations - can be used for debugging.
