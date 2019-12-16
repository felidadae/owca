Building executable binary with KafkaStorage component enabled
--------------------------------------------------------------

If there is need to store metrics from WCA in `Apache Kafka <https://kafka.apache.org>`_,
**KafkaStorage** component can be used. 

To support this feature WCA uses libraries: 

- `librdkafka <https://github.com/edenhill/librdkafka>`_
- `confluent-kafka-python package <https://github.com/confluentinc/confluent-kafka-python>`_


Building executable binary (distribution)
-----------------------------------------

To build executable binary inside a docker (using `Dockerfile <../Dockerfile.kafka>`_), run:

.. code:: shell

   make wca_package_in_docker_with_kafka

Runtime requirements
--------------------

One needs `librdkafka <https://github.com/edenhill/librdkafka>`_ of version **1.0.x**
on machine where pex file will be run.  Run commands to install it on centos 7
(taken from `confluent guide <https://docs.confluent.io/current/installation/installing_cp/rhel-centos.html>`_):

.. code:: shell

    sudo rpm --import https://packages.confluent.io/rpm/5.2/archive.key
    sudo tee /etc/yum.repos.d/confluent.repo > /dev/null <<'EOF'
    [Confluent.dist]
    name=Confluent repository (dist)
    baseurl=https://packages.confluent.io/rpm/5.2/7
    gpgcheck=1
    gpgkey=https://packages.confluent.io/rpm/5.2/archive.key
    enabled=1

    [Confluent]
    name=Confluent repository
    baseurl=https://packages.confluent.io/rpm/5.2
    gpgcheck=1
    gpgkey=https://packages.confluent.io/rpm/5.2/archive.key
    enabled=1
    EOF

    sudo yum clean all && sudo yum install -y librdkafka1
