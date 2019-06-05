=================
Kubernetes integration
=================

**This software is pre-production and should not be deployed to production servers.**

.. contents:: Table of Contents

Introduction
============

The diagram below puts Kubernetes integration in context of a cluster and monitoring infrastructure:

.. image:: kubernetes_context.png

Kubernetes supported features
========================

- Monitoring
- Allocation

Kubernetes restrictions
==================

- Kubernetes version >= 1.13.x,
- cgroup driver: `systemd` or `cgroupfs`.

Possible wca configuration options
===================================
In wca configuration file one can set below listed parameters.
Please refer to `example configuration file for kubernetes <../configs/kubernetes/kubernetes_example_allocator.yaml>`_.

.. code-block:: python

    class CgroupDriverType(str, Enum):
        SYSTEMD = 'systemd'
        CGROUPFS = 'cgroupfs'

    @dataclass
    class KubernetesNode(Node):
        # We need to know what cgroup driver is used to properly build cgroup paths for pods.
        #   Reference in source code for kubernetes version stable 1.13:
        #   https://github.com/kubernetes/kubernetes/blob/v1.13.3/pkg/kubelet/cm/cgroup_manager_linux.go#L207
        cgroup_driver: CgroupDriverType = field(
            default_factory=lambda: CgroupDriverType(CgroupDriverType.CGROUPFS))

        # By default use localhost, however kubelet may not listen on it.
        kubelet_endpoint: str = 'https://127.0.0.1:10250'

        # Key and certificate to access kubelet API, if needed.
        client_private_key: Optional[str] = None
        client_cert: Optional[str] = None

        # List of namespaces to monitor pods in.
        monitored_namespaces: List[str] = field(default_factory=lambda: ["default"])
