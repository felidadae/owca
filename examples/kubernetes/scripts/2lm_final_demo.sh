###########################################################
# STAGE 1
###########################################################

# Show list of nodes
kubectl get nodes

# Show WCA agent running
kubectl get pods -n wca -o wide

# AEP node
kubectl drain node101 --delete-local-data --ignore-daemonsets
kubectl get nodes

# -- Show graphana dashboards and workloads spec.

# Run all workloads
kubectl scale sts redis-memtier-big --replicas=7
kubectl scale sts memcached-mutilate-big --replicas=3
# ---
kubectl scale sts sysbench-memory-small --replicas=3
kubectl scale sts sysbench-memory-medium --replicas=8
kubectl scale sts stress-stream-medium --replicas=8
# ---
kubectl scale sts redis-memtier-medium --replicas=2
kubectl scale sts redis-memtier-big-wss --replicas=4
kubectl scale sts memcached-mutilate-big-wss --replicas=4


###########################################################
# STAGE 2
###########################################################

# Kill all pods on the cluster.
kubectl scale sts --all --replicas=0

# uncordon the PMEM node
kubectl uncordon node101
kubectl get nodes

# Run WCA-Scheduler
kubectl -n wca-scheduler scale deployment wca-scheduler --replicas=1

kubectl scale sts redis-memtier-big --replicas=7
kubectl scale sts memcached-mutilate-big --replicas=3
# ---
kubectl scale sts sysbench-memory-small --replicas=3
kubectl scale sts sysbench-memory-medium --replicas=8
kubectl scale sts stress-stream-medium --replicas=8
# ---
kubectl scale sts redis-memtier-medium --replicas=2
kubectl scale sts redis-memtier-big-wss --replicas=4
kubectl scale sts memcached-mutilate-big-wss --replicas=4


###########################################################
# STAGE 3
###########################################################

# Compare performance of apps between PMEM node and DRAM nodes
# with the same CPU model: node101 vs (node103, node104, node105)
# Intel(R) Xeon(R) Gold 6240Y CPU @ 2.60GHz

# Scale down all workloads and WCA-Scheduler
kubectl scale sts --all --replicas=0
kubectl -n wca-scheduler scale deployment wca-scheduler --replicas=0

# Taint to not schedule pods on all nodes except for PMEM - node101
for node in 103 104 105 200 201 202 203 37 38 39 40; do
    kubectl taint nodes node$node wca_runner=any:NoSchedule --overwrite
done
# Reproduce WCA-Scheduler scheduling decisions on node101
kubectl scale sts redis-memtier-big --replicas=7
kubectl scale sts memcached-mutilate-big --replicas=3

# Taint node101, and untaint all nodes of the same family as node101
kubectl taint nodes node101 wca_runner=any:NoSchedule --overwrite
for node in 103 104 105; do
    kubectl taint nodes node$node wca_runner=any:NoSchedule- --overwrite
done
# Run only two extra pods, one for each of type.
kubectl scale sts redis-memtier-big --replicas=8
kubectl scale sts memcached-mutilate-big --replicas=4
