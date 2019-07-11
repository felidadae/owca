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
from typing import Tuple, List, Dict, Optional

from wca import logger
from wca.allocators import AllocationType, TaskAllocations, RDTAllocation
from wca.allocations import InvalidAllocations
from wca.logger import TRACE
from wca.metrics import Measurements, MetricName
from wca.security import SetEffectiveRootUid

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


class OutOfClosidsException(Exception):
    pass


class ResGroup:
    """Represents and abstracts operations on specific resource control group
    (represents root default group when name == RESCTRL_ROOT_NAME).
    """

    def __init__(self, name: str):
        self.name: ResGroupName = name
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
        """Writes pids to task file.

        This function is susceptible to races caused by time that passes between read and write.
        - causing errors like: ProcessLookupError

        Error handling is based on edge cases available in:
        https://github.com/torvalds/linux/blob/v4.20/arch/x86/kernel/cpu/intel_rdt_rdtgroup.c#L676
        and are mapped to python exceptions
        https://github.com/python/cpython/blob/v3.6.8/Objects/exceptions.c#L2658

        ESRCH -> ProcessLookupError
        ENOENT -> FileNotFoundError

        Important note: any writing/flushing error is going the reappear during closing,
            that is why it is again wrapped by try:except (and why context manager is not used).
        """
        if not pids:
            return

        log.log(logger.TRACE, 'resctrl: write(%s): number_of_pids=%r', tasks_filepath, len(pids))
        try:
            ftasks = open(tasks_filepath, 'w')
            with SetEffectiveRootUid():
                for pid in pids:
                    ftasks.write(pid)
                    ftasks.flush()

        except ProcessLookupError:
            log.warning('Could not write pid to resctrl (%r): '
                        'Process probably does not exist. ', tasks_filepath)
        except FileNotFoundError:
            log.error('Could not write pid to resctrl (%r): '
                      'rdt group was not found (moved/deleted - race detected).', tasks_filepath)
        except OSError as e:
            if e.errno == errno.EINVAL:
                # (kstrtoint(strstrip(buf), 0, &pid) || pid < 0)
                log.error(
                    'Could not write pid to resctrl (%r): '
                    'Invalid argument %r.', tasks_filepath)
            else:
                log.error(
                    'Could not write pid to resctrl (%r): '
                    'Unexpected errno %r.', tasks_filepath, e.errno)
        finally:
            try:
                # Try what we can to close the file but it is expected
                # to fails because the wrong # data is waiting to be flushed
                ftasks.close()
            except (ProcessLookupError, FileNotFoundError, OSError):
                log.warning('Could not close resctrl/tasks file - ignored!'
                            '(side-effect of previous warning!)')

    def _create_controlgroup_directory(self):
        """Create control group directory"""
        try:
            log.log(logger.TRACE, 'resctrl: makedirs(%s)', self.fullpath)
            os.makedirs(self.fullpath, exist_ok=True)
        except OSError as e:
            if e.errno == errno.ENOSPC:  # "No space left on device"
                raise OutOfClosidsException(
                    "Limit of workloads reached! (Oot of available CLoSes/RMIDs!)")
            raise

    def add_pids(self, pids, mongroup_name):
        """Adds the pids to the resctrl group and creates mongroup with the pids.
           If the resctrl group does not exists creates it (lazy creation).
           If the mongroup exists adds pids to the group (no error will be thrown)."""
        if self.name != RESCTRL_ROOT_NAME:
            log.debug('creating resctrl group %r', self.name)
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
        """Remove resctrl control directory or just mon_group if this is root or not last
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

    def get_measurements(self, mongroup_name, mb_monitoring_enabled,
                         cache_monitoring_enabled) -> Measurements:
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
        try:
            for socket_dir in os.listdir(os.path.join(self.fullpath,
                                                      MON_GROUPS, mongroup_name, MON_DATA)):
                if mb_monitoring_enabled:
                    with open(_get_event_file(socket_dir, MBM_TOTAL)) as mbm_total_file:
                        mbm_total += int(mbm_total_file.read())
                if cache_monitoring_enabled:
                    with open(_get_event_file(socket_dir, LLC_OCCUPANCY)) as llc_occupancy_file:
                        llc_occupancy += int(llc_occupancy_file.read())
        except FileNotFoundError:
            log.warning("Could not read measurements from rdt - ignored! "
                        "rdt group was not found (race detected)")
            return {}

        measurements = {}
        if mb_monitoring_enabled:
            measurements[MetricName.MEM_BW] = mbm_total
        if cache_monitoring_enabled:
            measurements[MetricName.LLC_OCCUPANCY] = llc_occupancy
        return measurements

    def get_allocations(self) -> TaskAllocations:
        """Return TaskAllocations representing allocation for RDT resource."""
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

    def write_schemata(self, lines: List[str]):
        """Enforce RDT allocations from task_allocations."""

        def _write_schemata_line(value, schemata_file):
            log.log(logger.TRACE, 'resctrl: write(%s): %r', schemata_file.name, value)
            try:
                schemata_file.write(bytes(value + '\n', encoding='utf-8'))
                schemata_file.flush()
            except OSError as e:
                log.error('Cannot set rdt allocation: {} with {} error is {}'.format(
                    schemata_file.name, value, e))

        with open(os.path.join(self.fullpath, SCHEMATA), 'bw') as schemata_file:
            for line in lines:
                _write_schemata_line(line, schemata_file)

    def get_mon_groups(self):
        """Return list of containers_name under mon_groups."""
        return os.listdir(os.path.join(BASE_RESCTRL_PATH, self.name, MON_GROUPS))


def cleanup_resctrl(root_rdt_l3: Optional[str], root_rdt_mb: Optional[str], reset_resctrl=False):
    """Reinitialize resctrl filesystem: by removing subfolders (both CTRL and MON groups)
    and setting default values for cache allocation and memory bandwidth (in root CTRL group).
    Can raise InvalidAllocations exception.
    """
    if reset_resctrl:
        log.info('RDT: removing all resctrl groups')

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
        log.info('RDT: reconfiguring root RDT group for L3 resource with: %r', root_rdt_l3)
        with open(os.path.join(BASE_RESCTRL_PATH, SCHEMATA), 'bw') as schemata:
            log.log(logger.TRACE, 'resctrl: write(%s): %r', schemata.name, root_rdt_l3)
            try:
                schemata.write(bytes(root_rdt_l3 + '\n', encoding='utf-8'))
                schemata.flush()
            except OSError as e:
                raise InvalidAllocations('Cannot set L3 allocation for default group: %s' % e)

    if root_rdt_mb is not None:
        log.info('RDT: reconfiguring root RDT group for MB resource with: %r', root_rdt_mb)
        with open(os.path.join(BASE_RESCTRL_PATH, SCHEMATA), 'bw') as schemata:
            log.log(logger.TRACE, 'resctrl: write(%s): %r', schemata.name, root_rdt_mb)
            try:
                schemata.write(bytes(root_rdt_mb + '\n', encoding='utf-8'))
                schemata.flush()
            except OSError as e:
                raise InvalidAllocations('Cannot set MB allocation for default group: %s' % e)


def get_max_rdt_values(cbm_mask: str, platform_sockets: int,
                       rdt_mb_control_enabled, rdt_cache_control_enabled) \
                       -> Tuple[Optional[str], Optional[str]]:
    """Calculated default maximum values for memory bandwidth and cache allocation
    based on cbm_max and number of sockets.
    returns (max_rdt_l3, max_rdt_mb) matching the platform.
    """

    max_rdt_l3 = []
    max_rdt_mb = []

    for dom_id in range(platform_sockets):
        max_rdt_l3.append('%i=%s' % (dom_id, cbm_mask))
        max_rdt_mb.append('%i=100' % dom_id)

    max_rdt_l3 = 'L3:' + ';'.join(max_rdt_l3) if rdt_cache_control_enabled else None
    max_rdt_mb = 'MB:' + ';'.join(max_rdt_mb) if rdt_mb_control_enabled else None

    return max_rdt_l3, max_rdt_mb


def check_resctrl():
    """
    :return: True if resctrl is mounted and has required file
             False if resctrl is not mounted or required file is missing
    """

    resctrl_tasks = os.path.join(BASE_RESCTRL_PATH, TASKS_FILENAME)
    try:
        with open(resctrl_tasks):
            pass
    except IOError as e:
        log.log(TRACE, 'Error: Failed to open %s: %s', resctrl_tasks, e)
        log.debug('Resctrl not mounted. ')
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
