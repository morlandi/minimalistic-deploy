#!/usr/bin/env python3
import argparse
import logging
import subprocess
import traceback
import jinja2


class SSHClient():

    def __init__(self, host, ssh_user='', ssh_options='', rsync_options='', verbose=False, dry_run=False, timeout=0, colorize=True,
        logger=None, render_context={}):
        self.host = host
        self.ssh_user = ssh_user
        self.ssh_options = ssh_options
        self.rsync_options = rsync_options
        self.timeout = timeout
        self.verbose = verbose
        self.dry_run = dry_run
        self.colorize = colorize
        self.logger = logger
        self.render_context = render_context

    def exec_command(self, command, become=False, become_user='', wrap_bash=True):

        # Given command may be either a string, or a list of strings
        # in the latter case, we join string with '&&' bash operator
        if type(command) == list:
            inner_command = ' && '.join(command)
        else:
            inner_command = command

        if wrap_bash:
            inner_command = "/bin/bash -c \"cd && %s\"" % inner_command

        # sudo when required
        if become:
            prefix = "sudo -H --non-interactive "
            if become_user:
                prefix += "-u %s " % become_user
            inner_command = prefix + inner_command

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

        inner_command = inner_command.replace('"', '\\"')
        #self._print_message(inner_command)

        # We finally build the whole SSH statement

        remote_command = 'ssh '
        if self.ssh_options:
            remote_command += self.ssh_options + ' '
        if self.timeout:
            remote_command += '-o ConnectTimeout=%d ' % self.timeout
        # if self.ssh_user:
        #     remote_command += self.ssh_user + "@"
        # remote_command += self.host
        remote_command += self._remote_address()

        remote_command += " \"%s\"" % inner_command
        #self._print_message(remote_command)

        result = self._run_remote_command(remote_command)
        return result

    def exec_rsync(self, source, destination, become=False, become_user='', ignore_existing=False, mode='', owner='', group=''):
        """

        """
        remote_command = 'rsync -avz --progress '
        if self.timeout:
            remote_command +=  '--timeout=%d ' % self.timeout
        if ignore_existing:
            remote_command += '--ignore-existing '

        if mode:
            remote_command += f'--chmod="{mode}" '

        chown = f'{owner}:{group}'
        if len(chown) > 1:
            remote_command += f'--chown="{chown}" '

        if become:
            remote_command += '--rsync-path="sudo -u %s rsync" ' % (become_user or "root")

        if self.rsync_options:
            remote_command += self.rsync_options + ' '

        remote_command += f'"{source}" '
        remote_command += f'"{self._remote_address()}:{destination}" '

        result = self._run_remote_command(remote_command)

        return result

    def _run_remote_command(self, remote_command):

        remote_command = self.render_string(remote_command)

        self._log(logging.DEBUG, remote_command)
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
                self._print_message(result)
            except subprocess.CalledProcessError as e:
                if self.verbose:
                    print('ERROR ....................: ' + e.output)
                raise

            # result = subprocess.check_output(
            #     remote_command,
            #     shell=True,
            #     stderr=subprocess.STDOUT,
            #     encoding='utf-8',
            # )

        self._log(logging.DEBUG, result)
        # if action.register:
        #     self.results[action.register] = result
        return result

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

        if not self.render_context:
            return string

        return recursive_render(string, self.render_context)

    def _remote_address(self):
        text = ''
        if self.ssh_user:
            text += self.ssh_user + "@"
        text += self.host
        return text

    def _log(self, level, message):
        self._print_message(message)
        if self.logger:
            self.logger.log(level, message)

    def _print_message(self, line):
        if self.verbose:
            if self.colorize:
                from rich.console import Console
                console = Console()
                console.print(line, style="yellow")
            else:
                print(line)


if __name__ == '__main__':
    """
    Examples:

    python ./ssh_client.py anvera.edms.brainstorm.it --commands whoami "ls /" pwd --become --become-user master --ssh-user master  --verbose
    """
    parser = argparse.ArgumentParser(description="Run remote command via SSH")
    parser.add_argument("host")
    parser.add_argument("--commands", nargs="+", help="list of commands to execute remotely; if not provided, use rsync instead")
    parser.add_argument("--ssh-user", type=str, default="")
    parser.add_argument("--ssh-options", type=str, default="")
    parser.add_argument("--become", action="store_true")
    parser.add_argument("--become-user", type=str, default="")
    parser.add_argument("--timeout", type=int, default=0)
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--dry-run", "-d", action="store_true")
    parser.add_argument("--no-wrap-bash", action="store_true")
    parser.add_argument("--no-colors", action="store_true")
    parser.add_argument("--source", help="rync source")
    parser.add_argument("--destination", help="rsync destination")
    parser.add_argument("--ignore-existing", action="store_true", help="rsync to skip existing files")
    parser.add_argument("--rsync-options", type=str, default="")
    parser.add_argument(
        "--traceback", action="store_true", help="Print errors traceback"
    )
    args = parser.parse_args()
    #print(args)

    try:

        client = SSHClient(
            host=args.host,
            ssh_user=args.ssh_user,
            ssh_options=args.ssh_options,
            rsync_options=args.rsync_options,
            verbose=args.verbose,
            dry_run=args.dry_run,
            timeout=args.timeout,
            colorize=not args.no_colors,
        )

        if args.commands:
            client.exec_command(
                command=args.commands,
                become=args.become,
                become_user=args.become_user,
                wrap_bash=not args.no_wrap_bash,
            )
        else:
            if not args.source:
                print("source is required")
            if not args.destination:
                print("destination is required")
            if args.source and args.destination:
                client.exec_rsync(source=args.source, destination=args.destination,
                    become=args.become, become_user=args.become_user, ignore_existing=args.ignore_existing)


    except Exception as e:
        print('ERROR: ' + str(e))
        if args.traceback:
            print(traceback.format_exc())
