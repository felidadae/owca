# Copyright (c) 2020 Intel Corporation
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
# limitations under the License
import argparse
import logging

from wca.config import load_config, ConfigLoadError
from wca.admission_controller.service import AnnotatingService
from wca import logger
from wca.admission_controller.components import register_components

DEFAULT_MODULE = 'wca.admission_controller'

log = logging.getLogger(DEFAULT_MODULE + '.main')


def main():
    #  Parse file argument
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', required=True, help='Configuration file')
    args = parser.parse_args()
    # Initialize logging subsystem.
    log_levels = {}
    log_levels.setdefault(DEFAULT_MODULE, 'info')
    logger.configure_loggers_from_dict(log_levels)

    register_components()

    try:
        configuration = load_config(args.config)
    except ConfigLoadError as e:
        log.error('Cannot load config file! : %s', e)
        exit(1)

    if 'loggers' in configuration:
        log_levels_config = configuration['loggers']
        if not isinstance(log_levels, dict):
            log.error('Loggers configuration error: log levels are mapping from logger name to'
                      'log level!')
            exit(1)
        log_levels = dict(log_levels, **log_levels_config)
        logger.configure_loggers_from_dict(log_levels)

    annotating_service = AnnotatingService(configuration)
    annotating_service.app.run(host="0.0.0.0", ssl_context=('./ssl/server-cert.pem',  # nosec
                               './ssl/server-key.pem'))  # nosec


if __name__ == '__main__':
    main()
