from typing import Dict, List, Tuple
from pprint import pprint

# for testing, temporarily, do not want to bring new dependency
from numpy.random import normal as np_normal

from wca.allocators import AllocationType
from wca.detectors import TaskData, TasksData, TaskResource
from wca.metrics import MetricName, MetricValue
from wca.platforms import Platform


GB = 1000 ** 3
MB = 1000 ** 2

TaskId = str
NodeId = int
Assignments = Dict[TaskId, NodeId]


class Resources:
    def __init__(self, cpu, mem, membw):
        self.cpu = cpu
        self.mem = mem
        self.membw = membw

    def __repr__(self):
        return str({'cpu': self.cpu, 'mem': float(self.mem)/float(GB), 'membw': float(self.membw)/float(GB)})

    def create_empty():
        return Resources(0,0,0)

    def substract(self, b):
        self.cpu -= b.cpu
        self.mem -= b.mem
        self.membw -= b.membw

    def __bool__(self):
        return self.cpu >= 0 and self.mem >= 0 and self.membw >= 0

    def copy(self):
        return Resources(self.cpu, self.mem, self.membw)


class Node:
    def __init__(self, name, resources):
        self.name = name
        self.initial = resources
        self.real = resources.copy()
        self.unassigned = resources.copy()
    
    def __repr__(self):
        return "(name: {}, unassigned: {}, initial: {}, real: {})".format(self.name, str(self.unassigned), str(self.initial), str(self.real))

    def validate_assignment(self, tasks, new_task):
        """if unassigned > free_not_unassigned"""
        unassigned = self.initial.copy()
        for task in tasks:
            if task.assignment == self:
                unassigned.substract(task.initial)
        unassigned.substract(new_task.initial)
        return bool(unassigned) == True

    def update(self, tasks):
        self.real = self.initial.copy()
        self.unassigned = self.initial.copy()
        for task in tasks:
            if task.assignment == self:
                self.real.substract(task.real)
                self.unassigned.substract(task.initial)

    def create_apache_pass():
        return Node('0', Resources(96, 1000 * GB, 50 * GB))

    def create_standard():
        return Node('1', Resources(96, 150 * GB, 150 * GB))


class Task:
    def __init__(self, name, initial, assignment=None):
        self.name = name
        self.initial = initial 
        self.assignment = assignment

        self.real = Resources.create_empty()
        self.life_time = 0

    def update(self, delta_time):
        self.life_time += delta_time
        # Here simply just if, life_time > 0 assign all
        self.real = self.initial.copy()

    def create_stressng(i, assignment=None):
        r = Resources(8, 10 * GB, 10 * GB)
        t = Task('stress_ng_{}'.format(i), r)
        return t

    def create_random_stressng(i, assignment=None):
        def normal_random(loc, scale):
            r = int(np_normal(loc, scale))
            return r if r >= 1 else 1

        r = Resources(normal_random(8, 5),
                      normal_random(10, 8) * GB,
                      normal_random(10, 8) * GB)
        t = Task('stress_ng_{}'.format(i), r)
        return t

    def create_deterministic_stressng(i):
        pass

    def __repr__(self):
        return "(name: {}, assignment: {}, initial: {}, real: {})".format(
                self.name, 'None' if self.assignment is None else self.assignment.name, 
                str(self.initial), str(self.real))


class Symulator:
    def __init__(self, tasks, nodes, scheduler):
        self.tasks = tasks
        self.nodes = nodes
        self.scheduler = scheduler
        self.time = 0

    def reset(self):
        self.tasks = []
        self.time = 0

    def update_tasks_usage(self, delta_time):
        for task in self.tasks:
            task.update(delta_time)

    def update_tasks_list(self, changes):
        deleted, created = changes
        self.tasks = [task for task in self.tasks if task not in deleted]
        for new in created:
            new.assignment = None
            self.tasks.append(new)

    def calculate_new_state(self):
        for node in self.nodes:
            node.update(self.tasks)
        
    def validate_assignment(self, task: Task, assignment: Node) -> bool:
        return assignment.validate_assignment(self.tasks, task)

    def perform_assignments(self, assignments: Dict[TaskId, Node]) -> int:
        assigned_count = 0
        for task in self.tasks:
            if task.name in assignments:
                if self.validate_assignment(task, assignments[task.name]):
                    task.assignment = assignments[task.name]
                    assigned_count += 1
        return assigned_count

    def iterate(self, delta_time: int, changes: Tuple[List[Task], List[Task]]) -> int:
        self.time += delta_time
        self.update_tasks_usage(delta_time)
        self.update_tasks_list(changes)

        # Update state after deleting tasks.
        self.calculate_new_state()

        assignments = self.scheduler.schedule(self.nodes, [task for task in self.tasks if task.assignment is None])
        pprint("Assignments: {}".format({task_name: node.name for task_name, node in assignments.items()}))
        assigned_count = self.perform_assignments(assignments)

        # Recalculating state after assignments being performed.
        self.calculate_new_state()

        return assigned_count


class Scheduler:
    def schedule(self, nodes: List[Node], tasks: List[Task]) -> Assignments:
        pass


class FillFirstCpuOnlyScheduler(Scheduler):
    def schedule(self, nodes: List[Node], unassigned: List[Task]) -> Assignments:
        assignments = {}
       
        # only looks at cpu
        for task in sorted(unassigned, key=lambda task: task.initial.cpu, reverse=True):
            max_free_cpu_node = sorted(nodes, key=lambda node: node.unassigned.cpu, reverse=True)[0]
            assignments[task.name] = max_free_cpu_node

        return assignments


class FillFirst3DScheduler(Scheduler):
    def _3d_to_1d(resources) -> int:
        return resources.cpu * resources.mem * resources.membw

    def schedule(self, nodes: List[Node], unassigned: List[Task]) -> Assignments:
        assignments = {}

        if len(unassigned) == 0:
            return {}
        assert len(unassigned) == 1

        unassigned = unassigned[0]

        for node in nodes:
            pass

        return assignments


def log_state(iteration, symulator):
    print()
    pprint("Iteration {}".format(iteration))
    pprint("Nodes: ")
    pprint(symulator.nodes)
    pprint("Tasks: ")
    pprint(symulator.tasks)


def single_stress_ng(index):
    return [Task.create_stressng(index+1)]
def random_stress_ng(index):
    return [Task.create_random_stressng(index+1)]


def test_symulator():
    symulator = Symulator(
        tasks = [], 
        nodes = [Node.create_apache_pass(), Node.create_standard()],
        scheduler = FillFirstCpuOnlyScheduler()
    )

    for scheduler in (
            # FillFirstCpuOnlyScheduler(), 
            FillFirst3DScheduler(),
        ):
        symulator.scheduler = scheduler
        symulator.reset()
        for task_creation_fun in (
                single_stress_ng, 
                # random_stress_ng,
            ):
            all_assigned_count = 0
            assigned_count = -1
            iteration = 0
            while assigned_count != 0:
                log_state(iteration, symulator)
                changes = ([], task_creation_fun(iteration))
                assigned_count = symulator.iterate(delta_time=1, changes=changes)
                all_assigned_count += assigned_count
                iteration += 1

            print("scheduler: {}, task_creation_fun: {}, assigned_count: {}".format(
                scheduler, task_creation_fun, all_assigned_count))
