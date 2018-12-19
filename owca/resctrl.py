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

from owca import logger
from owca.cgroups import BASE_SUBSYSTEM_PATH
from owca.metrics import Measurements, MetricName
from owca.security import SetEffectiveRootUid

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


def cleanup_resctrl():
    """Remove taskless subfolders at resctrl folders to free scarce CLOS and RMID resources. """

    def _clean_taskless_folders(initialdir, subfolder, resource_recycled):
        for entry in os.listdir(os.path.join(initialdir, subfolder)):
            # Path to folder e.g. mesos-xxx represeting running container.
            directory_path = os.path.join(BASE_RESCTRL_PATH, subfolder, entry)
            # Only examine folders at first level.
            if os.path.isdir(directory_path):
                # Examine tasks file
                resctrl_tasks_path = os.path.join(directory_path, TASKS_FILENAME)
                tasks = ''
                if not os.path.exists(resctrl_tasks_path):
                    # Skip metadata folders e.g. info.
                    continue
                with open(resctrl_tasks_path) as f:
                    tasks += f.read()
                if len(tasks.split()) == 0:
                    log.warning('Found taskless (empty) mon group at %r - recycle %s resource.'
                                % (directory_path, resource_recycled))
                    log.log(logger.TRACE, 'resctrl (mon_groups) - cleanup: rmdir(%s)',
                            directory_path)
                    os.rmdir(directory_path)

    # Remove all monitoring groups for both CLOS and RMID.
    _clean_taskless_folders(BASE_RESCTRL_PATH, '', resource_recycled='CLOS')
    # _clean_taskless_folders(BASE_RESCTRL_PATH, MON_GROUPS, resource_recycled='RMID')


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


class ResGroup:
    """Represent a resctrl group.
    If self.name == "" the object represents the root resctrl group.
    """

    def __init__(self, name):
        """Note: lazy create resctrl control group in add_tasks method."""
        self.name = name
        self.is_root_group = name == ""
        self.fullpath = BASE_RESCTRL_PATH + ("/" + name if name != "" else "")

    def is_root_group(self):
        return self.is_root_group

    def _get_mongroup_fullpath(self, mongroup_name):
        return os.path.join(self.fullpath, MON_GROUPS, mongroup_name)

    def _read_pids_from_tasks_file(self, tasks_filepath):
        pids = []
        with open(tasks_filepath) as ftasks:
            for line in ftasks:
                line = line.strip()
                if line != "":
                    pids.append(line)
        return pids

    def _add_pids_to_tasks_file(self, pids, tasks_filepath):
        with open(tasks_filepath, 'w') as ftasks:
            for pid in pids:
                try:
                    ftasks.write(pid)
                    ftasks.flush()
                except ProcessLookupError:
                    log.warning('Could not write pid %s to resctrl (%r). '
                                'Process probably does not exist. '
                                % (pid, tasks_filepath))

    def add_tasks(self, pids, mongroup_name):
        """Adds the pids to the resctrl group and creates mongroup with the pids.
           If the resctrl group does not exists creates it (lazy creation).
           If already the mongroup exists just add the pids (no error will be thrown)."""
        if not check_resctr():
            return

        # create control group directory
        if not self.is_root_group:
            try:
                log.log(logger.TRACE, 'resctrl: makedirs(%s)', self.fullpath)
                os.makedirs(self.fullpath, exist_ok=True)
            except OSError as e:
                if e.errno == errno.ENOSPC:  # "No space left on device"
                    raise Exception("Limit of workloads reached! (Oot of available CLoSes/RMIDs!)")
                raise

        # add pids to /tasks file
        self._add_pids_to_tasks_file(pids, os.path.join(self.fullpath, 'tasks'))

        # create mongroup and write tasks there
        mongroup_fullpath = self._get_mongroup_fullpath(mongroup_name)
        os.makedirs(mongroup_fullpath, exist_ok=True)
        self._add_pids_to_tasks_file(pids, os.path.join(mongroup_fullpath, 'tasks'))

    def remove_tasks(self, mongroup_name):
        """Removes the mongroup and all pids inside it from the resctrl group."""
        if not check_resctr():
            return

        # read tasks that belongs to the mongroup
        mongroup_fullpath = self._get_mongroup_fullpath(mongroup_name)
        pids = self._read_pids_from_tasks_file(os.path.join(mongroup_fullpath, 'tasks'))

        # remove the mongroup directory
        os.rmdir(mongroup_fullpath)

        # removes tasks from the group by adding it to the root group
        self._add_pids_to_tasks_file(pids, os.path.join(BASE_RESCTRL_PATH, 'tasks'))

    def get_measurements(self, mongroup_name) -> Measurements:
        """
        mbm_total: Memory bandwidth - type: counter, unit: [bytes]
        :return: Dictionary containing memory bandwidth
        and cpu usage measurements
        """
        mbm_total = 0
        llc_occupancy = 0

        def _get_event_file(mon_dir, event_name):
            return os.path.join(self.fullpath, MON_DATA, mon_dir, event_name)

        # mon_dir contains event files for specific socket:
        # llc_occupancy, mbm_total_bytes, mbm_local_bytes
        for mon_dir in os.listdir(os.path.join(self.fullpath, mongroup_name, MON_DATA)):
            with open(_get_event_file(mon_dir, MBM_TOTAL)) as mbm_total_file:
                mbm_total += int(mbm_total_file.read())
            with open(_get_event_file(mon_dir, LLC_OCCUPANCY)) as llc_occupancy_file:
                llc_occupancy += int(llc_occupancy_file.read())

        return {MetricName.MEM_BW: mbm_total, MetricName.LLC_OCCUPANCY: llc_occupancy}

    def get_allocations(self):
        task_allocations = {}
        with open(os.path.join(self.fullpath, SCHEMATA)) as schemata:
            for line in schemata:
                if 'MB' in line:
                    task_allocations[RDT_MB] = line
                elif 'L3' in line:
                    task_allocations[RDT_LC] = line

        return task_allocations

    def set_allocations(self, task_allocations):
        with open(os.path.join(self.fullpath, SCHEMATA)) as schemata:
            if task_allocations.get(RDT_MB):
                schemata.write(task_allocations[RDT_MB])

            if task_allocations.get(RDT_LC):
                schemata.write(task_allocations[RDT_LC])

    def cleanup(self):
        log.log(logger.TRACE, 'resctrl: rmdir(%s)', self.fullpath)
        os.rmdir(self.fullpath)
