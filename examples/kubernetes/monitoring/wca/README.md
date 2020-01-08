Getting started
===============

To run wca in daemon set: 

1. Build image(from main project repo) and push to your registry

```
make REPO=$registry:80/ _wca_docker_devel
sudo docker push $registry:80/wca:devel
```



2. (optionally) Overwrite image name to your local repository in kustomization.yaml

```yaml
...
# kustomization.yaml
images:
  - name: wca
    newName: REPO/wca
    newTag: devel
```

Note the default image (from **kustomization.yaml**) is using private repository in testing cluster and **master** tag.

3. (optionally) Choose (**disable the default goal=service**) nodes to deploy owca using node selector

```yaml
# daemonset.yaml
spec:
    node-selector:
        kubernetes.io/hostname: node12

```

Optionally, you can use token to connect to Kube API Server, while WCA is using outside pod.
Save Bearer token and CA cert to enable connection. Set their path in wca configuration.  

```
SERVICE_ACCOUNT=wca

# Get the serviceaccount token secret name
SECRET=$(kubectl get serviceaccount ${SERVICE_ACCOUNT} -o json | jq -Mr '.secrets[].name | select(contains("token"))')

# Extract the Bearer token from the Secret and decode
kubectl get secret ${SECRET} -o json | jq -Mr '.data.token' | base64 -d > token

# Extract ca.crt from the Secret and decode
kubectl get secret ${SECRET} -o json | jq -Mr '.data["ca.crt"]' | base64 -d > ca.crt

# Get the API Server location
echo https://$(kubectl -n default get endpoints kubernetes --no-headers | awk '{ print $2 }') > server
```

Example config for wca:

```
node: !KubernetesNode
  client_token_path: "/home/user/wca/cert/token"
  server_cert_ca_path: "/home/user/wca/cert/ca.crt"
  kubeapi_host: "123.45.123.45"
  kubeapi_port: "6443"
  node_ip: "123.45.123.46"
```


Additionally, you can use following variables to connect to Kube API Server.
```
TOKEN=$(cat token)
APISERVER=$(cat server)
curl -s $APISERVER/openapi/v2  --header "Authorization: Bearer $TOKEN" --cacert ca.crt | less
```
