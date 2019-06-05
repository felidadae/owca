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


"""
Main entry point.

Responsible for configuration and prepare components
and start main loop from Runner.
"""
import argparse
import logging
import os

from wca import components
from wca import config
from wca import logger
from wca import platforms
from wca.config import assure_type
from wca.runners import Runner

log = logging.getLogger('wca.main')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-c', '--config',
        help="Configuration", default=None, required=True)
    parser.add_argument(
        '-l',
        '--log-level',
        help='Log level for modules (by default for wca) in [module:]level form,'
             'where level can be one of: CRITICAL,ERROR,WARNING,INFO,DEBUG,TRACE'
             'Example -l debug -l example:debug. Defaults to wca:INFO.'
             'Can be overridden at runtime with config.yaml "loggers" section.',
        default=[],
        action='append',
        dest='levels',
    )
    parser.add_argument(
        '-r', '--register', action='append', dest='components',
        help="Register additional components in config", default=[])
    parser.add_argument(
        '-v', '--version', action='version', version=platforms.get_wca_version(),
        help="Show version")
    parser.add_argument(
        '-0', '--root', help="Allow WCA process to be run using root account",
        dest='is_root_allowed', action='store_true')

    args = parser.parse_args()

    # Do not allow to run WCA with root privileges unless user indicates that it is intended.
    uid = os.geteuid()
    if uid == 0 and not args.is_root_allowed:
        log.fatal("Do not run WCA with root privileges. Consult documentation "
                  "to understand what capabilities are required. If root account "
                  "has to be used then set --root/-0 argument to override.")
        exit(2)

    # Initialize logging subsystem from command line options.
    log_levels = logger.parse_loggers_from_list(args.levels)
    log_levels.setdefault(logger.DEFAULT_MODULE, 'info')
    logger.configure_loggers_from_dict(log_levels)

    log.warning('This software is pre-production and should not be deployed to production servers.')
    log.debug('started PID=%r', os.getpid())
    log.info('Version wca: %s', platforms.get_wca_version())

    # Register internal & external components.
    components.register_components(extra_components=args.components)

    if not os.path.isabs(args.config):
        log.error(
            'Error: The config path \'%s\' is not valid. The path must be absolute.'
            % args.config)
        exit(1)

    # Initialize all necessary objects.
    try:
        configuration = config.load_config(args.config)
    except config.ConfigLoadError as e:
        log.error('Error: Cannot load config file %r: %s', args.config, e)
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.exception('Detailed exception:')
        exit(1)

    for key in configuration:
        if key != 'loggers' and key != 'runner':
            log.error('Error: Unknown field in configuration '
                      'file: {}. Possible fields are: \'loggers\', '
                      '\'runner\''.format(key))
            exit(1)

    assure_type(configuration, dict)
    assert 'runner' in configuration, 'Improper config - missing runner instance!'

    # Configure loggers using configuration file.
    if 'loggers' in configuration:
        log_levels_config = configuration['loggers']
        if not isinstance(log_levels, dict):
            log.error('Loggers configuration error: log levels are mapping from logger name to'
                      'log level got "%r" instead!' % log_levels_config)
            exit(1)
        # Merge config from cmd line and config file.
        # Overwrite config file values with values provided from command line.
        log_levels = dict(log_levels, **log_levels_config)
        logger.configure_loggers_from_dict(log_levels)

    # Dump loggers configurations  to debug issues with loggers.
    if os.environ.get('WCA_DUMP_LOGGERS') == 'True':
        print('------------------------------------ Logging tree ---------------------')
        import logging_tree
        logging_tree.printout()
        print('------------------------------------ Logging tree END------------------')

    # Extract main loop component.
    runner = configuration['runner']
    assure_type(runner, Runner)

    # Prepare and run the "main loop".
    exit_code = runner.run()
    exit(exit_code)


def debug():
    """Debug hook to allow entering debug mode in compiled pex.
    Run it as PEX_MODULE=wca.main:debug
    """
    import warnings
    try:
        import ipdb as pdb
    except ImportError:
        warnings.warn('ipdb not available, using pdb')
        import pdb
    pdb.set_trace()
    main()


if __name__ == '__main__':
    main()
