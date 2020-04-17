1. Make sure all nodes have limited frequency to 2.1Ghz.
This command will check it from terminal:

```shell
cd $path_to_insaller/scheduler_setup/
ansible -i hosts all -f 10 -m shell -a 'sudo lscpu | grep "CPU MHz:"'
```

Or not from terminal look at 
http://100.64.176.12:3000/d/G6zUvbEWz/workload-2lm-profiling?orgId=1
and at Main->node freq (check all nodes at the top).

2. Make sure wca is running on all nodes and have proper configuration files.
Check logs, check configmap (if all perf metrics are enabled - sb could change
it throughout the day).

```shell
for pod in $(kubectl get pods -n wca | grep wca | cut -f1 -d' '); do
	kubectl delete pod -n wca $pod
done
for pod in $(kubectl get pods -n wca | grep wca | cut -f1 -d' '); do
	kubectl logs -n wca $pod wca
done
```

3. If wca-scheduler is used. Check if the configmap is proper.

```shell
kubectl -n wca-scheduler scale deployment wca-scheduler --replicas=0
kubectl -n wca-scheduler scale deployment wca-scheduler --replicas=1
pod=$(kubectl get pods -n wca-scheduler | tail -1 | cut -f1 -d' ')
configmap=$(kubectl describe pod -n wca-scheduler $pod | grep 'wca-scheduler-config-' | awk '{print $2}')
kubectl describe configmap -n wca-scheduler $pod wca-scheduler | less
kubectl describe configmap -n wca-scheduler $configmap 
```

4. If wca-scheduler is used. Run runner.py with test mode.

Now run script **runner.py**:

```python
experimentset_test()
```

It will scale wca-scheduler to replicas=1 and run sample workloads on the cluster.

Check logs and make sure expecte behaviour is seen in graphana. Make sure scheduler doesnt die during experiment.
Check in graphana if decisions made by scheduler are expected. 

In case of Score algorithm check whether only
workloads with score>score_limit were scheduled on PMEM node.

To know which pods should be scheduled,
please look in wca-scheduler logs and search for apps_profile. Or check value of apps_profile
metric in prometheus but for timestamp defined in wca-scheduler configuration file.

Also make sure that proper rule for apps_profile in prometheus is defined - it should use
profile_app_2lm_score2_negative_max.

```shell
pod=$(kubectl get pods -n wca-scheduler | tail -1 | cut -f1 -d' ')
configmap=$(kubectl describe pod -n wca-scheduler $pod | grep 'wca-scheduler-config-' | awk '{print $2}')
kubectl logs -n wca-scheduler $pod wca-scheduler | less

kubectl get pods -o wide | grep node101  # node 101
```

5. Run main experiment.

Make sure you didnt changed any crucial things in runner.py by using git diff (length of experiment, DRY_RUN mode turned off, etc).
Give proper name keeping to standard given in the example: $date__$name

MAKE SURE YOU RUN THE SCRIPTS FROM TMUX - best option it would be to run it on a cluster node.

For 3-stage wca_scheduler main experiment use:

```python
experimentset_main(iterations=10, experiment_root_dir='results/202_04-16__score2_promrules')
```

For stepping-workloads experiment use:

```python
experimentset_single_workload_at_once(experiment_root_dir='results/2020-04-16__stepping_single_workloads')
```

6. Possible add new entry to runner_analyzer.py describing new experiment to having changelog.

7. Tuning.
To simplify experiments wca-scheduler use given in the config timestamp to make queries to prometheus
(so we always get the same values for workloads requirements, etc).
If applications have changed or one changed way how to calculate any resource requirements, or nodes
capacities have changed (hp enabled, less RAM or similar) one should perform tuning stage.

```python
tune_stage(ClusterInfoLoader.get_instance().get_workloads_names())
```

After 20 minutes on stdout You will be given  new timestamp. You should insert this timestamp in wca_scheduler
configuration file. Whats more You should update info about nodes and workloads in files
nodes.json workloads.json.

Remember that adding new prometheus rule will not have impact on historical data - so after new rule which will be used
by wca_scheduler You need also to perform the tuning phase.
