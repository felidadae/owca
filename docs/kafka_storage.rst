Building executable binary with KafkaStorage component enabled
--------------------------------------------------------------

If there is need to store metrics from WCA, **KafkaStorage** component
can be used. The component requires `confluent-kafka-python package <https://github.com/confluentinc/confluent-kafka-python>`_,
which by default is not included in the distribution file.

To build pex file with confluent-kafka-python package one should:
* install requirements: 
    * for centos: https://docs.confluent.io/current/installation/installing_cp/rhel-centos.html
* install gcc, python3 development files (for centos 7: gcc, python36-devel.x86_64)
* clone repository of confluent-kafka-python in root repository directory to the directory confluent-kafka-python,
* checkout the repository to tag **v1.0.1**
* while building Makefile target **wca_package** set variable **OPTIONAL_FEATURES** to `kafka_storage`.

We require to clone the confluent-kafka-python as wheel package of version 1.0.1 (the newest) included in PyPI cannot be bundled in
pex (https://github.com/confluentinc/confluent-kafka-python/issues/482#issuecomment-490711109).

To build confluent-kafka-python librdkafka library needs to be installed on the machine.

All commands which needs to be run to build WCA pex file with **KafkaStorage** component enabled for centos7:

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

    sudo yum clean all && sudo yum install -y librdkafka1 librdkafka-devel-1.0.0_confluent5.2.2-1.el7.x86_64
    sudo yum install -y gcc python36-devel.x86_64

    git clone https://github.com/confluentinc/confluent-kafka-python
    cd confluent-kafka-python
    git checkout v1.0.1
    cd ..
    make wca_package OPTIONAL_FEATURES=kafka_storage

On the machine on which the pex file will be run one needs librdkafka 1.0.x library.
To install only it:

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
