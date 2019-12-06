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

Please use as reference example configuration for Mesos:

- `config for mesos <../configs/extra/numa_allocator_mesos.yaml>`_.

Leave NUMAAllocator class configuration as it is and modify rest of configuration file
to match needs.

Run WCA agent as usually.


Algorithm explanation
=====================

The goal of allocator is to minimise remote memory NUMA nodes accesses by processes.

Further in text, by *task memory being pinned* we mean that at least
cgroup based cpu pinning was performed on the task; optionally other methods which helps in
keeping memory on chosen NUMA node might have been performed.
All available methods supported by the plugin are:

- cgroup based cpu pinning - which results in higher propability that new allocations of memory made a process
  will be done on NUMA node to which cpus was pinned task; it is not optional

- cgroup based memory pinning - allow to assure that all new allocations of a task will be done on chosen NUMA node,
  however it may result in OOM kills of processes, so we do not recommend to use it in most cases, optional

- syscall migrate_pages based method - allow to migrate pages of process from chosen NUMA nodes to a choosen node,
  in synchronous manner; it may make the service unavailable for the time of migration,
  however it used only in initialization stage of a task is the most effective

- autoNUMA - kernel method to automatically migrate pages between NUMA nodes, it may be used in parallel to this plugin.


We provide two algorithms:

- ``algorithm``: **NUMAAlgorithm**

    - *'fill_biggest_first'*

        Algorithm only cares about sum of already pinned task's memory to each numa node.
        In each step tries to pin the biggest possible task to numa node, where sum of
        memories of pinned task is the lowest.

    - *'minimize_migrations'*

        Algorithm tries to minimize amount of memory which needs to be remigrated
        between numa nodes.  Into consideration takes information: where a task
        memory is allocated (on which NUMA nodes), which are nodes where the sum
        of pinned memory is the lowest and which are nodes where most
        free memory is available.

In calculations we use orchestrator assigned memory as task memory (if available).
