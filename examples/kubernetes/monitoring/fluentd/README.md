### DEBUGGING

Deleting fluentd daemonsets and configmaps:
```bash
kubectl delete ds --all -n fluentd ; kubectl delete cm --all -n fluentd
```

Creating fluentd daemonset and service. Observing daemonset rollout status:
```bash
kubectl apply -k . -n fluentd ; k -n fluentd rollout status ds fluentd
```

Fluentd logs. Replace `$hostname` with your host:
```bash
while sleep 1 ; do kubectl -n fluentd logs --tail 5 --follow `kubectl get pods -owide -n fluentd |grep $hostname | awk '{print $1}'`; done
curl 100.64.176.40:24231/metrics
```


