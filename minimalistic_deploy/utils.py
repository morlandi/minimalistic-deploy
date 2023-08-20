#!/usr/bin/env python3
import json
import logging

# import subprocess
# import argparse
# import copy
# import os
# import platform
# import inspect
# from dataclasses import dataclass, field, asdict
# from typing import List, Dict
# from collections import UserDict

logger = logging.getLogger("deploy")


def merge_dicts(d1, d2):
    """
    Merge two dictionaries;
    on case of keys collision, the second parameter overrides the first

    Example:
        merge_dicts({'a': 1, 'b': 2}, {'c': 3, 'a': 100})
        {'a': 100, 'b': 2, 'c': 3}
    """
    return {**d1, **d2}


def load_json_file(filename, fail_silently=False):
    if not filename.lower().endswith('.json'):
        filename += '.json'
    try:
        with open(filename, "rt") as f:
            data = json.load(f)
    except Exception as e:
        logger.error('JSONDecodeError in file "%s": %s' % (filename, str(e)))
        if not fail_silently:
            exit()
        data = {}
    return data
