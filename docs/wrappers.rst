========
Wrappers
========

**This software is pre-production and should not be deployed to production servers.**

Wrappers produce Application Performance Metrics by parsing an output of an application. The metrics can be stored in Kafka.
Output can be parsed using regular expression or a Python function.
Metrics can be normalized and labelled with user-provided values.

Wrapping ``stress-ng`` based workload example
=============================================

#. Please follow `development guide <development.rst>`_ to install dependencies.

#. Build wrappers::

    make wrapper_package

#. To build with KafkaStorage support please follow `Building executable binary with KafkaStorage component enabled <kafka_storage.rst>`_ and run::

    make wrapper_package OPTIONAL_FEATURES=kafka_storage

#. Install stress-ng (for example using ``epel`` repository)::

    sudo yum install -y stress-ng

#. Run generic wrapper based on regexp configured for stress-ng::

    dist/wrapper.pex --command '-c "while true; do stress-ng --cpu 1 --metrics 1 --timeout 1; done"' \
        --stderr 1 --log_level DEBUG --separator ".*dispatching hogs.*" \
        --regexp '(?P<name>cpu)[\ ]+(?P<value>\d+)' \
        --labels "{'workload':'stress-ng','cores':'1'}" \
        --subprocess_shell --metric_name_prefix=stress_ng_bogo_ops_

#. Similar output should be visible::

    stress-ng: info:  [26709] dispatching hogs: 1 cpu
    2018-11-26 13:58:59,327 DEBUG parser Found separator in stress-ng: info:  [26709] dispatching hogs: 1 cpu
    2018-11-26 13:58:59,327 DEBUG parser Found metric: Metric(name='stress_ng_bogo_ops_cpu', value=261.0, labels={'workload': 'stress-ng', 'cores': '1'}, type=<MetricType.COUNTER: 'counter'>, help=None)
    2018-11-26 13:58:59,327 DEBUG storage storing: 1
    # TYPE cpu counter
    stress_ng_bogo_ops_cpu{cores="1",workload="stress-ng"} 261.0 1543237139327


#. To generate normalized SLI and SLO metrics and store them in ``/tmp/metrics.txt`` file use following call::

    dist/wrapper.pex --command '-c "while true; do stress-ng --cpu 1 --metrics 1 --timeout 1; done"' \
        --stderr 1 --log_level DEBUG --separator ".*dispatching hogs.*" \
        --regexp '(?P<name>cpu)[\ ]+(?P<value>\d+)' \
        --labels "{'workload':'stress-ng','cores':'1'}" \
        --subprocess_shell --metric_name_prefix=stress_ng_bogo_ops_ \
        --slo 1000 \
        --sli_metric_name "stress_ng_bogo_ops_cpu" \
        --storage_output_filename "/tmp/metrics.txt"

#. Content of ``/tmp/metrics.txt`` should be similar to::

    cat /tmp/metrics.txt

    stress_ng_bogo_ops_cpu{cores="1",workload="stress-ng"} 261.0 1543337343583

    # HELP sli Service Level Indicator based on stress_ng_bogo_ops_cpu metric
    # TYPE sli gauge
    sli{cores="1",workload="stress-ng"} 261.0 1543337344606

    # HELP sli_normalized Normalized Service Level Indicator basd on stress_ng_bogo_ops_cpu metric and SLO
    # TYPE sli_normalized gauge
    sli_normalized{cores="1",workload="stress-ng"} 0.261 1543337344606

    # HELP slo Service Level Objective based on stress_ng_bogo_ops_cpu metric
    # TYPE slo gauge
    slo{cores="1",workload="stress-ng"} 1000.0 1543337344606


#. To log metrics to Kafka use ``--kafka_borker`` and ``--kafka_topic`` arguments::

    
    dist/wrapper.pex --command '-c "while true; do stress-ng --cpu 1 --metrics 1 --timeout 1; done"' \
        --stderr 1 --log_level DEBUG --separator ".*dispatching hogs.*" \
        --regexp '(?P<name>cpu)[\ ]+(?P<value>\d+)' \
        --subprocess_shell --metric_name_prefix=stress_ng_bogo_ops_\
        --kafka_brokers 127.0.0.1:9092 --kafka_topic wca_stress_ng


#. Verify that messages are available in ``wca_stress_ng`` topic::

    /opt/kafka/kafka-console-consumer.sh --bootstrap-server 127.0.0.1:9092 --topic wca_stress_ng --from-beginning


Command line wrapper options
--------------------------------------

.. code-block::

    usage: wrapper.pex [-h] --command COMMAND [--stderr STDERR] [--regexp REGEXP]
                       [--metric_name_prefix METRIC_NAME_PREFIX]
                       [--separator SEPARATOR]
                       [--log_level {ERROR,WARNING,INFO,DEBUG}] [--labels LABELS]
                       [--kafka_brokers KAFKA_BROKERS] [--kafka_topic KAFKA_TOPIC]
                       [--storage_output_filename STORAGE_OUTPUT_FILENAME]
                       [--peak_load PEAK_LOAD]
                       [--load_metric_name LOAD_METRIC_NAME] [--slo SLO]
                       [--sli_metric_name SLI_METRIC_NAME]
                       [--inverse_sli_metric_value] [--subprocess_shell]

    Wrapper that exposes APMs using Prometheus format.

    optional arguments:
      -h, --help            show this help message and exit
      --command COMMAND     Workload run command
      --stderr STDERR       If 0, parser will use stdout, if 1 stderr
      --regexp REGEXP       regexp used for parsing with the default parsing
                            function Needs to contain 2 named groups "name" and
                            "value"Defaults to (?P<name>\w+?)=(?P<value>\d+?.?\d*)
                            that matches values in format "a=4.0"
      --metric_name_prefix METRIC_NAME_PREFIX
                            metric name prefix (only relevant for default parse
                            function)
      --separator SEPARATOR
                            String that separates workload outputs
      --log_level {ERROR,WARNING,INFO,DEBUG}
                            Logging level
      --labels LABELS       Prometheus labels. Provide them in a dict
                            format.Example: {'workload':'stress-ng','exper':'2'}
      --kafka_brokers KAFKA_BROKERS
                            list of addresses with ports of kafka brokers (kafka
                            nodes). Coma separated
      --kafka_topic KAFKA_TOPIC
                            Kafka messages topic, passed to KafkaStorage
      --storage_output_filename STORAGE_OUTPUT_FILENAME
                            When Kafka storage is not used, allows to redirect
                            metrics to file
      --peak_load PEAK_LOAD
                            Expected maximum load.
      --load_metric_name LOAD_METRIC_NAME
                            Metric name parsed from the application stream used as
                            load level indicator. If set to `const` the behaviour
                            is slightly different: as real load were all the time
                            equal to peak_load (then load_normalized == 1).
      --slo SLO             Service level objective. Must be expressed in the same
                            units as SLI. Default value is +inf. Being used only
                            if sli_metric_name also defined.
      --sli_metric_name SLI_METRIC_NAME
                            Metric name parsed from the application stream used as
                            service level indicator.
      --inverse_sli_metric_value
                            Add this flag if value of a metric used to calculate
                            service level indicator should be inversed.
      --subprocess_shell    Run subprocess command with full shell support.

Implementing workload specific parsing function
-----------------------------------------------

Parsing function implementation must return metrics only once. Already returned values must be discarded.

See default 'parse function <wca/wrapper/default_parse.py`_ as an example.
Application specific parser functions can be found at in ```wca/wrapper/`` directory <wca/wrapper/>`_.

To handle child process exit ``readline_with_check(input)`` function should be used.
The function raises ``StopIteration`` exception when EOF is found.

.. code-block:: python

    #import
    from wca.wrapper.parser import readline_with_check

    # Read a line using readline_with_check(input)
    new_line = readline_with_check(input)
