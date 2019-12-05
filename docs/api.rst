
==============================
Workload Collocation Agent API
==============================

**This software is pre-production and should not be deployed to production servers.**

.. contents:: Table of Contents


MeasurementRunner
=================

	
	    MeasurementRunner run iterations to collect platform, resource, task measurements
	    and store them in metrics_storage component.
	
	    - `node`: **type**: 
	        
	        Component used for tasks discovery.
	
	    - ``metrics_storage``: **type** = `DEFAULT_STORAGE` 
	
	        Storage to store platform, internal, resource and task metrics.
	        (defaults to DEFAULT_STORAGE/LogStorage to output for standard error)
	
	    - ``action_delay``: **Numeric(0,60)** = *1.* 
	
	        Iteration duration in seconds (None disables wait and iterations).
	        (defaults to 1 second)
	
	    - ``rdt_enabled``: **Optional[bool]** = *None* 
	
	        Enables or disabled support for RDT monitoring.
	        (defaults to None(auto) based on platform capabilities)
	
	    - ``gather_hw_mm_topology``: **bool** = *False* 
	
	        Gather hardware/memory topology based on lshw and ipmctl.
	        (defaults to False)
	
	    - ``extra_labels``: **Optional[Dict[Str, Str]]** = *None* 
	
	        Additional labels attached to every metrics.
	        (defaults to empty dict)
	
	    - ``event_names``: **List[str]** = `DEFAULT_EVENTS` 
	
	        Perf counters to monitor.
	        (defaults to `DEFAULT_EVENTS` what is: instructions, cycles, cache-misses, memstalls)
	
	    - ``enable_derived_metrics``: **bool** = *False* 
	
	        Enable derived metrics ips, ipc and cache_hit_ratio.
	        (based on enabled_event names, default to False)
	
	    - ``enable_perf_uncore``: **bool** = *None* 
	
	        Enable perf event uncore metrics.
	        (defaults to None - automatic, if available enable)
	
	    - ``task_label_generators``: **Optional[Dict[str, TaskLabelGenerator]]** = *None* 
	
	        Component to generate additional labels for tasks.
	        (optional)
	
	    - ``allocation_configuration``: **Optional[AllocationConfiguration]** = *None* 
	
	        Allows fine grained control over allocations.
	        (defaults to AllocationConfiguration() instance)
	
	    - ``wss_reset_interval``: **int** = *0* 
	
	        Interval of reseting wss.
	        (defaults to 0, not measured)
	
	    - ``include_optional_labels``: **bool** = *False* 
	
	        Include optional labels like: sockets, cpus, cpu_model
	        (defaults to False)
	    

AllocationRunner
================

	    Runner is responsible for getting information about tasks from node,
	    calling allocate() callback on allocator, performing returning allocations
	    and storing all allocation related metrics in allocations_storage.
	
	    Because Allocator interface is also detector, we store serialized detected anomalies
	    in anomalies_storage and all other measurements in metrics_storage.
	
	
	    - ``measurement_runner``: **MeasurementRunner**
	
	        Measurement runner object.
	
	    - ``allocator``: **Allocator**
	
	        Component that provides allocation logic.
	
	    - ``anomalies_storage``: **Storage** = `DEFAULT_STORAGE`
	
	        Storage to store serialized anomalies and extra metrics.
	
	    - ``allocations_storage``: **tdwiboolype** = `DEFAULT_STORAGE`
	
	        Storage to store serialized resource allocations.
	
	    - ``rdt_mb_control_required``: **bool** = *False* 
	
	        Indicates that MB control is required,
	        if the platform does not support this feature the WCA will exit.
	
	    - ``rdt_cache_control_required``: **bool** = *False* 
	
	        Indicates tha L3 control is required,
	        if the platform does not support this feature the WCA will exit.
	
	    - ``remove_all_resctrl_groups``: **bool** = *False* 
	
	        Remove all RDT controls groups upon starting.
	    

DetectionRunner
===============
.. code-block:: 

	    DetectionRunner extends MeasurementRunner with ability to callback Detector,
	    serialize received anomalies and storing them in anomalies_storage.
	
	    Arguments:
	        config: Runner configuration object.
	    

MesosNode
=========
.. code-block:: 

	MesosNode(mesos_agent_endpoint:<function Url at 0x7f178dab5f28>='https://127.0.0.1:5051', timeout:wca.config.Numeric=5.0, ssl:Union[wca.security.SSL, NoneType]=None)

KubernetesNode
==============
.. code-block:: 

	KubernetesNode(cgroup_driver:wca.kubernetes.CgroupDriverType=<CgroupDriverType.CGROUPFS: 'cgroupfs'>, ssl:Union[wca.security.SSL, NoneType]=None, client_token_path:Union[wca.config.Path, NoneType]='/var/run/secrets/kubernetes.io/serviceaccount/token', server_cert_ca_path:Union[wca.config.Path, NoneType]='/var/run/secrets/kubernetes.io/serviceaccount/ca.crt', kubelet_enabled:bool=False, kubelet_endpoint:<function Url at 0x7f178dab5f28>='https://127.0.0.1:10250', kubeapi_host:<function Str at 0x7f178dab5d08>=None, kubeapi_port:<function Str at 0x7f178dab5d08>=None, node_ip:<function Str at 0x7f178dab5d08>=None, timeout:wca.config.Numeric=5, monitored_namespaces:List[Str]=<factory>)

LogStorage
==========
.. code-block:: 

	    Outputs metrics encoded in Prometheus exposition format
	    to standard error (default) or provided file (output_filename).
	    

KafkaStorage
============
.. code-block:: 

	    Storage for saving metrics in Kafka.
	
	    Args:
	        topic: name of a kafka topic where message should be saved
	        brokers_ips:  list of addresses with ports of all kafka brokers (kafka nodes)
	        max_timeout_in_seconds: if a message was not delivered in maximum_timeout seconds
	            self.store will throw FailedDeliveryException
	        extra_config: additionall key value pairs that will be passed to kafka driver
	            https://github.com/edenhill/librdkafka/blob/master/CONFIGURATION.md
	            e.g. {'debug':'broker,topic,msg'} to enable logging for kafka producer threads
	        ssl: secure socket layer object
	    

FilterStorage
=============
.. code-block:: 

	FilterStorage(storages:List[wca.storage.Storage], filter:Union[List[str], NoneType]=None)

NOPAnomalyDetector
==================
.. code-block:: 

	None

NOPAllocator
============
.. code-block:: 

	None

AllocationConfiguration
=======================
.. code-block:: 

	AllocationConfiguration(cpu_quota_period:wca.config.Numeric=1000, cpu_shares_unit:wca.config.Numeric=1000, default_rdt_l3:<function Str at 0x7f178dab5d08>=None, default_rdt_mb:<function Str at 0x7f178dab5d08>=None)

CgroupDriverType
================
.. code-block:: 

	An enumeration.

StaticNode
==========
.. code-block:: 

	    Simple implementation of Node that returns tasks based on
	    provided list on tasks names.
	
	    Tasks are returned only if corresponding cgroups exists:
	    - /sys/fs/cgroup/cpu/(task_name)
	    - /sys/fs/cgroup/cpuacct/(task_name)
	    - /sys/fs/cgroup/perf_event/(task_name)
	
	    Otherwise, the item is ignored.
	    

NUMAAllocator
=============

	
	    Allocator aimed to minimize remote NUMA memory accesses for processes.
	
	    - ``algorithm``: **NUMAAlgorithm** = *'fill_biggest_first'*:
	
	        User can choose from options: *'fill_biggest_first'*, *'minimize_migration'* to specify policy
	        determining which task is chosen to be pinned.
	
	        - *'fill_biggest_first'*
	
	            Algorithm only cares about sum of already pinned task's memory to each numa node.
	            In each step tries to pin the biggest possible task to numa node, where sum of pinned task is the lowest.
	
	        - *'minimize_migrations'*
	            
	            Algorithm tries to minimize amount of memory which needs to be remigrated between numa nodes.
	            Into consideration takes information: where a task memory is allocated (on which NUMA nodes),
	            which are nodes where the sum of pinned memory is the lowest and which are nodes where most free memory is available.
	
	    - ``loop_min_task_balance``: **float** = *0.0*:
	        
	        Minimal value of task_balance so the task is not skipped during rebalancing analysis
	        by default turn off, none of tasks are skipped due to this reason
	
	
	    - ``free_space_check``: **bool** = *False*:
	        
	        If True, then do not migrate if not enough space on target numa node.
	       
	
	    - ``migrate_pages``: **bool** = *True*:
	        
	        If use syscall "migrate pages" (forced, synchronous migrate pages of a task)
	       
	
	    - ``migrate_pages_min_task_balance``: **Optional[float]** = *0.95*:
	        
	        Works if migrate_pages == True. Then if set tells, when remigrate pages of already pinned task. 
	        If not at least migrate_pages_min_task_balance * TASK_TOTAL_SIZE bytes of memory resides on pinned node, then # tries to remigrate all pages allocated on other nodes to target node.
	
	
	    - ``cgroups_cpus_binding``: **bool** = *True*:
	        
	        cgroups based cpu pinning
	       
	
	    - ``cgroups_memory_binding``: **bool** = *False*:
	        
	        cgroups based memory binding
	        
	
	    - ``cgroups_memory_migrate``: **bool** = *False*:
	
	        cgroups based memory migrating; can be used only when 
	        cgroups_memory_binding is set to True
	
	
	    - ``dryrun``: **bool** = *False*:
	        
	        If set to True, do not make any allocations - can be used for debugging.
	
	    

NUMAAlgorithm
=============
.. code-block:: 

	solve bin packing problem by heuristic which takes the biggest first

StaticAllocator
===============
.. code-block:: 

	    Simple allocator based on rules defining relation between task labels
	    and allocation definition (set of concrete values).
	
	    The allocator reads allocation rules from a yaml file and directly
	    from constructor argument (passed as python dictionary).
	    Refer to configs/extra/static_allocator_config.yaml to see sample
	    input file for StaticAllocator.
	
	    A rule is an object with three fields:
	    - name,
	    - labels (optional),
	    - allocations.
	
	    First field is just a helper to name a rule.
	    Second field contains a dictionary, where each key is a task's label name and
	    the value is a regex defining the matching set of label values. If the field
	    is not included then all tasks match the rule.
	    The third field is a dictionary of allocations which should be applied to
	    matching tasks.
	
	    If there are multiple matching rules then the rules' allocations are merged and applied.
	    

SSL
===
.. code-block:: 

	    Common configuration for SSL communication.
	
	    * server_verify: Union[bool, Path(absolute=True, mode=os.R_OK)] = True
	    * client_cert_path: Optional[Path(absolute=True, mode=os.R_OK)] = None
	    * client_key_path: Optional[Path(absolute=True, mode=os.R_OK)] = None
	
	    

TaskLabelRegexGenerator
=======================
.. code-block:: 

	Generate new label value based on other label value.

DefaultDerivedMetricsGenerator
==============================
.. code-block:: 

	None

UncoreDerivedMetricsGenerator
=============================
.. code-block:: 

	None

