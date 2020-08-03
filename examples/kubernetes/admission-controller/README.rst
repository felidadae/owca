Steps
=====
Lets assume that:

- ``100.64.176.12`` - is node with docker image repository.


Enable admission plugins:
-------------------------
Edit `/etc/kubernetes/manifests/kube-apiserver.yaml` file on master node:

.. code-block:: yaml

        spec:
          containers:
          - command:
          ...
          - --enable-admission-plugins=MutatingAdmissionWebhook


Prepare cluster
---------------

TLS connection
++++++++++++++

TLS is required to secure a connection.

Instructions are based on https://kubernetes.io/docs/tasks/tls/managing-tls-in-a-cluster/

You must generate a private key and Certificate Signing Request based on the private key.
Openssl is used below as a tool, but you can use another tools to generate CSR, for example cfssl.
In Certificate Signing Request the key ``subjectAltName`` has two values.
``webhook.webhook.svc`` is SVC's DNS name.
``100.64.176.36`` is example IP address, where wca-scheduler will be deployed.
You should change this IP address to address, where the wca-scheduler will be deployed.

Recommended parameters for key generations are:
- ECDSA at least 256 bits
- NIST p-256 curve for 256 bits

.. code-block:: shell

    # Generate a private key
    openssl ecparam -out key.pem -name prime256v1 -genkey

    # Generate a CSR. Change IP address to wca-scheduler node address!
    openssl req -new -key key.pem \
    -subj "/CN=webhook.webhook.svc" \
    -addext "subjectAltName=DNSwebhook.webhook.svc,IP:100.64.176.36" \
    -out server.csr \

The next step is to create CSR Kubernetes object and send it to apiserver.
It contains previously created CSR.
Created Kubernetes CertificateSigningRequest must be approved.
It can be done by an automated approval process or by a cluster administrator.
Below script uses example certificate approved by the administrator.
It is recommended to create a certificate with an expiry date of 3 years.

.. code-block:: shell

    # Create CSR K8S object
    cat <<EOF | kubectl apply -f -
    apiVersion: certificates.k8s.io/v1beta1
    kind: CertificateSigningRequest
    metadata:
      name: webhook.webhook
    spec:
      request: $(cat server.csr | base64 | tr -d '\n')
      usages:
      - digital signature
      - key encipherment
      - server auth
    EOF

    # The CSR must be approved by administrator (or automated approval process)
    kubectl certificate approve webhook.webhook

Now, you can download the signed certificate.
When you have a set of the certificate and the private key, you can create Secret using them.
The Secret will be forwarded to wca-scheduler.

.. code-block:: shell

    # Download the Certificate
    kubectl get csr webhook.webhook -o jsonpath='{.status.certificate}' | base64 --decode > server.crt

    # Create namespace webhook
    kubectl create namespace webhook

    # Create Secret with the certificate and the private key
    kubectl create secret generic webhook-secret --from-file server.crt --from-file server-key.pem --namespace webhook

Create MutatingWebhookConfiguration
+++++++++++++++++++++++++++++++++++

Execute command below and copy its output use to replace ${CA_BUNDLE} field in mutating-webhook.yaml:
``kubectl get configmap -n kube-system extension-apiserver-authentication -o=jsonpath='{.data.client-ca-file}' | base64 | tr -d '\n'``

Replace ${HOST} field in webhook-deployment.yaml file with name of the node where deployment will run.

Build and push image for admission-controller
---------------------------------------------

    ``docker build -t 100.64.176.12:80/webhook:latest -f examples/kubernetes/admission-controller/Dockerfile .``

    ``docker push 100.64.176.12:80/webhook:latest``


Create webhook
--------------

.. code-block:: shell

  kubectl apply -f webhook-deployment.yaml
  kubectl apply -f webhook-svc.yaml
  kubectl apply -f mutating-webhook.yaml

After a change in any of the mentioned files it is safer to delete all previously created objects:

.. code-block:: shell

  kubectl delete -f webhook-deployment.yaml
  kubectl delete -f webhook-svc.yaml
  kubectl delete -f mutating-webhook.yaml
