#!/usr/bin/env python3.6
import argparse
import fileinput
from shutil import copyfile
import re
import os


if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-p', '--features_history_period',
        dest='period',
        help="",
        default="7d",
        required=True)
    parser.add_argument(
        '-o', '--output',
        dest='output',
        help="Name output file",
        default="prometheus_rule_score.yaml")

    args = parser.parse_args()
    config_name = args.output
    period = args.period
    assert re.match(r'\d+\w', period)

    # Prepare regex
    period_regex_search = r'\[7d'  # r'\[\d+\w\]'
    period_regex_replace = '[{}'.format(period)

    # Copy template
    copyfile(os.path.dirname(os.path.abspath(__file__)) +
             '/../monitoring/prometheus/prometheus_rule.score.yaml',
             config_name)

    # Replace
    with fileinput.FileInput(config_name, inplace=True) as file:
        for line in file:
            print(re.sub(period_regex_search, period_regex_replace, line), end='')

    # Print information
    print("Created Prometheus Rules with period {} in file {}.".format(period, config_name))
