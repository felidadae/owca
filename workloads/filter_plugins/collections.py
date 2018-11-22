def instances_version_iter(workloads_versions, job_id):
    '''
    returns list to be ready to be iterated by
    '''
    r = []
    i = 0
    for wvn, wv in workloads_versions.items():
        try:
            unique_count = wv[job_id]['unique_count']
        except Exception:
            unique_count = 1
        for i_ in range(wv['count']):
            for i__ in range(unique_count):
                r.append((i, wvn, i__))
            i+=1
    return r
        


class FilterModule(object):
    def filters(self):
        return {
            'instances_version_iter': instances_version_iter,
        }
