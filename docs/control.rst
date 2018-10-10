===========================
Control algorithm interface
===========================


Control interface reuses existing Detector input and metric structures.
Please use `detection.rst` for further reference on ``Platform``, ``TaskResources``, ``TasksMeasurements`` and 
``TaskLabels`` structures.


Allocate resource callback 
--------------------------

You can configure system to reconfigure allocations on specific resources, but using ``ControlRunner`` type in
configuration file  ``config.yaml`` in following way:

.. code:: yaml

    runner: !ControlRunner
      node: !MesosNode
      delay: 1.                                 # [s]
      controller: 

Please note that previously required property of ``DetectionRunner``


``ControlRunner`` structure has following required and optional properties.

.. code:: yaml


