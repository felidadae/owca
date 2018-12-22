from owca.resctrl import ResGroup
from owca.allocators import RDTAllocation

import subprocess
import re
import time


def if_file_contains(filepath, patterns):
    # check if array is passed
    if type(patterns) == str:
        patterns = [patterns]

    with open(filepath) as ffile:
        content = " ".join(ffile.readlines())
        for pattern in patterns:
            if pattern not in content:
                return False
        return True


class SampleProcess:
    def __init__(self):
        p_ = subprocess.Popen(re.split(r"\s+", "stress-ng --stream 1 -v"),
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        self.p_ = p_
        time.sleep(1)

    def is_alive(self):
        return self.p_.poll() is None

    def get_pid(self):
        """get root pid"""
        return str(self.p_.pid)

    def get_pids(self):
        """the main process and children processes"""
        _pid = str(self.p_.pid)
        children = subprocess.check_output("pgrep -P {}".format(_pid).split()).decode('utf-8').split()
        return [_pid] + children

    def kill(self):
        self.p_.terminate()
        while self.is_alive():
            time.sleep(0.3)


def test_simple():
    """Creates one stress-ng process.
       Creates new resctrl group with the pid of the process."""
    stressng_ = SampleProcess()
    assert stressng_.is_alive()
    resgroup_ = ResGroup('grupa_szymona')
    resgroup_.add_tasks([], 'mongrupa_januszka')
    resgroup_.cleanup()

    # pids are in the files
    resgroup_.add_tasks(stressng_.get_pids(), 'mongrupa_januszka')
    assert if_file_contains('/sys/fs/resctrl/grupa_szymona/tasks', stressng_.get_pids())
    assert if_file_contains('/sys/fs/resctrl/grupa_szymona/mon_groups/mongrupa_januszka/tasks', stressng_.get_pid())

    # set and check rdt allocations
    l3_ = ('L3:0=000ff;1=000ff', 'L3:0=00fff;1=00fff')
    for i in range(2):
        task_allocations = { 
            'cpu_quota': 0.6,
            'cpu_shares': 0.8,
            'rdt': RDTAllocation(name='hp_group', l3=l3_[i])
        }
        resgroup_.perform_allocations(task_allocations)
        assert resgroup_.get_allocations()['rdt'].l3.strip() == l3_[i]
        assert if_file_contains('/sys/fs/resctrl/grupa_szymona/schemata', l3_[i])

    # pids are not longer in the tasks files
    resgroup_.remove_tasks('mongrupa_januszka')
    assert not if_file_contains('/sys/fs/resctrl/grupa_szymona/tasks', stressng_.get_pid())

    # but still available in root ctrlgroup
    assert if_file_contains('/sys/fs/resctrl/tasks', stressng_.get_pid())
    assert stressng_.is_alive()

    # cleanup
    stressng_.kill()
    assert not stressng_.is_alive()

    assert not if_file_contains('/sys/fs/resctrl/tasks', stressng_.get_pid())
    resgroup_.cleanup()


def test_complex_1():
    """Move tasks between resctrl groups. """
    p0, p1, p2 = SampleProcess(), SampleProcess(), SampleProcess()
    processes = [p0, p1, p2]

    assert all(p.is_alive() for p in processes)

    resgroups = [ResGroup('g0'), ResGroup('g1')]
    g0, g1 = resgroups
    for rg in resgroups:
        rg.cleanup()

    # p0 and p1 to r0
    g0.add_tasks(p0.get_pids(), 'p0')
    g0.add_tasks(p1.get_pids(), 'p1')

    # p2 to r1
    g1.add_tasks(p2.get_pids(), 'p2')

    # check ctrl cgroups pids
    assert if_file_contains('/sys/fs/resctrl/g0/tasks', p0.get_pids())
    assert if_file_contains('/sys/fs/resctrl/g0/tasks', p1.get_pids())
    assert if_file_contains('/sys/fs/resctrl/g1/tasks', p2.get_pids())

    # move p1 from g0 to g1
    g0.remove_tasks('p1')
    g1.add_tasks(p1.get_pids(), 'p1')

    # g0/p0 still contains p0
    assert if_file_contains('/sys/fs/resctrl/g0/tasks', p0.get_pids())
    assert if_file_contains('/sys/fs/resctrl/g0/mon_groups/p0/tasks', p0.get_pids())

    # there is no g0/p1 anymore
    # p1 is in g1/p1 now
    assert if_file_contains('/sys/fs/resctrl/g1/tasks', p1.get_pids())
    assert if_file_contains('/sys/fs/resctrl/g1/mon_groups/p1/tasks', p1.get_pids())

    # p2 is still in g1/p2
    assert if_file_contains('/sys/fs/resctrl/g1/tasks', p2.get_pids())
    assert if_file_contains('/sys/fs/resctrl/g1/mon_groups/p2/tasks', p2.get_pids())

    for p in processes:
        p.kill()

    time.sleep(1)
    for p in processes:
        assert not p.is_alive()

    assert not if_file_contains('/sys/fs/resctrl/g0/tasks', p0.get_pid())
    assert not if_file_contains('/sys/fs/resctrl/g0/mon_groups/p0/tasks', p0.get_pid())
    assert not if_file_contains('/sys/fs/resctrl/g1/tasks', p1.get_pid())
    assert not if_file_contains('/sys/fs/resctrl/g1/mon_groups/p1/tasks', p1.get_pid())
    assert not if_file_contains('/sys/fs/resctrl/g1/tasks', p2.get_pid())
    assert not if_file_contains('/sys/fs/resctrl/g1/mon_groups/p2/tasks', p2.get_pid())

    for rg in resgroups:
        rg.cleanup()
