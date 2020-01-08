**This software is pre-production and should not be deployed to production servers.**

========
Examples
========

+-----------------------------------------------------------------------------------------------+
| Sandbox deployment recommendation warning                                                     |
+===============================================================================================+
| These workloads definitions and wrapper applications are not                                  |
| meant to be run as production workloads.                                                      |
| Workloads definitions are provided only for performance evaluation purposes                   |
| and should be run only in fully controlled and isolated sandbox environments.                 |
|                                                                                               |
| They were build with performance and usability in mind, with following assumption:            |
|                                                                                               | 
| - not to be mixed with production workloads, because of lack of resource and access isolation,|
| - to be run without network isolation,                                                        |
| - run with privileged account (root account),                                                 |
| - are based on third-party docker images,                                                     |
| - to be run by cluster (environment) owner/operator, not by cluster users,                    |
| - those workloads were tested only in limited specific configuration (Centos 7.5, Mesos 1.2.3,|
|   Kubernetes 1.13, Docker 18.09.2)                                                            |
|                                                                                               |
| Possible implications:                                                                        |
|                                                                                               |
| - load generators may cause very resource intensive work, that can interfere with             |
|   you existing infrastructure on network, storage and compute layer                           |
| - there are no safety mechanisms so improperly constructed command definition,                |
|   can causes leak of private sensitive information,                                           |
|                                                                                               |
| Please treat these workloads definitions as reference code. For production usage for specific |
| orchestrator software and configuration, please follow recommendation from                    |
| official documentation:                                                                       |
|                                                                                               |
| - `Kubernetes <https://kubernetes.io/docs/home/>`_                                            |
| - `Mesos <https://mesos.apache.org/documentation/latest/index.html>`_                         |
| - `Aurora <http://aurora.apache.org/documentation/>`_                                         |
+-----------------------------------------------------------------------------------------------+

This folder contains three examples how to extend or deploy WCA integrated with full monitoring stack and example workloads that were used for evaluation:

- `simple "hello world" <hello_world_runner.py>`_ runner to show how easily WCA can be extended, details `here <../docs/extending.rst>`_
- `external_package.py file <external_package.py>`_ for full-fledged example of **externally provided detector** describe `here <../docs/external_detector_example.rst>`_
- `workloads for Mesos and Kubernetes <workloads>`_ for WCA testing and evaluation that can be scheduled on Mesos and Kubernetes using Ansible playbook with performance reporting using wrappers,
- `Kubernetes manifests <kubernetes>`_ for deploying WCA and Kubernetes-only workloads using `Kustomize <https://kustomize.io/>`_
- `example manifests for monitoring with WCA <kubernetes/monitoring>`_ for deploying WCA as `DaemonSet in Kubernetes <../docs/kubernetes.rst#run-wca-as-daemonset-on-cluster>`_ including full monitoring stack with Prometheus, Grafana and Fluentd


