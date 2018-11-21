def instances_version_iter(workloads_versions):
    '''
    returns list to be ready to be iterated by
    '''
    r = []
    i = 0
    for wvn, wv in workloads_versions.items():
        for i_ in range(wv['count']):
            r.append((i, wvn))
            i+=1
    return r
        


class FilterModule(object):
    def filters(self):
        return {
            'instances_version_iter': instances_version_iter
        }
