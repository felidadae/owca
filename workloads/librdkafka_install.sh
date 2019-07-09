# Installation of librdkafka according to guide:
#  https://docs.confluent.io/current/installation/installing_cp/rhel-centos.html
rpm --import https://packages.confluent.io/rpm/5.2/archive.key
tee /etc/yum.repos.d/confluent.repo > /dev/null <<'EOF' 
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
yum clean all && yum install -y librdkafka1
