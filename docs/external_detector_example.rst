=========================
External detector example
=========================

**This software is pre-production and should not be deployed to production servers.**

Before running the example you must:

- Set up Mesos cluster with Aurora framework.
- Be able to connect to Mesos operator API available at ``https://127.0.0.1:5051``

Assuming that external implementation of detector is provided as
`external_package <../example/external_package.py>`_ in ``example`` module and called ``ExampleDetector`` defined as:

.. code:: python

    #example/external_package.py

    from wca import detectors
    from wca import mesos
    from wca import metrics


    class ExampleDetector(detectors.AnomalyDetector):
        """Always return anomaly for given task."""

        def __init__(self, task_id: mesos.TaskId):
            self.task_id = task_id

        def detect(
                self,
                platform: Platform,
                tasks_measurements: TasksMeasurements,
                tasks_resources: TasksResources,
                tasks_labels: TasksLabels
                ) -> (List[Anomaly], List[Metric]):
            anomalies = [
                detectors.ContentionAnomaly(
                    resource=detectors.ContendedResource.CPUS
                    contended_task_id='task1',
                    contending_task_ids=['task2', 'task3']
                    metrics=[Metric(name="a_threshold", value=66.6, type="gauge")]
                )
            ]
            debugging_metrics = [
                metrics.Metric(
                    name='some_debug',
                    value=2,
                    labels=dict(
                        version=2,
                    )
                )
            ]
            return anomalies, debugging_metrics


when configuration file `mesos_external_detector.yaml <example/mesos_external_detector.yaml>`_ is used:

.. code:: yaml

    runner: !DetectionRunner
      node: !MesosNode
      action_delay: 1.
      storage: !LogStorage
      detector: !ExampleDetector
        task_id: 'some_task_id'


you can run WCA in following way. Remember to use the absolute configuration path:

.. code:: shell-session

    dist/wca.pex -c ${pwd}configs/mesos_external_detector.yaml -r example.external_package:ExampleDetector -l debug

you will see similar output:

.. code:: shell-session

    2018-07-13 14:51:32,829 DEBUG    {MainThread} [wca.logger] level=DEBUG
    2018-07-13 14:51:32,829 DEBUG    {MainThread} [wca.main] started PID=30048
    2018-07-13 14:51:32,913 DEBUG    {MainThread} [wca.storage] [Metric(name='platform_dummy', value=1, labels={}, type=None, help=None)]
    2018-07-13 14:51:32,913 DEBUG    {MainThread} [wca.storage] [Metric(name='anomaly', value=1, labels={'task_id': 'task_id', 'resource': <ContendedResource.CPUS: 'cpus'>, 'uuid': <bound method ContentionAnomaly.uuid of ContentionAnomaly(task_ids=['task_id'], resource=<ContendedResource.CPUS: 'cpus'>)>}, type=<MetricType.COUNTER: 'counter'>, help=None), Metric(name='some_debug', value=2, labels={'version': 2}, type=None, help=None)]

Register API (optionally)
-------------------------

Instead of providing a class as command line argument you can register it using annotations:


.. code:: python

    #example_package/example_module.py

    ...
    from wca import config

    @config.register
    class ExampleDetector(detectors.AnomalyDetector):
        ...


then you can run WCA just providing configuration file:


.. code:: shell-session

    dist/wca.pex -c /etc/wca/example.yaml -l debug
