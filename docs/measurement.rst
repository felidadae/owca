=====================
Measurement interface
=====================

**This software is pre-production and should not be deployed to production servers.**

.. contents:: Table of Contents

Introduction
------------
MeasurementRunner run iterations to collect platform, resource, task measurements from ``node`` and store them in ``metrics_storage`` component.

Configuration
-------------

Example of configuration that uses ``MeasurementRunner``:

.. code:: yaml

        runner: !MeasurementRunner
          node: !StaticNode
            tasks:
              - task1
          metrics_storage: !LogStorage
            output_filename: 'metrics.prom'
            overwrite: true


Available arguments
-------------------

Please refer to `API documentation of MeasurementRunner <api.rst#MeasurementRunner>`_.
