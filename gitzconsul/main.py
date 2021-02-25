"""gitzconsul command-line"""
#  gitzconsul is a bridge between git repositories and consul kv
#
#    It is a stripped-down Python re-implementation of git2consul
#
#    Copyright (C) 2021 Laurent Monin
#    Copyright (C) 2021 MetaBrainz Foundation
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.

import logging
import traceback
from pathlib import Path
import subprocess
import sys
from time import sleep

import click


from gitzconsul import Context
from gitzconsul.sync import SyncKV
from gitzconsul.consultxn import ConsulConnection


log = logging.getLogger('gitzconsul')


# pylint: disable=unused-argument
def loglevelfmt(ctx, param, value):
    """use to convert lowercased level passed as option to uppercase"""
    if value is not None:
        return value.upper()
    return None


POSSIBLE_LEVELS = (
    'CRITICAL',
    'ERROR',
    'WARNING',
    'INFO',
    'DEBUG',
)

WORKING_BRANCH = 'gitzconsul'


class RunCmdError(Exception):
    """Raises whenever rumcmd() returned with non-zero exit code"""


def runcmd(args, cwd=None, exit_code=False, timeout=120):
    """subprocess.run() wrapper
        It returns decoded stdout by default
        It raises RunCmdError if command exits with non-zero exit code, with stderr output as message
        If exit_code is True, it just returns command exit code
    """
    result = subprocess.run(
        args,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout  # safer, in case a command is stuck
    )
    if exit_code:
        return result.returncode
    if result.returncode:
        raise RunCmdError(result.stderr.decode('utf-8').strip())

    return result.stdout.decode('utf-8').strip()


def init_git_repo(target_dir, git_remote, git_ref):
    """Initialize local directory with remote git repository"""
    # check if local repo exists
    path = Path(target_dir)
    if not path.is_absolute():
        log.error("%s isn't an absolute path", path)
        return False
    try:
        path.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        if not path.is_dir():
            log.error("%s isn't a directory", path)
            return False
    else:
        log.info("%s directory was created", path)

    log.info("Target directory: %s", path)

    try:
        runcmd(['git', 'ls-remote', git_remote, git_ref])
        log.info("Remote repository: %s ref=%s", git_remote, git_ref)

        # clone if needed
        if not is_a_git_repository(path):
            log.info("Cloning repo...")
            runcmd(['git', 'clone', git_remote, path], cwd=path)

        # create our own branch, and set it to proper ref
        runcmd(['git', 'checkout', '-B', WORKING_BRANCH, git_ref], cwd=path)

        log.info("Local commit id: %s", get_local_commit_id(path))
        return True
    except RunCmdError as exc:
        log.error("Failed to init repo path=%s remote=%s ref=%s: %s",
                  path, git_remote, git_ref, exc)
        return False


def get_local_commit_id(path):
    """Get current commit id from local directory"""
    return runcmd(['git', 'rev-parse', WORKING_BRANCH], cwd=path)


def get_remote_commit_id(path, git_ref):
    """Get last commit id from git remote repository"""
    return runcmd(['git', 'ls-remote', '--exit-code', 'origin', git_ref], cwd=path).split()[0]


def is_a_git_repository(path):
    """Check if path is a git repo, returns True if it is"""
    return runcmd(['git', 'rev-parse', '-is-inside-work-tree'], cwd=path, exit_code=True) == 0


class SyncWithRemoteError(Exception):
    """Raised whenever sync_with_remote() fails"""


def sync_with_remote(path, git_ref):
    """Sync local directory with remote repository"""
    try:
        local_commit_id = get_local_commit_id(path)
        remote_commit_id = get_remote_commit_id(path, git_ref)
    except RunCmdError as exc:
        raise SyncWithRemoteError("Couldn't read local or remote commit ids: %s" % exc) from exc

    if local_commit_id != remote_commit_id:
        log.info(
            "Resync needed: local %s != remote %s", local_commit_id, remote_commit_id)

        try:
            runcmd(['git', 'fetch', 'origin', git_ref], cwd=path)
            runcmd(['git', 'reset', '--hard', 'FETCH_HEAD'], cwd=path)
            commit_id = get_local_commit_id(path)
        except RunCmdError as exc:
            raise SyncWithRemoteError("Couldn't fetch from remote: %s" % exc) from exc

        log.info("Synced to commit id: %s", commit_id)


@click.command()
@click.option(
    '-r',
    '--root',
    help='root directory, relative to directory',
    default="",
    show_default=True
)
@click.option(
    '-d',
    '--directory',
    help='directory, must be absolute path',
    required=True
)
@click.option(
    '-g',
    '--git-url',
    help='git repository remote url',
    default=None
)
@click.option(
    '-R',
    '--git-ref',
    help='git repository remote ref',
    default='refs/heads/master',
    show_default=True
)
@click.option(
    '-k',
    '--consul-key',
    help='add keys under this key',
    required=True
)
@click.option(
    '-u',
    '--consul-url',
    help='consul url',
    default='http://localhost:8500',
    show_default=True
)
@click.option(
    '-i',
    '--interval',
    help='interval in seconds between syncs',
    default=15,
    show_default=True
)
@click.option(
    '-a',
    '--consul-datacenter',
    help='consul datacenter',
    default=None,
)
@click.option(
    '-t',
    '--consul-token',
    help='consul token',
    default=None,
)
@click.option(
    '-T',
    '--consul-token-file',
    help='path to file containing consul token',
    default=None,
)
@click.option(
    '-f',
    '--logfile',
    help="log file path",
    default=None
)
@click.option(
    '-l',
    '--loglevel',
    help="log level",
    default="INFO",
    show_default=True,
    type=click.Choice(POSSIBLE_LEVELS, case_sensitive=False),
    callback=loglevelfmt
)
@click.option(
    '-G',
    '--debug',
    help='output extra debug info',
    is_flag=True
)
def main(**options):
    """Register kv values into consul based on git repository content"""
    context = Context(options)
    interval = context.options['interval']

    log.info("Options: %r", context.options)
    repo_path = None
    git_ref = context.options['git_ref']
    git_url = context.options['git_url']
    repo_path = Path(context.options['directory']).resolve()
    log.info("Directory: %s", repo_path)
    if git_url:
        if not init_git_repo(repo_path, git_url, git_ref):
            sys.exit(1)
    else:
        # no remote repository
        if not repo_path.is_dir():
            log.error("%s isn't a directory", repo_path)
            sys.exit(1)

    root_directory = Path(context.options['root'])
    if root_directory.is_absolute():
        log.error("%s must be relative to %s", root_directory, repo_path)
        sys.exit(1)

    abs_root_directory = repo_path.joinpath(root_directory).resolve()
    if not abs_root_directory.is_dir():
        log.error("Not a directory: %s", abs_root_directory)
        sys.exit(1)
    while not context.kill_now:
        try:
            if git_url and is_a_git_repository(repo_path):
                log.info("Fetching from remote %s ref=%s repo=%s", git_url, git_ref, repo_path)
                sync_with_remote(repo_path, git_ref)
            consul_connection = ConsulConnection(
                context.options['consul_url'],
                data_center=context.options['consul_datacenter'],
                acl_token=context.options['consul_token'],
                acl_token_file=context.options['consul_token_file']
            )
            sync = SyncKV(abs_root_directory,
                          context.options['consul_key'], consul_connection)
            log.info(
                "Syncing consul @%s (%s) with %s",
                sync.consul_connection,
                sync.topkey,
                sync.root)
            sync.do()
        except Exception as exc:  # pylint: disable=broad-except
            log.error(exc)
            if context.options['debug']:
                log.debug(traceback.format_exc())
        finally:
            if not context.kill_now:
                log.debug("sleeping %d second(s)...", interval)
                for _unused in range(0, interval):
                    if not context.kill_now:
                        sleep(1)


if __name__ == "__main__":
    main()
