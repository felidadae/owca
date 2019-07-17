Building executable binary with KafkaStorage component enabled
--------------------------------------------------------------

If there is need to store metrics from WCA, **KafkaStorage** component
can be used. The component requires `confluent-kafka-python package <https://github.com/confluentinc/confluent-kafka-python>`_,
which by default is not included in the pex WCA distribution file.

To build pex file with confluent-kafka-python package one should:

* follow part "Get the software" points 1-4 from `confluent guide <https://docs.confluent.io/current/installation/installing_cp/rhel-centos.html>`_ 
* install librdkafka1 and librdkafka-devel-1.0.0_confluent5.2.2-1.el7.x86_64 packages
* install gcc, python3 development files (for centos 7: gcc, python36-devel.x86_64)
* clone repository confluent-kafka-python in root repository directory to the directory confluent-kafka-python,
* checkout the repository to tag **v1.0.1**
* while building Makefile target **wca_package** set variable **OPTIONAL_FEATURES** to `kafka_storage`.

All commands which needs to be run to build WCA pex file with **KafkaStorage** component enabled are as follow for centos7:

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

One needs librdkafka 1.0.x on machine where pex file will be run.
To install only librdkafka library:

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


Unsafe method
-------------
We strongly advise to build the confluent-kafka-python manually due to security reasons. 
Wheel manylinux package included in PyPi contains bundled binary libraries, where some of them 
are outdated (e.g. zlib1.2.3 is included in the package and contains security vulnerabilities).
Hovewer, if You want to use the package from PyPi and skip all steps described here please run:

.. code:: shell

    export INCLUDE_UNSAFE_CONFLUENT_KAFKA_WHEEL=yes
    make wca_package
