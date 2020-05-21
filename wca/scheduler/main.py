# Copyright (c) 2019 Intel Corporation
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
import os

from wca import logger
from wca.config import load_config, ConfigLoadError
from wca.scheduler.components import register_algorithms, register_dataproviders
from wca.scheduler.server import Server

DEFAULT_MODULE = 'wca.scheduler'

log = logging.getLogger(DEFAULT_MODULE + '.main')


def main(config):
    # Initialize logging subsystem.
    log_levels = {}
    log_levels.setdefault(DEFAULT_MODULE, 'info')
    logger.configure_loggers_from_dict(log_levels)

    log.warning('This software is pre-production and should not be deployed to production servers!')
    log.debug('started PID=%r', os.getpid())
    log.info('Starting wca-scheduler.')

    # Initialize all necessary objects.
    register_algorithms()
    register_dataproviders()

    try:
        configuration = load_config(config)
    except ConfigLoadError as e:
        log.error('Error: Cannot load config file! : %s', e)
        exit(1)

    # Configure loggers using configuration file.
    if 'loggers' in configuration:
        log_levels_config = configuration['loggers']
        if not isinstance(log_levels, dict):
            log.error('Loggers configuration error: log levels are mapping from logger name to'
                      'log level!')
            exit(1)

        log_levels = dict(log_levels, **log_levels_config)
        logger.configure_loggers_from_dict(log_levels)

    server = Server(configuration)

    return server.app
