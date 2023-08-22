#!/usr/bin/env python3
import argparse
import copy
import json
import logging
import os
import traceback

from .host import Host, Context
from .action import Action
from .utils import merge_dicts, load_json_file

try:
    import rich
except ModuleNotFoundError:
    rich = None


logger = logging.getLogger("deploy")


def load_vars(filename):
    return load_json_file(filename)


def load_hosts(filename, hosts, vars, files_foldername):
    # with open("hosts.json", "rt") as f:
    #     data = {k: v for k, v in json.load(f).items() if not v.get("disabled", False)}
    data = load_json_file(filename, fail_silently=True if hosts is None else False)
    data = {k: v for k, v in data.items() if not v.get("disabled", False)}

    if hosts is None:
        # Return only keys
        return data.keys()

    if "*" in hosts:
        selected_hosts = data
    else:
        for h in hosts:
            if h not in data.keys():
                print('Available hosts: ' + ','.join(data.keys()))
                raise Exception('Unknown host "%s"' % h)
        selected_hosts = {k: v for k, v in data.items() if k in hosts}

    hosts = []
    for k, v in selected_hosts.items():

        # Remove unexpected parameters
        v.pop('disabled', None)

        # Prepare Context merging "hosts vars" and global "default" vars
        host_vars = v.pop('vars', {})
        context = merge_dicts(vars, host_vars)

        params = merge_dicts({'name': k, 'files_foldername': files_foldername, 'context': Context(**context)}, v)

        hosts.append(Host(**params))

    return hosts


def load_actions(filename, tags):
    def intersection(lst1, lst2):
        lst3 = [value for value in lst1 if value in lst2]
        return lst3

    # with open(filename + ".json", "rt") as f:
    #     data = [a for a in json.load(f) if not a.get("disabled", False)]
    if not filename.lower().endswith('.json'):
        filename += ".json"
    data = load_json_file(filename)
    data = [a for a in data if not a.get("disabled", False)]

    if not tags:
        selected_actions = data
    else:
        selected_actions = [d for d in data if intersection(tags, d.get("tags", []))]

    actions = []
    for a in selected_actions:
        #actions.append(Action.from_dict(a))
        a.pop('tags', None)

        actions.append(Action(**a))

    return actions


def work(args):
    vars = load_vars(args.vars_filename)
    hosts = load_hosts(args.hosts_filename, args.hosts, vars, args.files_foldername)
    actions = load_actions(args.actions_filename, args.tags)
    for action in actions:
        for host in hosts:
            if host.errors <= 0:
                try:
                    host.run_action(action, args.dry_run, args.extra_debug, rich and not args.no_colors, )
                except Exception as e:
                    host.errors += 1
                    logger.error(e)
                    if args.traceback:
                        logger.error(traceback.format_exc())


def verbosity_to_log_level(verbosity):
    levels = [logging.WARNING, logging.INFO, logging.DEBUG]
    log_level = levels[min(len(levels)-1, verbosity)]  # capped to number of levels
    return log_level


def main():
    parser = argparse.ArgumentParser(description="Simple deploy procedure. Required packages: Jinja2. Suggested packages: rich.")
    parser.add_argument("hosts", nargs="+", help='One or more deploy target')
    parser.add_argument("--tags", nargs="*", help="Optional tags for actions filtering")
    parser.add_argument("--actions-filename", "-a", default="deployment")
    parser.add_argument('-v', '--verbosity', type=int, choices=range(3), default=1, action='store', help="log verbosity level. Choose 0, 1 or 2. Default=1")
    parser.add_argument("--dry-run", "-d", action="store_true", help="simulate action")
    parser.add_argument("--extra-debug", "-x", action="store_true", help="Very verbose ouput")
    parser.add_argument("--no-colors", action="store_true", help="never use colors")
    parser.add_argument(
        "--traceback", action="store_true", help="Print errors traceback"
    )
    parser.add_argument("--hosts-filename", default="hosts.json", help='hosts filename; default: "hosts.json"')
    parser.add_argument("--vars-filename", default="vars.json", help='vars filename; default: "vars.json"')
    parser.add_argument("--files-foldername", default="files", help='files foldername; default: "files"')
    args = parser.parse_args()

    if args.extra_debug and args.verbosity < 2:
        args.verbosity = 2

    if rich and not args.no_colors:
        from rich.logging import RichHandler

        logging.basicConfig(
            format="%(message)s",
            level=verbosity_to_log_level(args.verbosity),
            datefmt="[%X]",
            handlers=[RichHandler()],
        )
    else:
        logging.basicConfig(
            format="%(asctime)s|%(name)-12s|%(levelname)-8s|%(message)s",
            level=verbosity_to_log_level(args.verbosity),
            datefmt="[%X]",
        )

    try:
        work(args)
    except Exception as e:
        logger.error(e)
        if args.traceback:
            logger.error(traceback.format_exc())

# if __name__ == "__main__":
#     main()
