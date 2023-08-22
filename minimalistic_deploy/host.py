import logging
import subprocess
import os
from dataclasses import dataclass, field, asdict
from typing import List, Dict
from collections import UserDict
import jinja2
import json
from .ssh_client import SSHClient
from .action import Action
from .utils import merge_dicts

logger = logging.getLogger("deploy")


class Context(UserDict):

    def __str__(self):
        return self.__repr__()

    def __repr__(self):
        return "Context<%s>" % json.dumps(self.data, indent=4)


class UserDictJsonEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, UserDict):
            return obj.data
        return json.JSONEncoder.default(self, obj)


@dataclass
class Host():
    name: str
    address: str
    files_foldername: str
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
                chdir = action.extra.get('chdir', '')
                for item in action.items:
                    if not item.startswith('#'):
                        command = item
                        if chdir:
                            command = "cd %s && %s" % (chdir, command)
                        self.run_ssh(
                            action,
                            command,
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

            source = os.path.join(self.files_foldername, item)
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
            as_template=action.extra.get('template', False)
        )

        if action.register:
            self.results[action.register] = result
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
