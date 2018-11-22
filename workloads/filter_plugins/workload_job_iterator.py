def workload_job_iterator(workloads_versions, job_id):
    """
    Build list of dicts, where each dict item has 3 key-value pairs,
    used in the playbook to iterate through 1) workload instances count, 2) workload versions,
    3) job replica count.

    I suppose it does not really match what a jinja2 filter should
    consitute (general purpose, not matching just one use case).
    However, in that particular situation it is much simpler to write the custom filter
    than construct the result using build-in jinja2 filters.

    [(workload_instance_index, workload_version_name, job_replica_index), ... ]
    [ {0, small, 0}, {0, small, 1}, {0, small, 2},
      {1, small, 0}, {1, small, 1}, {1, small, 2},
      {2, big, 0}, {2, big, 1},
      {3, big, 0}, {3, big, 1} ]
    """
    r = []
    i = 0
    for workload_version_name, workload_version in workloads_versions.items():

        try:
            job_replica_count = int(workload_version[job_id]['count'])
        except Exception:
            job_replica_count = 1
        if 'count' not in workload_version:
            job_replica_count = 1

        for workload_instance_index in range(workload_version['count']):
            for job_replica_index in range(job_replica_count):
                r.append({'workload_instance_index': workload_instance_index,
                          'workload_version_name': workload_version_name,
                          'job_replica_index': job_replica_index})
            i+=1
    return r


class FilterModule(object):
    def filters(self):
        return { 'workload_job_iterator': workload_job_iterator }
