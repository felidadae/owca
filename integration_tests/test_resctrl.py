import subprocess, re, os
import time
from owca.resctrl import *


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
		p_ = subprocess.Popen(re.split("\s+", "stress-ng --stream 1 -v"), 
							 stdout=subprocess.PIPE, 
							 stderr=subprocess.PIPE)
		self.p_ = p_
		time.sleep(1)
	
	def is_alive(self):
		return self.p_.poll() == None

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
    """Creates one stress-ng process. Creates new resctrl group with the pid of the process."""
	stressng_ = SampleProcess()
	assert(stressng_.is_alive() == True)
	resgroup_ = ResGroup('grupa_szymona')
	resgroup_.cleanup()
	resgroup_.add_tasks(stressng_.get_pids(), 'mongrupa_januszka')
	assert(if_file_contains('/sys/fs/resctrl/grupa_szymona/tasks', stressng_.get_pids()) == True)
	assert(if_file_contains('/sys/fs/resctrl/grupa_szymona/mon_groups/mongrupa_januszka/tasks', stressng_.get_pid()) == True)
	resgroup_.remove_tasks('mongrupa_januszka')
	assert(if_file_contains('/sys/fs/resctrl/grupa_szymona/tasks', stressng_.get_pid()) == False)
	assert(if_file_contains('/sys/fs/resctrl/tasks', stressng_.get_pid()) == True)
	assert(stressng_.is_alive() == True)
	stressng_.kill()
	assert(stressng_.is_alive() == False)


def test_complex_1():
    """Move tasks between resctrl groups. """
    stressngs = [SampleProcess(), SampleProcess(), SampleProcess()]
    assert(all(p.is_alive() == True for p in stressngs))

    resgroups = [ResGroup('group_a'), ResGroup('group_b')]
    for _ in resgroups: _.cleanup()

    resgroups[0].add_tasks(stressngs[0].get_pids(), 'mongroup_0')
    resgroups[0].add_tasks(stressngs[1].get_pids(), 'mongroup_1')
    resgroups[1].add_tasks(stressngs[2].get_pids(), 'mongroup_0')

    assert(if_file_contains('/sys/fs/resctrl/group_a/tasks', stressngs[0].get_pids()) == True)
    assert(if_file_contains('/sys/fs/resctrl/group_a/tasks', stressngs[1].get_pids()) == True)
    assert(if_file_contains('/sys/fs/resctrl/group_b/tasks', stressngs[2].get_pids()) == True)

    resgroups[0].remove_tasks('mongroup_1')
    resgroups[1].add_tasks(stressngs[1].get_pids(), 'mongroup_1')

    assert(if_file_contains('/sys/fs/resctrl/group_a/tasks', stressngs[0].get_pids()) == True)
    assert(if_file_contains('/sys/fs/resctrl/group_a/mon_groups/mongroup_0/tasks', stressngs[0].get_pids()) == True)
    assert(if_file_contains('/sys/fs/resctrl/group_b/tasks', stressngs[1].get_pids()) == True)
    assert(if_file_contains('/sys/fs/resctrl/group_b/mon_groups/mongroup_1/tasks', stressngs[1].get_pids()) == True)
    assert(if_file_contains('/sys/fs/resctrl/group_b/tasks', stressngs[2].get_pids()) == True)
    assert(if_file_contains('/sys/fs/resctrl/group_b/mon_groups/mongroup_0/tasks', stressngs[2].get_pids()) == True)


if __name__ == "__main__":
    test_simple()
    test_complex_1()
