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

    ``cd examples/kubernetes/admission-controller/keys``
    ``openssl genrsa -out server-key.pem 2048``
    ``openssl req -new -key server-key.pem -subj "/CN=webhook.webhook.svc" -out server.csr -config csr.conf``

Execute command below and copy its output use to replace ${REQUEST} field in cert_sign_request.yaml:
    ``cat server.csr | base64 | tr -d '\n'``

Create certificate signing request:
    ``kubectl apply -f cert_sign_request.yaml``
it will be pending until approved by command:
    ``kubectl certificate approve webhook.webhook``

Generate webhook secret:
    ``serverCert=$(kubectl get csr webhook.webhook -o jsonpath='{.status.certificate}')``
    ``echo ${serverCert} | openssl base64 -d -A -out server-cert.pem``
    ``kubectl create secret generic webhook-secret --from-file=server-key.pem --from-file=server-cert.pem -n webhook``

Enter parent directory:
    ``cd ..``

Execute command below and copy its output use to replace ${CA_BUNDLE} field in mutating-webhook.yaml:
    ``kubectl get configmap -n kube-system extension-apiserver-authentication -o=jsonpath='{.data.client-ca-file}' | base64 | tr -d '\n'``

Replace ${HOST} field in webhook-deployment.yaml file with name of the node where deployment will run.

Build and push image for admission-controller
---------------------------------------------

    ``docker build -t 100.64.176.12:80/webhook:latest -f examples/kubernetes/admission-controller/Dockerfile .``

    ``docker push 100.64.176.12:80/webhook:latest``

Create namespace
----------------

    ``kubectl create namespace webhook``

Create webhook
--------------

  kubectl apply -f webhook-deployment.yaml
  kubectl apply -f webhook-svc.yaml
  kubectl apply -f mutating-webhook.yaml
