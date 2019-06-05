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
import logging
from typing import Callable, List, Optional, Dict

from dataclasses import dataclass

from wca.allocations import AllocationValue, InvalidAllocations, LabelsUpdater
from wca.allocators import RDTAllocation
from wca.metrics import Metric, MetricType
from wca.platforms import RDTInformation
from wca.resctrl import ResGroup

log = logging.getLogger(__name__)


class RDTGroups:
    """Helper object shared among many RDTAllocationValues, that ignores perform_allocations
    on the same RDTAllocationValue if this operates on the same ResGroup (the same name) and
    verifies that number of used closids is not out of limit.
    """

    def __init__(self, closids_limit):
        self.closids_limit = closids_limit
        self.already_executed_resgroup_names = set()
        self.existing_groups = set()

    def should_perform_schemata_write(self, rdt_allocation_value):
        resgroup_name = rdt_allocation_value.get_resgroup_name()
        if resgroup_name not in self.already_executed_resgroup_names:
            self.already_executed_resgroup_names.add(resgroup_name)
            return True
        else:
            log.debug('RDTGroups: ignore schemata write - already updated!')
            return False

    def validate(self, rdt_allocation_value):
        """Count the number of all resctrl groups and return error if number of groups
        is higher than allowed. """
        self.existing_groups.add(rdt_allocation_value.get_resgroup_name())
        if len(self.existing_groups) > self.closids_limit:
            raise InvalidAllocations('too many resource groups for available CLOSids')


@dataclass
class RDTAllocationValue(AllocationValue):
    """Wrapper over immutable RDTAllocation object to perform validation, serialization
    and enforce isolation on RDT resources."""

    # Name of tasks, that RDTAllocation was assigned to.
    # Is used as resgroup.name if RDTAllocation.name is None
    container_name: str
    rdt_allocation: RDTAllocation
    resgroup: ResGroup
    get_pids: Callable[[], List[str]]  # Used as pid provider
    platform_sockets: int
    rdt_information: RDTInformation
    rdt_groups: RDTGroups
    common_labels: Dict[str, str]
    source_resgroup: Optional[ResGroup] = None  # if not none try to _cleanup it at the end

    def __post_init__(self):
        assert isinstance(self.rdt_allocation, RDTAllocation), 'type error on %r' % self
        self.labels_updater = LabelsUpdater(self.common_labels)

    def __repr__(self):
        return repr(self.rdt_allocation)

    def __eq__(self, other):
        return self.rdt_allocation == other.rdt_allocation

    def _copy(self, rdt_allocation: RDTAllocation, source_resgroup=None,
              resgroup=None):
        return RDTAllocationValue(
            container_name=self.container_name,
            rdt_allocation=rdt_allocation,
            get_pids=self.get_pids,
            resgroup=resgroup if resgroup is not None else self.resgroup,
            platform_sockets=self.platform_sockets,
            rdt_information=self.rdt_information,
            source_resgroup=source_resgroup,
            rdt_groups=self.rdt_groups,
            common_labels=self.common_labels
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
                        name='allocation_rdt_l3_cache_ways', value=_count_enabled_bits(raw_value),
                        type=MetricType.GAUGE, labels=dict(
                            allocation_type='rdt_l3_cache_ways',
                            group_name=group_name,
                            domain_id=domain_id,
                            container_name=self.container_name,
                        )
                    ),
                    Metric(
                        name='allocation_rdt_l3_mask', value=int(raw_value, 16),
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
                        name='allocation_rdt_mb', value=value, type=MetricType.GAUGE,
                        labels=dict(allocation_type='rdt_mb',
                                    group_name=group_name, domain_id=domain_id,
                                    container_name=self.container_name,
                                    )
                    )
                )

        self.labels_updater.update_labels(metrics)

        return metrics

    def get_resgroup_name(self):
        """Return explicitly set resgroup name of inferred from covering container. """
        return self.rdt_allocation.name if self.rdt_allocation.name is not None \
            else self.container_name

    def calculate_changeset(self, current: Optional['RDTAllocationValue']):
        """Merge with existing RDTAllocation objects and return
        sum of the allocations (target_rdt_allocation)
        and allocations that need to be updated (rdt_allocation_changeset).

        current can be None - means we have just spotted the task, and we're moving
                it from default root group.

        current cannot have empty name in rdt_allocation.name !!!!
        """
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
                                  source_resgroup=ResGroup(name=''))

        current_group_name = current.get_resgroup_name()

        if current_group_name != new_group_name:
            # We need to move to another group.
            log.debug('resctrl changeset: move to new group=%r from=%r',
                      current_group_name, new_group_name)
            return new, new._copy(new.rdt_allocation,
                                  resgroup=ResGroup(name=new_group_name),
                                  source_resgroup=ResGroup(name=current.get_resgroup_name()))
        else:
            log.debug('resctrl changeset: merging existing rdt allocation (the same resgroup name)')

            # Prepare target first, overwrite current l3 & mb values with new
            target_rdt_allocation = RDTAllocation(
                name=current.rdt_allocation.name,
                l3=new.rdt_allocation.l3 or current.rdt_allocation.l3,
                mb=new.rdt_allocation.mb or current.rdt_allocation.mb,
            )
            target = current._copy(target_rdt_allocation)

            # Prepare changeset
            # Logic: if new value exists and is different from old one use the new.
            if _is_rdt_suballocation_changed(current.rdt_allocation.l3,
                                             new.rdt_allocation.l3):
                new_l3 = new.rdt_allocation.l3
            else:
                log.debug('changeset l3: no change between: %r and %r' % (
                    current.rdt_allocation.l3, new.rdt_allocation.l3))
                new_l3 = None

            if _is_rdt_suballocation_changed(current.rdt_allocation.mb,
                                             new.rdt_allocation.mb):
                new_mb = new.rdt_allocation.mb
            else:
                log.debug('changeset l3: no change between: %r and %r' % (
                    current.rdt_allocation.mb, new.rdt_allocation.mb))
                new_mb = None

            if new_l3 or new_mb:
                # Only return something if schemata resources differs.
                rdt_allocation_changeset = RDTAllocation(
                    name=new.rdt_allocation.name,
                    l3=new_l3,
                    mb=new_mb,
                )
                changeset = current._copy(rdt_allocation_changeset)
                return target, changeset
            else:
                return target, None

    def validate(self):
        """Check L3 mask according platform.rdt_ features."""
        if self.rdt_allocation.l3:
            if not self.rdt_information.rdt_cache_control_enabled:
                raise InvalidAllocations('Allocator requested RDT cache allocation but '
                                         'RDT cache control is not enabled!')

            validate_l3_string(self.rdt_allocation.l3,
                               self.platform_sockets,
                               self.rdt_information.cbm_mask,
                               self.rdt_information.min_cbm_bits)
        if self.rdt_allocation.mb:
            if not self.rdt_information.rdt_mb_control_enabled:
                raise InvalidAllocations('Allocator requested RDT MB allocation but '
                                         'RDT memory bandwidth is not enabled!')
            validate_mb_string(self.rdt_allocation.mb,
                               self.platform_sockets,
                               self.rdt_information.mb_min_bandwidth)

        self.rdt_groups.validate(self)

    def perform_allocations(self):
        """Enforce L3 or MB isolation including:
        - moving to new group if source_group is not None
        - update schemata file for given RDT resources
        - remove old group (source) optional
        """

        # Move to appropriate group first.
        if self.source_resgroup is not None:
            log.debug('resctrl: perform_allocations moving to new group (from %r to %r)',
                      self.source_resgroup.name, self.resgroup.name)

            # three cases (to root, from root, or between new resgroups)
            self.resgroup.add_pids(pids=self.get_pids(),
                                   mongroup_name=self.container_name)

            if len(self.source_resgroup.get_mon_groups()) == 1:
                self.source_resgroup.remove(self.container_name)

        # Now update the schemata file.
        if self.rdt_groups.should_perform_schemata_write(self):
            lines = []
            if self.rdt_allocation.l3 and \
                    self.rdt_information.rdt_cache_control_enabled:
                lines.append(self.rdt_allocation.l3)
            if self.rdt_allocation.mb and \
                    self.rdt_information.rdt_mb_control_enabled:
                lines.append(self.rdt_allocation.mb)
            if lines:
                log.debug('resctrl: perform_allocations update schemata in %r', self.resgroup.name)
                self.resgroup.write_schemata(lines)


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


def _is_rdt_suballocation_changed(current: Optional[str], new: Optional[str]):
    """Checks whether the rdt allocation needs to be performed based on comparison
    between current and new allocations.
    The comparison is not trivial. Firstly, if new allocation is set to None no matter
    what value is assigned to current the function returns False."""
    if current is None or new is None:
        assert (current is None and new is None) or (new is None)
        return False

    def _is_equal(first, second):
        return first.lstrip(' 0') == second.lstrip(' 0')

    current_domains: Dict[str, str] = _parse_schemata_file_row(current)
    new_domains: Dict[str, str] = _parse_schemata_file_row(new)

    common_domains_names: List[str] = set(new_domains.keys()) & set(current_domains.keys())

    assert common_domains_names == set(new_domains.keys()), \
        "Assume that new allocations domain is subset of current allocations domain."

    for domain in common_domains_names:
        if not _is_equal(current_domains[domain], new_domains[domain]):
            return True
    return False


def _validate_domains(domains: List[str], platform_sockets):
    for domain in domains:
        try:
            domain_int = int(domain)
            if not (0 <= domain_int < platform_sockets):
                raise InvalidAllocations('invalid domain id - out of range'
                                         '(got=%r number_of_sockets=%i )' % (domain_int,
                                                                             platform_sockets))
        except ValueError as e:
            raise InvalidAllocations('invalid domain id - non numeric'
                                     '(got=%r error=%s)' % (domain, e))


def validate_l3_string(l3, platform_sockets, rdt_cbm_mask, rdt_min_cbm_bits):
    assert rdt_cbm_mask is not None
    assert rdt_min_cbm_bits is not None
    if not l3.startswith('L3:'):
        raise InvalidAllocations(
            'l3 resources setting should start with "L3:" prefix (got %r)' % l3)
    domains = _parse_schemata_file_row(l3)
    _validate_domains(domains, platform_sockets)

    for mask_value in domains.values():
        check_cbm_mask(mask_value,
                       rdt_cbm_mask,
                       rdt_min_cbm_bits)


def validate_mb_string(mb, platform_sockets, mb_min_bandwidth):
    assert mb_min_bandwidth is not None
    if not mb.startswith('MB:'):
        raise InvalidAllocations(
            'mb resources setting should start with "MB:" prefix (got %r)' % mb)

    domains = _parse_schemata_file_row(mb)
    _validate_domains(domains, platform_sockets)

    for mb_value in domains.values():
        check_mb_value(mb_value, mb_min_bandwidth)


def check_mb_value(mb_value: str, mb_min_bandwidth):
    try:
        mb_value = int(mb_value)
    except ValueError:
        raise InvalidAllocations("{} is not integer format".format(mb_value))

    if mb_value < mb_min_bandwidth:
        raise InvalidAllocations(
                "mb allocation smaller than minimum value {}"
                .format(str(mb_min_bandwidth)))


def _count_enabled_bits(hexstr: str) -> int:
    """Parse a raw value like f202 to number of bits enabled."""
    if hexstr == '':
        return 0
    value_int = int(hexstr, 16)
    enabled_bits_count = bin(value_int).count('1')
    return enabled_bits_count


def check_cbm_mask(mask: str, cbm_mask: str, min_cbm_bits: str):
    mask = int(mask, 16)
    cbm_mask = int(cbm_mask, 16)
    if mask > cbm_mask:
        raise InvalidAllocations('Mask is bigger than allowed')

    bin_mask = format(mask, 'b')
    number_of_cbm_bits = 0
    series_of_ones_finished = False
    previous = '0'

    for bit in bin_mask:
        if bit == '1':
            if series_of_ones_finished:
                raise InvalidAllocations('Bit series of ones in mask '
                                         'must occur without a gap between them')

            number_of_cbm_bits += 1
            previous = bit
        elif bit == '0':
            if previous == '1':
                series_of_ones_finished = True

            previous = bit

    min_cbm_bits = int(min_cbm_bits)
    if number_of_cbm_bits < min_cbm_bits:
        raise InvalidAllocations(
            str(number_of_cbm_bits) + " cbm bits. Requires minimum " + str(min_cbm_bits))
