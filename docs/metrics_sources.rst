===============
Metrics sources
===============

**This software is pre-production and should not be deployed to production servers.**

.. contents:: Table of Contents

This documents describes briefly how metrics are collected, what is potential overhead and
how it can be enabled or disabled.

Perf event based for cgroup (task)
==================================

To collect metrics you need to provide ``event_names`` list (defaults to instructions,
cycles, cache-misses, memstalls) to runner object in config file.

Those metrics to be collected require task to be put in cgroup *perf_event* subsystem.

**Only a few or several hardware events can be collected at the same time, because
Processor have a fixed number of registers which can be programmed to gain hardware information!**

Perf event based for uncore PMUs (platform scoped)
==================================================

Resctrl based (task)
====================

To collect metrics you need to have hardware with `Intel RDT <https://www.intel.com/content/www/us/en/architecture-and-technology/resource-director-technology.html>`_ support and set ``rdt_enabled`` in config file.

Collecting of this metrics can be controlled by "rdt_enabled" option.
"rdt_enable" option accepts three values:
- None (automatically) - collection of those metrics depends on hardware and kernel support for RDT
- true - resctrl based metrics are forced to be collected and appliction will stop with error if
         it is not possible,
- false - resctrl based metrics are not collected, even if RDT is available

Cgroup based
=============

Some metrics are collected directly from cgroup filesystem from specifc controllers like cpu, cpuset
cpuacct or memory.


/proc/ or /sys/ filesystems based
==================================


