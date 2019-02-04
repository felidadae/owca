# Copyright (c) 2018 Intel Corporation

#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import errno
import logging
import os
from typing import Tuple, List, Optional, Dict, Callable

from dataclasses import dataclass

from owca import logger
from owca.allocations import AllocationValue
from owca.allocations import AllocationValueRecreatingWrapper
from owca.allocators import AllocationType, TaskAllocations
from owca.logger import TRACE
from owca.metrics import Measurements, MetricName, Metric, MetricType
from owca.security import SetEffectiveRootUid

RESCTRL_ROOT_NAME = ''
BASE_RESCTRL_PATH = '/sys/fs/resctrl'
MON_GROUPS = 'mon_groups'
TASKS_FILENAME = 'tasks'
SCHEMATA = 'schemata'
INFO = 'info'
MON_DATA = 'mon_data'
MON_L3_00 = 'mon_L3_00'
MBM_TOTAL = 'mbm_total_bytes'
LLC_OCCUPANCY = 'llc_occupancy'
RDT_MB = 'rdt_MB'
RDT_LC = 'rdt_LC'

log = logging.getLogger(__name__)

ResGroupName = str


class ResGroup:
    """ Represents ctrl group (can represent root default when name == RESCTRL_ROOT_NAME)"""

    def __init__(self, name: str, rdt_mb_control_enabled: bool = True):
        self.name: ResGroupName = name
        self.rdt_mb_control_enabled = rdt_mb_control_enabled
        self.fullpath = BASE_RESCTRL_PATH + ("/" + name if name != "" else "")

    def __repr__(self):
        return 'ResGroup(name=%r, fullpath=%r)' % (self.name, self.fullpath)

    def _get_mongroup_fullpath(self, mongroup_name) -> str:
        return os.path.join(self.fullpath, MON_GROUPS, mongroup_name)

    def _read_pids_from_tasks_file(self, tasks_filepath):
        with open(tasks_filepath) as ftasks:
            pids = [line.strip() for line in ftasks.readlines() if line != ""]
        log.log(logger.TRACE, 'resctrl: read(%s): found %i pids', tasks_filepath, len(pids))
        return pids

    def _add_pids_to_tasks_file(self, pids, tasks_filepath):
        log.log(logger.TRACE, 'resctrl: write(%s): number_of_pids=%r', tasks_filepath, len(pids))
        with open(tasks_filepath, 'w') as ftasks:
            with SetEffectiveRootUid():
                for pid in pids:
                    try:
                        ftasks.write(pid)
                        ftasks.flush()
                    except ProcessLookupError:
                        log.warning('Could not write pid %s to resctrl (%r). '
                                    'Process probably does not exist. ', pid, tasks_filepath)

    def _create_controlgroup_directory(self):
        """Create control group directory"""
        try:
            log.log(logger.TRACE, 'resctrl: makedirs(%s)', self.fullpath)
            os.makedirs(self.fullpath, exist_ok=True)
        except OSError as e:
            if e.errno == errno.ENOSPC:  # "No space left on device"
                raise Exception("Limit of workloads reached! (Oot of available CLoSes/RMIDs!)")
            raise

    def add_pids(self, pids, mongroup_name):
        """Adds the pids to the resctrl group and creates mongroup with the pids.
           If the resctrl group does not exists creates it (lazy creation).
           If the mongroup exists adds pids to the group (no error will be thrown)."""
        if self.name != RESCTRL_ROOT_NAME:
            log.debug('creating restrcl group %r', self.name)
            self._create_controlgroup_directory()

        # CTRL GROUP
        # add pids to /tasks file
        log.debug('add_pids: %d pids to %r', len(pids), os.path.join(self.fullpath, 'tasks'))
        self._add_pids_to_tasks_file(pids, os.path.join(self.fullpath, 'tasks'))

        # MON GROUP
        # create mongroup ...
        mongroup_fullpath = self._get_mongroup_fullpath(mongroup_name)
        try:
            log.log(logger.TRACE, 'resctrl: makedirs(%s)', mongroup_fullpath)
            os.makedirs(mongroup_fullpath, exist_ok=True)
        except OSError as e:
            if e.errno == errno.ENOSPC:  # "No space left on device"
                raise Exception("Limit of workloads reached! (Oot of available CLoSes/RMIDs!)")
            raise
        # ... and write the pids to the mongroup
        log.debug('add_pids: %d pids to %r', len(pids), os.path.join(mongroup_fullpath, 'tasks'))
        self._add_pids_to_tasks_file(pids, os.path.join(mongroup_fullpath, 'tasks'))

    def remove(self, mongroup_name):
        """Remove resctrl ctrl directory or just mon_group if this is root or not last
        container under control.
         """
        # Try to clean itself if I'm the last mon_group and not root.

        if self.name == RESCTRL_ROOT_NAME:
            log.debug('resctrl: remove root')
            dir_to_remove = self._get_mongroup_fullpath(mongroup_name)
        else:
            # For non root
            # Am I last on the remove all.
            if len(self.get_mon_groups()) == 1:
                log.debug('resctrl: remove ctrl directory %r', self.name)
                dir_to_remove = self.fullpath
            else:
                log.debug('resctrl: remove just mon_group %r in %r', mongroup_name, self.name)
                dir_to_remove = self._get_mongroup_fullpath(mongroup_name)

        # Remove the mongroup directory.
        with SetEffectiveRootUid():
            log.log(logger.TRACE, 'resctrl: rmdir(%r)', dir_to_remove)
            os.rmdir(dir_to_remove)

    def get_measurements(self, mongroup_name) -> Measurements:
        """
        mbm_total: Memory bandwidth - type: counter, unit: [bytes]
        :return: Dictionary containing memory bandwidth
        and cpu usage measurements
        """
        mbm_total = 0
        llc_occupancy = 0

        def _get_event_file(socket_dir, event_name):
            return os.path.join(self.fullpath, MON_GROUPS, mongroup_name,
                                MON_DATA, socket_dir, event_name)

        # Iterate over sockets to gather data:
        for socket_dir in os.listdir(os.path.join(self.fullpath,
                                                  MON_GROUPS, mongroup_name, MON_DATA)):
            with open(_get_event_file(socket_dir, MBM_TOTAL)) as mbm_total_file:
                mbm_total += int(mbm_total_file.read())
            with open(_get_event_file(socket_dir, LLC_OCCUPANCY)) as llc_occupancy_file:
                llc_occupancy += int(llc_occupancy_file.read())

        return {MetricName.MEM_BW: mbm_total, MetricName.LLC_OCCUPANCY: llc_occupancy}

    def get_allocations(self) -> TaskAllocations:
        """Return TaskAllocations represeting allocation for RDT resource."""
        rdt_allocations_mb, rdt_allocations_l3 = None, None
        with open(os.path.join(self.fullpath, SCHEMATA)) as schemata:
            for line in schemata:
                if 'MB:' in line:
                    rdt_allocations_mb = line.strip()
                elif 'L3:' in line:
                    rdt_allocations_l3 = line.strip()

        rdt_allocations = RDTAllocation(
            name=self.name,
            l3=rdt_allocations_l3,
            mb=rdt_allocations_mb,
        )
        return {AllocationType.RDT: rdt_allocations}

    def write_schemata(self, l3=None, mb=None):
        """Enforce RDT allocations from task_allocations."""

        def _write_schemata_line(value, schemata_file):

            log.log(logger.TRACE, 'resctrl: write(%s): %r', schemata_file.name, value)
            try:
                schemata_file.write(bytes(value + '\n', encoding='utf-8'))
                schemata_file.flush()
            except OSError as e:
                log.error('Cannot set rdt allocation: {}'.format(e))

        with open(os.path.join(self.fullpath, SCHEMATA), 'bw') as schemata_file:

            # Cache allocation.
            if l3:
                _write_schemata_line(l3, schemata_file)

            # Optional memory bandwidth allocation.
            if self.rdt_mb_control_enabled and mb:
                _write_schemata_line(mb, schemata_file)

    def get_mon_groups(self):
        """Return list of containers_name under mon_groups."""
        return os.listdir(os.path.join(BASE_RESCTRL_PATH, self.name, MON_GROUPS))


#
# ------------------------ Allocation -----------------------------------
#

@dataclass(unsafe_hash=True, frozen=True)
class RDTAllocation:
    # defaults to TaskId from TasksAllocations
    name: str = None
    # CAT: optional - when no provided doesn't change the existing allocation
    l3: str = None
    # MBM: optional - when no provided doesn't change the existing allocation
    mb: str = None


@dataclass
class RDTAllocationValue(AllocationValue):
    """Wrapper over immutable RDTAllocation object"""

    # Name of tasks, that RDTAllocation was assigned to.
    # Is used as resgroup.name if RDTAllocation.name is None
    container_name: str
    rdt_allocation: RDTAllocation
    resgroup: ResGroup
    get_pids: Callable[[], List[str]]  # Used as pid provider
    platform_sockets: int
    rdt_mb_control_enabled: bool
    rdt_cbm_mask: str
    rdt_min_cbm_bits: str

    source_resgroup: Optional[ResGroup] = None  # if not none try to _cleanup it at the end

    def __post_init__(self):
        assert isinstance(self.rdt_allocation, RDTAllocation), 'type error on %r' % self

    def __repr__(self):
        return 'RDTAllocationValue(rdt_allocation=%r)' % self.rdt_allocation

    def _copy(self, rdt_allocation: RDTAllocation, source_resgroup=None,
              container_name: str = None, resgroup=None):
        return RDTAllocationValue(
            container_name=container_name or self.container_name,
            rdt_allocation=rdt_allocation,
            get_pids=self.get_pids,
            resgroup=resgroup if resgroup is not None else self.resgroup,
            platform_sockets=self.platform_sockets,
            rdt_mb_control_enabled=self.rdt_mb_control_enabled,
            rdt_cbm_mask=self.rdt_cbm_mask,
            rdt_min_cbm_bits=self.rdt_min_cbm_bits,
            source_resgroup=source_resgroup,
        )

    def generate_metrics(self) -> List[Metric]:
        """Encode RDT Allocation as metrics.
        Note:
        - cache allocation: generated two metrics, with number of cache ways and
                            mask of bits (encoded as int)
        - memory bandwidth: is encoded as int, representing MB/s or percentage
        """
        # Empty object generate no metric.
        if not self.rdt_allocation.l3 and not self.rdt_allocation.mb:
            return []

        group_name = self.get_resgroup_name()

        metrics = []
        if self.rdt_allocation.l3:
            domains = _parse_schemata_file_row(self.rdt_allocation.l3)
            for domain_id, raw_value in domains.items():
                metrics.extend([
                    Metric(
                        name='allocation', value=_count_enabled_bits(raw_value),
                        type=MetricType.GAUGE, labels=dict(
                            allocation_type='rdt_l3_cache_ways',
                            group_name=group_name,
                            domain_id=domain_id,
                            container_name=self.container_name,
                        )
                    ),
                    Metric(
                        name='allocation', value=int(raw_value, 16),
                        type=MetricType.GAUGE, labels=dict(
                            allocation_type='rdt_l3_mask', group_name=group_name,
                            domain_id=domain_id,
                            container_name=self.container_name,
                        )
                    )
                ])

        if self.rdt_allocation.mb:
            domains = _parse_schemata_file_row(self.rdt_allocation.mb)
            for domain_id, raw_value in domains.items():
                # NOTE: raw_value is treated as int, ignoring unit used (MB or %)
                value = int(raw_value)
                metrics.append(
                    Metric(
                        name='allocation', value=value, type=MetricType.GAUGE,
                        labels=dict(allocation_type='rdt_mb',
                                    group_name=group_name, domain_id=domain_id,
                                    container_name=self.container_name,
                                    )
                    )
                )

        return metrics

    def get_resgroup_name(self):
        return self.rdt_allocation.name if self.rdt_allocation.name is not None \
            else self.container_name

    def calculate_changeset(self, current):
        """Merge with existing RDTAllocation objects and return
        sum of the allocations (target_rdt_allocation)
        and allocations that need to be updated (rdt_allocation_changeset).

        current can be None - means we have just spotted the task, and we're moving
                it from default root group.

        current cannot have empty name in rdt_allocation.name !!!!
        """
        assert isinstance(current,
                          (type(None), AllocationValue)), 'type error on current=%r ' % current

        if current is not None:
            current = current.unwrap_to_leaf()

        assert isinstance(current,
                          (type(None), RDTAllocationValue)), 'type error on current=%r ' % current

        # Any rdt_allocation that comes with current have to have rdt_allocation.name set)
        assert current is None or (current.rdt_allocation is not None)

        new: RDTAllocationValue = self
        new_group_name = new.get_resgroup_name()

        # new name, then new allocation will be used (overwrite) but no merge
        if current is None:
            # New tasks or is moved from root group.
            log.debug(
                'resctrl changeset: new name or no previous allocation exists (moving from root '
                'group!)')
            return new, new._copy(new.rdt_allocation,
                                  resgroup=ResGroup(name=new_group_name),
                                  source_resgroup=ResGroup(name='')), []

        current_group_name = current.get_resgroup_name()

        if current_group_name != new_group_name:
            # We need to move to another group.
            log.debug('resctrl changeset: move to new group=%r from=%r',
                      new.resgroup.name, current.get_resgroup_name())
            return new, new._copy(new.rdt_allocation,
                                  resgroup=ResGroup(name=new_group_name),
                                  source_resgroup=ResGroup(name=current.get_resgroup_name())), []
        else:
            errors = []
            log.debug('resctrl changeset: merging existing rdt allocation (the same resgroup name)')

            # Prepare target first, overwrite current l3 & mb values with new
            target_rdt_allocation = RDTAllocation(
                name=current.rdt_allocation.name,
                l3=new.rdt_allocation.l3 or current.rdt_allocation.l3,
                mb=new.rdt_allocation.mb or current.rdt_allocation.mb,
            )
            target = current._copy(target_rdt_allocation)

            # Prepare changeset
            # Logic: if new value exists and is different from old one the use new.
            if new.rdt_allocation.l3 is not None \
                    and current.rdt_allocation.l3 != new.rdt_allocation.l3:
                new_l3 = new.rdt_allocation.l3
            else:
                new_l3 = None

            if new.rdt_allocation.mb is not None \
                    and current.rdt_allocation.mb != new.rdt_allocation.mb:
                new_mb = new.rdt_allocation.mb
            else:
                new_mb = None

            if new_l3 or new_mb:
                # Only return something if schemata resources differs.
                rdt_allocation_changeset = RDTAllocation(
                    name=new.rdt_allocation.name,
                    l3=new_l3,
                    mb=new_mb,
                )
                changeset = current._copy(rdt_allocation_changeset)
                return target, changeset, errors
            else:
                return target, None, errors

    def validate(self) -> Tuple[List[str], Optional['RDTAllocationValue']]:
        errors = []
        # Check l3 mask according provided platform.rdt
        if self.rdt_allocation.l3:
            try:
                if not self.rdt_allocation.l3.startswith('L3:'):
                    raise ValueError('l3 resources setting should '
                                     'start with "L3:" prefix (got %r)' % self.rdt_allocation.l3)
                domains = _parse_schemata_file_row(self.rdt_allocation.l3)
                if len(domains) != self.platform_sockets:
                    raise ValueError('not enough domains in l3 configuration '
                                     '(expected=%i,got=%i)' % (self.platform_sockets,
                                                               len(domains)))

                for mask_value in domains.values():
                    check_cbm_bits(mask_value,
                                   self.rdt_cbm_mask,
                                   self.rdt_min_cbm_bits)
            except ValueError as e:
                errors.append('Invalid l3 cache config(%r): %s' % (self.rdt_allocation.l3, e))
        if errors:
            return errors, None
        else:
            return [], self

    def perform_allocations(self):
        """
        - move to new group is source_group is not None
        - update schemata file
        - remove old group (source) optional
        """
        # move to approriate group first
        if self.source_resgroup is not None:
            log.debug('resctrl: perform_allocations moving to new group (%s -> %s)',
                      self.source_resgroup.name, self.resgroup.name)

            # three cases (to root, from root, or between new resgroups)
            self.resgroup.add_pids(pids=self.get_pids(),
                                   mongroup_name=self.container_name)

            if len(self.source_resgroup.get_mon_groups()) == 1:
                self.source_resgroup.remove(self.container_name)

        # now update the schema
        if self.rdt_allocation.l3 or self.rdt_allocation.mb:
            log.debug('resctrl: perform_allocations update schemata in %s', self.resgroup.name)
            self.resgroup.write_schemata(
                l3=self.rdt_allocation.l3,
                mb=self.rdt_allocation.mb
            )

    def unwrap(self):
        return self.rdt_allocation


#
# ------------------------ initialization -----------------------------------
#

def cleanup_resctrl(root_rdt_l3: str, root_rdt_mb: str, reset_resctrl=False):
    """Reinitialize resctrl filesystem: by removing subfolders (both CTRL and MON groups)
    and setting default values for cache allocation and memory bandwidth (in root CTRL group).
    """
    if reset_resctrl:
        def _remove_folders(initialdir, subfolder):
            """Removed subfolders of subfolder of initialdir """
            for entry in os.listdir(os.path.join(initialdir, subfolder)):
                directory_path = os.path.join(BASE_RESCTRL_PATH, subfolder, entry)
                # Only examine folders at first level.
                if os.path.isdir(directory_path):
                    # Examine tasks file
                    resctrl_tasks_path = os.path.join(directory_path, TASKS_FILENAME)
                    if not os.path.exists(resctrl_tasks_path):
                        # Skip metadata folders e.g. info.
                        continue
                    log.warning(
                        'Resctrl: Found ctrl or mon group at %r - recycle CLOS/RMID resource.',
                        directory_path)
                    log.log(logger.TRACE, 'resctrl (mon_groups) - _cleanup: rmdir(%s)',
                            directory_path)
                    os.rmdir(directory_path)

        # Remove all monitoring groups for both CLOS and RMID.
        _remove_folders(BASE_RESCTRL_PATH, MON_GROUPS)
        # Remove all resctrl groups.
        _remove_folders(BASE_RESCTRL_PATH, '')

    # Reinitialize default values for RDT.
    if root_rdt_l3 is not None:
        with open(os.path.join(BASE_RESCTRL_PATH, SCHEMATA), 'bw') as schemata:
            log.log(logger.TRACE, 'resctrl: write(%s): %r', schemata.name, root_rdt_l3)
            try:
                schemata.write(bytes(root_rdt_l3 + '\n', encoding='utf-8'))
                schemata.flush()
            except OSError as e:
                log.error('Cannot set L3 cache allocation: {}'.format(e))

    if root_rdt_mb is not None:
        with open(os.path.join(BASE_RESCTRL_PATH, SCHEMATA), 'bw') as schemata:
            log.log(logger.TRACE, 'resctrl: write(%s): %r', schemata.name, root_rdt_mb)
            try:
                schemata.write(bytes(root_rdt_mb + '\n', encoding='utf-8'))
                schemata.flush()
            except OSError as e:
                log.error('Cannot set rdt memory bandwidth allocation: {}'.format(e))


def get_max_rdt_values(cbm_mask: str, platform_sockets: int) -> Tuple[str, str]:
    """Calculated default maximum values for memory bandwidth and cache allocation
    based on cbm_max and number of sockets.
    returns (max_rdt_l3, max_rdt_mb) matching the platform.
    """

    max_rdt_l3 = []
    max_rdt_mb = []

    for dom_id in range(platform_sockets):
        max_rdt_l3.append('%i=%s' % (dom_id, cbm_mask))
        max_rdt_mb.append('%i=100' % dom_id)

    return 'L3:' + ';'.join(max_rdt_l3), 'MB:' + ';'.join(max_rdt_mb)


def check_resctrl():
    """
    :return: True if resctrl is mounted and has required file
             False if resctrl is not mounted or required file is missing
    """
    run_anyway_text = 'If you wish to run script anyway,' \
                      'please set rdt_enabled to False in configuration file.'

    resctrl_tasks = os.path.join(BASE_RESCTRL_PATH, TASKS_FILENAME)
    try:
        with open(resctrl_tasks):
            pass
    except IOError as e:
        log.debug('Error: Failed to open %s: %s', resctrl_tasks, e)
        log.critical('Resctrl not mounted. ' + run_anyway_text)
        return False

    mon_data = os.path.join(BASE_RESCTRL_PATH, MON_DATA, MON_L3_00, MBM_TOTAL)
    try:
        with open(mon_data):
            pass
    except IOError as e:
        log.debug('Error: Failed to open %s: %s', mon_data, e)
        log.critical('Resctrl does not support Memory Bandwidth Monitoring.' +
                     run_anyway_text)
        return False

    return True


def read_mon_groups_relation() -> Dict[str, List[str]]:
    """Read the file structure of resctrl filesystem and return on relations
    between control groups and its monitoring groups in form:
    ctrl_group_name: [mon_group_name1, mon_group_name2]

    Root control group has '' name (empty string).
    """

    relation = dict()
    # root ctrl group mon dirs
    root_mon_group_dir = os.path.join(BASE_RESCTRL_PATH, MON_GROUPS)
    assert os.path.isdir(root_mon_group_dir)
    root_mon_groups = os.listdir(root_mon_group_dir)
    relation[''] = root_mon_groups

    ctrl_group_names = os.listdir(BASE_RESCTRL_PATH)
    for ctrl_group_name in ctrl_group_names:
        ctrl_group_dir = os.path.join(BASE_RESCTRL_PATH, ctrl_group_name)
        if os.path.isdir(ctrl_group_dir):
            mon_group_dir = os.path.join(ctrl_group_dir, MON_GROUPS)
            if os.path.isdir(mon_group_dir):
                relation[ctrl_group_name] = os.listdir(mon_group_dir)
    return relation


def clean_taskless_groups(mon_groups_relation: Dict[str, List[str]]):
    """Remove all control and monitoring group based on list of already read
    groups from mon_groups_relation.
    """
    for ctrl_group, mon_groups in mon_groups_relation.items():
        for mon_group in mon_groups:
            ctrl_group_dir = os.path.join(BASE_RESCTRL_PATH, ctrl_group)
            mon_group_dir = os.path.join(ctrl_group_dir, MON_GROUPS, mon_group)
            tasks_filename = os.path.join(mon_group_dir, TASKS_FILENAME)
            mon_groups_to_remove = []
            with open(tasks_filename) as tasks_file:
                if tasks_file.read() == '':
                    mon_groups_to_remove.append(mon_group_dir)

            if mon_groups_to_remove:
                log.debug('mon_groups_to_remove: %r', mon_groups_to_remove)

                # For ech non root group, drop just ctrl group if all mon groups are empty
                if ctrl_group != '' and \
                        len(mon_groups_to_remove) == len(mon_groups_relation[ctrl_group]):
                    log.log(TRACE, 'rmdir(%r)', ctrl_group_dir)
                    os.rmdir(ctrl_group_dir)
                else:
                    for mon_group_to_remove in mon_groups_to_remove:
                        os.rmdir(mon_group_to_remove)
                        log.log(TRACE, 'rmdir(%r)', mon_group_to_remove)


class DeduplicatingRDTAllocationsValue(AllocationValueRecreatingWrapper):
    """Wrapper over RDTAllocationsValus, that ignores perform_allocations
    on the same RDTAllocationValue if this operates on the same ResGroup (the same name).

    Have to be created properly, thats shares resgroup names set with other objects
    of this kind but only for one run.
    """

    def __init__(self, rdt_allocation_value: RDTAllocationValue,
                 maximum_closids,
                 already_executed_resgroup_names: set,
                 existing_groups: set):
        super().__init__(rdt_allocation_value)
        self.maximum_closids = maximum_closids
        self.rdt_allocation_value = rdt_allocation_value
        self.already_executed_resgroup_names = already_executed_resgroup_names
        self.existing_groups = existing_groups
        self.existing_groups.add(rdt_allocation_value.get_resgroup_name())

    def _recreate_me(self, allocation_value):
        return DeduplicatingRDTAllocationsValue(
            allocation_value,
            self.maximum_closids,
            self.already_executed_resgroup_names,
            self.existing_groups,
        )

    def perform_allocations(self):
        force_execution = (self.rdt_allocation_value.rdt_allocation.name is None or
                           self.rdt_allocation_value.source_resgroup is not None)

        resgroup_name = self.rdt_allocation_value.get_resgroup_name()
        if force_execution or resgroup_name not in self.already_executed_resgroup_names:
            self.rdt_allocation_value.perform_allocations()
            self.already_executed_resgroup_names.add(
                resgroup_name
            )
        else:
            log.debug('DeduplicatingRDTAllocationsValue: %s already performed', resgroup_name)

    def validate(self):
        """Count the number of all resctrl groups and return error if number of groups
        is higher than allowed. """
        errors, new_rdt_allocation_value = self.rdt_allocation_value.validate()
        if new_rdt_allocation_value is not None:
            if len(self.existing_groups) > self.maximum_closids:
                assert isinstance(errors, list)
                errors = list(errors)
                errors.extend(['too many closids(%s)!' % len(self.existing_groups)])
                return errors, None
        return errors, self._recreate_me(new_rdt_allocation_value) if new_rdt_allocation_value \
            else None


#
# ------------------------ helpers -----------------------------------
#

def _parse_schemata_file_row(line: str) -> Dict[str, str]:
    """Parse RDTAllocation.l3 and RDTAllocation.mb strings based on
    https://elixir.bootlin.com/linux/latest/source/arch/x86/kernel/cpu/intel_rdt_ctrlmondata.c#lL206
    and return dict mapping and domain id to its configuration (value).
    Resource type (e.g. mb, l3) is dropped.

    Eg.
    mb:1=20;2=50 returns {'1':'20', '2':'50'}
    mb:xxx=20mbs;2=50b returns {'1':'20mbs', '2':'50b'}
    raises ValueError exception for inproper format or conflicting domains ids.
    """
    RESOURCE_ID_SEPARATOR = ':'
    DOMAIN_ID_SEPARATOR = ';'
    VALUE_SEPARATOR = '='

    domains = {}

    # Ignore emtpy line.
    if not line:
        return {}

    # Drop resource identifier prefix like ("mb:")
    line = line[line.find(RESOURCE_ID_SEPARATOR) + 1:]
    # Domains
    domains_with_values = line.split(DOMAIN_ID_SEPARATOR)
    for domain_with_value in domains_with_values:
        if not domain_with_value:
            raise ValueError('domain cannot be empty')
        if VALUE_SEPARATOR not in domain_with_value:
            raise ValueError('Value separator is missing "="!')
        separator_position = domain_with_value.find(VALUE_SEPARATOR)
        domain_id = domain_with_value[:separator_position]
        if not domain_id:
            raise ValueError('domain_id cannot be empty!')
        value = domain_with_value[separator_position + 1:]
        if not value:
            raise ValueError('value cannot be empty!')

        if domain_id in domains:
            raise ValueError('Conflicting domain id found!')

        domains[domain_id] = value

    return domains


def _count_enabled_bits(hexstr: str) -> int:
    """Parse a raw value like f202 to number of bits enabled."""
    if hexstr == '':
        return 0
    value_int = int(hexstr, 16)
    enabled_bits_count = bin(value_int).count('1')
    return enabled_bits_count


def check_cbm_bits(mask: str, cbm_mask: str, min_cbm_bits: str):
    mask = int(mask, 16)
    cbm_mask = int(cbm_mask, 16)
    if mask > cbm_mask:
        raise ValueError('Mask is bigger than allowed')

    bin_mask = format(mask, 'b')
    number_of_cbm_bits = 0
    series_of_ones_finished = False
    previous = '0'

    for bit in bin_mask:
        if bit == '1':
            if series_of_ones_finished:
                raise ValueError('Bit series of ones in mask '
                                 'must occur without a gap between them')

            number_of_cbm_bits += 1
            previous = bit
        elif bit == '0':
            if previous == '1':
                series_of_ones_finished = True

            previous = bit

    min_cbm_bits = int(min_cbm_bits)
    if number_of_cbm_bits < min_cbm_bits:
        raise ValueError(str(number_of_cbm_bits) +
                         " cbm bits. Requires minimum " +
                         str(min_cbm_bits))
