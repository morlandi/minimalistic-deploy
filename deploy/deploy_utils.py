#!/usr/bin/env python3
import subprocess
import argparse
import copy
import logging
import os
import platform
import jinja2
import json
import inspect
from dataclasses import dataclass, field, asdict
from typing import List, Dict
from collections import UserDict

logger = logging.getLogger("deploy")
from ssh_client import SSHClient


def merge_dicts(d1, d2):
    """
    Merge two dictionaries;
    on case of keys collision, the second parameter overrides the first

    Example:
        merge_dicts({'a': 1, 'b': 2}, {'c': 3, 'a': 100})
        {'a': 100, 'b': 2, 'c': 3}
    """
    return {**d1, **d2}


class UserDictJsonEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, UserDict):
            return obj.data
        return json.JSONEncoder.default(self, obj)



@dataclass
class Action:
    title: str = ''
    type: str = ''
    become: bool = False
    become_user: str = ''
    timeout: int = 0
    wrap_bash: bool = True
    when: str = ''
    register: str = ''
    items: List[str] = field(default_factory=list)
    extra: Dict = field(default_factory = lambda: ({}))

    # The following works but is not required any more
    # @classmethod
    # def from_dict(cls, env):      
    #     """
    #     Build the dataclass collecting all nexpected params, if any, in a separate  "extra" dict.
    #     Adapted from: [How does one ignore extra arguments passed to a dataclass?](https://stackoverflow.com/questions/54678337/how-does-one-ignore-extra-arguments-passed-to-a-dataclass)
    #     """
    #     cls_parameters = inspect.signature(cls).parameters
    #     extra = {
    #         k: v for k, v in env.items() 
    #         if k not in cls_parameters
    #     }
    #     kwargs = {
    #         k: v for k, v in env.items() 
    #         if k in cls_parameters
    #     }
    #     return cls(**kwargs, extra=extra)

    def __str__(self):
        return str(self.title)

    def __repr__(self):
        return "Action<%s>" % json.dumps(asdict(self), indent=4)


class Context(UserDict):

    def __str__(self):
        return self.__repr__()

    def __repr__(self):
        return "Context<%s>" % json.dumps(self.data, indent=4)


@dataclass
class Host():
    name: str
    address: str
    context: Context
    ssh_user: str = ''
    errors: int = 0
    results: Dict = field(default_factory = lambda: ({}))

    def __str__(self):
        return self.name

    def __repr__(self):
        return "Host<%s>" % json.dumps(asdict(self), indent=4, cls=UserDictJsonEncoder)

    def run_action(self, action, dry_run, extra_debug, colorize):

        self.dry_run = dry_run
        self.extra_debug = extra_debug
        self.colorize = colorize

        logger.info("=" * 80)
        logger.info('--> "%s": %s ...' % (self, action))
        logger.debug("-" * 80)
        if self.extra_debug:
            logger.debug(repr(self))
            logger.debug(repr(action))

        # If when expression has been provided, evaluate it
        skip = False
        if action.when:
            expression = action.when
            result = self.evaluate_expression(expression, action)
            if not result:
                skip = True

        if skip:
            self.log_message(["skipped", ])
        else:

            if action.type == "command":
                for item in action.items:
                    if not item.startswith('#'):
                        self.run_ssh(
                            action,
                            item,
                            silent=False
                        )

            elif action.type == "mkdirs":
                self.execute_mkdirs(
                    action,
                )

            elif action.type == "message":
                self.log_message(action.items)

            elif action.type == "stat_dir":
                self.execute_stat(
                    action,
                    True
                )

            elif action.type == "stat_file":
                self.execute_stat(
                    action,
                    False
                )

            elif action.type == "copy":
                self.execute_copy(
                    action,
                )

        #     # elif action == 'template':
        #     #     templates = item.get('templates', [])
        #     #     for template in templates:
        #     #         run_remote_template(template.get('src', ''), template.get('dest', ''),
        #     #             item.get('owner', ''), item.get('group', ''), item.get('mode', ''),
        #     #             item.get('become', False), item.get('become_user', ''))

            else:
                raise Exception('Unknown action type "%s"' % action.type)


    def render_string(self, string):

        # Jinja nested rendering on variable content
        # https://stackoverflow.com/questions/8862731/jinja-nested-rendering-on-variable-content#34002296
        def recursive_render(tpl, values):
             prev = tpl
             while True:
                 curr = jinja2.Template(prev, undefined=jinja2.StrictUndefined).render(**values)
                 if curr != prev:
                     prev = curr
                 else:
                     return curr

        # environment = jinja2.Environment()
        # template = environment.from_string(string)
        #return template.render(**asdict(self.context))
        #return template.render(**(self.context))
        return recursive_render(string, self.context.data)

    def print_message(self, line):
        if self.colorize:
            from rich.console import Console
            console = Console()
            console.print(line, style="yellow")
        else:
            print(line)

    def evaluate_expression(self, expression, action=None):
        """
        - if expression is "results['key']"", return result of eval(self.results['key'] ...)
        - if expression is "eval('whatever')", applies eval() to 'whatever' and returns result
        - if expression starts with:
            - 'exists_dir('
            - 'not_exists_dir('
            - 'exists_file('
            - 'not_exists_file('
          check if remote path exists and return result accordingly

        - otherwise, return 'expression' as is

        Sample usage from Action:

            {
                "title": "Show target",
                "type": "message",
                "items": [
                    "aaa",
                    "results['target_version']",
                    "eval(1 + 2)"
                ],
                "tags": ["testme"]
            },
        """
        text = self.render_string(expression)

        brace_opener = text.find('(') + 1
        brace_closer = text.find(')')
        inner_text = text[brace_opener:brace_closer]

        if text.startswith('results['):
            result = eval("self." + text)
        elif text.startswith("eval("):
            result = eval(inner_text)
        elif text.startswith('not_exists_dir('):
            result = not self.check_remote_path_exists(eval(inner_text), True, action)
        elif text.startswith('exists_dir('):
            result = self.check_remote_path_exists(eval(inner_text), True, action)
        elif text.startswith('not_exists_file('):
            result = not self.check_remote_path_exists(eval(inner_text), False, action)
        elif text.startswith('exists_file('):
            result = self.check_remote_path_exists(eval(inner_text), False, action)
        else:
            result = text

        return result

    def log_message(self, lines):
        for line in lines:
            text = str(self.evaluate_expression(line)).strip()
            if self.colorize:
                from rich.text import Text
                message = Text('[yellow]' + text + '[/yellow]')
                logger.info(message, extra={"markup": True})
            else:
                logger.info(text)

    def execute_mkdirs(self, action):

        command = "mkdir -p " 
        if "mode" in action.extra:
            command += "-m %s " % action.extra["mode"]
        command += self.render_string(' '.join(action.items))
        self.run_ssh(action, command, silent=False)

    def check_required_action_params(self, action, params):
        for p in params:
            if not getattr(action, p):
                raise Exception('Missing attribute "%s"' % p)

    def check_required_action_extra_params(self, action, params):
        for p in params:
            if not p in action.extra:
                raise Exception('Missing attribute extra["%s"]' % p)

    def check_remote_path_exists(self, path, dir, action):
        if self.dry_run:
            return False
        command  = 'test -%s "%s"' % (('d' if dir else 'e'), path, )
        result = False
        try:
            # check existence
            fake_action = Action(become=action.become, become_user=action.become_user, wrap_bash=True)
            self.run_ssh(fake_action, command, silent=True)
            result = True
        except subprocess.CalledProcessError as e:
            # Does not exists
            result = False

        logger.info('%s "%s" was %sfound' % (
            "dir" if dir else "file",
            path,
            "" if result else "not ",
        ))

        return result

    def execute_stat(self, action, dir):
        """
        Sample usage:

            {
                "title": "Collect file stats",
                "type": "stat_file",
                "become": true,
                "register": "result1",
                "extra": {
                    "path": "/home/{{username}}/logs/access.log"
                }
            },
            {
                "title": "message yes",
                "type": "message",
                "items": [
                    "file exists"
                ],
                "when": "eval(self.results['result1']['exists'])"
            },
            {
                "title": "message no",
                "type": "message",
                "items": [
                    "file DOES NOT exists"
                ],
                "when": "eval(not self.results['result1']['exists'])"
            },
        """
        self.check_required_action_params(action, ["register", ])
        self.check_required_action_extra_params(action, ["path", ])
        action.wrap_bash = False

        command  = 'test -%s "%s"' % (('d' if dir else 'e'), action.extra["path"], )
        result = {'exists': True}
        try:
            # check existence
            self.run_ssh(action, command, silent=True)

            format = '|'.join([c+':%'+c for c in 'aAFgGinNsuUXYZ'])
            command = 'stat --format="%s" "%s"' % (format, action.extra["path"])
            response = self.run_ssh(action, command, silent=False)
            parsed_response = {t.split(':')[0]: t.split(':')[1].strip() for t in response.split('|')}
            # Example:
            #{
            #  'a': '755',                      access rights in octal (note '#' and '0' printf flags)
            #  'A': 'drwxr-xr-x',               access rights in human readable form
            #  'F': 'directory',                file type
            #  'g': '1003',                     group ID of owner
            #  'G': 'ecolwaste',                group name of owner
            #  'i': '683581',                   inode number
            #  'n': '/home/ecolwaste/logs',     file name
            #  'N': "'/home/ecolwaste/logs'",   quoted file name with dereference if symbolic link
            #  's': '4096',                     total size, in bytes
            #  'u': '1003',                     user ID of owner
            #  'U': 'ecolwaste',                user name of owner
            #  'X': '1688596627',               time of last access, seconds since Epoch
            #  'Y': '1688596626',               time of last data modification, seconds since Epoch
            #  'Z': '1688596626',               time of last status change, seconds since Epoch
            #}

            result = merge_dicts(result, parsed_response)

        except subprocess.CalledProcessError as e:
            # Does not exists
            result = {'exists': False}

        self.results[action.register] = result

    def execute_copy(self, action):

        self.check_required_action_extra_params(action, ["destination", ])

        destination = action.extra['destination']
        for item in action.items:

            source = "files/" + item
            if not os.path.isfile(source):
                raise Exception(f'File "{source}" not found')

            self.run_rsync(action, source, destination, silent=False)

    def run_rsync(self, action, source, destination, silent):
        client = SSHClient(
            host=self.address,
            ssh_user=self.ssh_user,
            ssh_options='',
            rsync_options='',
            verbose=not silent,
            dry_run=self.dry_run,
            timeout=action.timeout,
            colorize=self.colorize,
            logger=logger,
            render_context=self.context.data,
        )

        result = client.exec_rsync(
            source=source,
            destination=destination,
            become=action.become,
            become_user=action.become_user,
            ignore_existing=not action.extra.get('force', False),
            mode=action.extra.get('mode', ''),
            owner=action.extra.get('owner', ''),
            group=action.extra.get('group', ''),
        )

        if action.register:
            self.results[action.register] = result
        return result


    def run_rsync_bak(self, action, source, destination, silent):
        """

        """

        def remote_host(action):
            text = ''
            if self.ssh_user:
                text += self.ssh_user + "@"
            text += self.address
            return text

        remote_command = 'rsync -avz --progress '
        if action.timeout:
            remote_command +=  '--timeout=%d ' % action.timeout
        if not action.extra.get('force', False):
            remote_command += '--ignore-existing '

        mode = action.extra.get('mode', '')
        if mode:
            remote_command += f'--chmod="{mode}" '

        owner = action.extra.get('owner', '')
        group = action.extra.get('group', '')
        chown = f'{owner}:{group}'
        if len(chown) > 1:
            remote_command += f'--chown="{chown}" '

        if action.become:
            remote_command += '--rsync-path="sudo -u %s rsync" ' % (action.become_user or "root")
        remote_command += f'"{source}" '
        remote_command += f'"{remote_host(action)}:{destination}" '

        result = self._run_remote_command_bak(action, remote_command, silent)

        return result

    def run_ssh(self, action, command, silent):
        """
        Prepare command for remote execution and run_ssh it
        Example:
            ssh -o ConnectTimeout=5 master@192.168.98.18 "sudo -H --non-interactive ls /home"
        """

        client = SSHClient(
            host=self.address,
            ssh_user=self.ssh_user,
            ssh_options='',
            rsync_options='',
            verbose=not silent,
            dry_run=self.dry_run,
            timeout=action.timeout,
            colorize=self.colorize,
            logger=logger,
            render_context=self.context.data,
        )

        result = client.exec_command(
            command,
            become=action.become,
            become_user=action.become_user,
            wrap_bash=action.wrap_bash,
        )

        if action.register:
            self.results[action.register] = result
        return result

    def run_ssh_bak(self, action, command, silent):
        """
        Prepare command for remote execution and run_ssh it
        Example:
            ssh -o ConnectTimeout=5 master@192.168.98.18 "sudo -H --non-interactive ls /home" 
        """
        wrapped_command = ""
        if action.become:
            wrapped_command += "sudo -H --non-interactive "
            if action.become_user:
                wrapped_command += "-u %s " % action.become_user
            #wrapped_command += "/bin/bash -c \"cd && "
        #wrapped_command += command + "\""
        if action.wrap_bash:
            wrapped_command += "/bin/bash -c \"cd && "

        wrapped_command += command

        if action.wrap_bash:
            wrapped_command += "\""

        #
        # "Escaping single quotes in shell for postgresql"
        # https://stackoverflow.com/questions/24095203/escaping-single-quotes-in-shell-for-postgresql
        #
        # > What I usually do is use double quotes (") for postgres -c's argument
        #   and escaped double quotes (\") for psql -c's argument.
        #   That way, I can use single quotes (') inside the SQL string with no problem:
        #
        #         su postgres -c "psql -c \"SELECT 'hi'  \" "
        #

        wrapped_command = wrapped_command.replace('"', '\\"')

        #remote_command = 'ssh -o ConnectTimeout=5 '
        remote_command = 'ssh '
        if action.timeout:
            remote_command += '-o ConnectTimeout=%d ' % action.timeout
        if self.ssh_user:
            remote_command += self.ssh_user + "@"
        remote_command += self.address
        remote_command += " \"%s\"" % wrapped_command

        result = self._run_remote_command_bak(action, remote_command, silent)
        return result

    def _run_remote_command_bak(self, action, remote_command, silent):

        remote_command = self.render_string(remote_command)
        
        logger.debug(remote_command)
        result = ''
        if not self.dry_run:

            # rc = os.system(remote_command)
            # if rc != 0:
            #     raise Exception("Previous command failed with error code: %d" % rc)
            
            try:
                result = subprocess.check_output(
                    remote_command,
                    shell=True,
                    stderr=subprocess.STDOUT,
                    encoding='utf-8',
                )
                if not silent:
                    self.print_message(result)
            except subprocess.CalledProcessError as e:
                if not silent:
                    print('ERROR ....................: ' + e.output)
                raise

            # result = subprocess.check_output(
            #     remote_command,
            #     shell=True,
            #     stderr=subprocess.STDOUT,
            #     encoding='utf-8',
            # )

        logger.debug(result)
        if action.register:
            self.results[action.register] = result
        return result
