import logging
import os
import pprint
import re
import ruamel
from typing import List

import dataclasses
from dataclasses import dataclass

from owca.allocations import AllocationsDict, create_default_registry
from owca.allocators import Allocator, TasksAllocations, AllocationType
from owca.config import load_config
from owca.detectors import TasksMeasurements, TasksResources, TasksLabels, Anomaly
from owca.metrics import Metric
from owca.platforms import Platform
from owca.resctrl import RDTAllocation, RDTAllocationValue, ResGroup

log = logging.getLogger(__name__)


@dataclass
class StaticAllocator(Allocator):
    """
    Allocator that uses config file to decide how to configure resources for tasks.
    It tries to match task according labels and the apply given allocations.

    Config file contains so-called rules, an objects with two fields:
    - labels
    - allocations

    if there is not labels or any label match to task labels, then allocations are exectuted.
    If there is multiple matching rules all allocations are merged.
    """

    config: str

    def allocate(
            self,
            platform: Platform,
            tasks_measurements: TasksMeasurements,
            tasks_resources: TasksResources,
            tasks_labels: TasksLabels,
            tasks_allocations: TasksAllocations,
    ) -> (TasksAllocations, List[Anomaly], List[Metric]):
        if not os.path.exists(self.config):
            # Build a structure of rules for existing jobs:
            task_ids = (set(tasks_labels.keys())
                        | set(tasks_resources.keys()) | set(tasks_allocations.keys()))
            rules = []
            for task_id in task_ids:
                rule = {}
                rule['task_id'] = task_id
                if task_id in tasks_labels:
                    rule['labels'] = tasks_labels[task_id]
                if task_id in tasks_resources:
                    rule['resources'] = tasks_resources[task_id]
                if task_id in tasks_allocations:
                    task_allocations = tasks_allocations[task_id]
                    allocations_dict = {k.value: v for k, v in task_allocations.items()}
                    if allocations_dict['rdt'] is not None:
                        allocations_dict['rdt'] = dataclasses.asdict(allocations_dict['rdt'])
                    rule['allocations'] = allocations_dict
                rules.append(rule)

            # Dump configuration to file
            with open(self.config, 'w') as f:
                ruamel.yaml.dump(rules, f)
            log.info('StaticAllocator: Generate %r config file', self.config)
            return {}, [], []
        else:
            log.info('found %i tasks with labels: ', len(tasks_labels))
            for task_id, labels in tasks_labels.items():
                log.debug('%s', ' '.join('%s=%s' % (k, v) for k, v in sorted(labels.items())))

            # Load configuration and
            rules = load_config(self.config)
            if type(rules) != list:
                log.warning('StaticAllocator: improper format of config (expected list of rules)')
                return {}, [], []
            target_tasks_allocations = {}
            all_tasks_ids = (set(tasks_labels.keys())
                             | set(tasks_resources.keys()) | set(tasks_allocations.keys()))

            # and apply rules
            for rule_idx, rule in enumerate(rules):
                if 'allocations' not in rule:
                    log.warning('StaticAllocator(%s): missing "allocations" - ignore!', rule_idx)
                    continue

                log.info('StaticAllocator(%s): processing %s rule.', rule_idx,
                         '(%s)' % rule['name'] if 'name' in rule else '')

                new_task_allocations = rule['allocations']
                if 'rdt' in new_task_allocations:
                    new_task_allocations[AllocationType.RDT] = RDTAllocation(
                        **new_task_allocations['rdt'])

                # If match is by task_id just use it instead of labels
                match_task_ids = set()
                if 'task_id' in rule:
                    match_task_ids.add(rule['task_id'])
                    log.debug('StaticAllocator(%s): match by task_id=%r', rule_idx, rule['task_id'])

                # find all tasks that matches
                elif 'labels' in rule:
                    labels = rule['labels']
                    # by label
                    for task_id, task_labels in tasks_labels.items():
                        matching_label_names = set(task_labels) & set(labels)
                        for label_name in matching_label_names:
                            if re.match(str(labels[label_name]), task_labels[label_name]):
                                match_task_ids.add(task_id)
                                log.debug('StaticAllocator(%s):  match task %r by label=%s',
                                          rule_idx, task_id, label_name)
                else:
                    # no labes and no match id - matche everything
                    log.debug('StaticAllocator(%s):  match all tasks', rule_idx)
                    match_task_ids.update(all_tasks_ids)

                # for matching tasks calculcate and remember target_tasks_allocations
                log.info('StaticAllocator(%s):  applaying allocations for %i tasks', rule_idx,
                         len(match_task_ids))

                this_rule_tasks_allocations = {}

                for match_task_id in match_task_ids:
                    this_rule_tasks_allocations[match_task_id] = new_task_allocations

                registry = create_default_registry()

                def dummy_construsctor(rdt_value, ctx, registry):
                    resgroup_name = rdt_value.name or 'unknown'
                    resgroup = ResGroup(resgroup_name)
                    return RDTAllocationValue(resgroup_name, rdt_value, resgroup, None, 0, False,
                                              '', '')

                registry.register_automapping_type(RDTAllocation, dummy_construsctor)

                # Get the difference
                target_tasks_allocations, _, errors = \
                    AllocationsDict(this_rule_tasks_allocations,
                                    registry=registry).calculate_changeset(
                        AllocationsDict(target_tasks_allocations, registry=registry), )

                if errors:
                    log.warning('There are some errors in rules: %s', errors)

                target_tasks_allocations = target_tasks_allocations.unwrap_to_simple()
                log.debug('StaticAllocator(%s):  after this rule final tasks allocations: \n %s',
                          rule_idx, pprint.pformat(target_tasks_allocations))

            log.info('StaticAllocator: final tasks allocations: \n %s',
                     pprint.pformat(target_tasks_allocations))
            return target_tasks_allocations, [], []
