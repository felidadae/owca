#!/usr/bin/env python3.6
import argparse
import fileinput
from shutil import copyfile
import re


if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-p', '--features_history_period',
        dest='period',
        help="Register additional components in config",
        default="3d",
        required=True)
    parser.add_argument(
        '-o', '--output',
        dest='output',
        help="Name output file",
        default="prometheus_rule_score.yaml")

    args = parser.parse_args()
    config_name = args.output

    period = args.period
    assert re.match('\d+\w', period)

    # Prepare regex
    period_regex_search = r'\[\d+\w\]'
    period_regex_replace = '[{}]'.format(period)

    # Copy template
    copyfile('prometheus_rule.score.yaml.template', config_name)

    # Replace
    with fileinput.FileInput(config_name, inplace=True) as file:
        for line in file:
            print(re.sub(period_regex_search, period_regex_replace, line), end='')
