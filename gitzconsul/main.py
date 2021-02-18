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


def runcmd(args, cwd=None):
    return subprocess.run(
        args,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120   # safer, in case a command is stuck
    )


def init_git_repo(target_dir, git_remote, git_ref):
    # check if local repo exists
    path = Path(target_dir)
    if not path.is_absolute():
        log.error("{} isn't an absolute path".format(path))
        return False
    try:
        path.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        if not path.is_dir():
            log.error("{} isn't a directory".format(path))
            return False
    else:
        log.info("{} directory was created".format(path))

    log.info("Target directory: {}".format(path))

    result = runcmd(['git', 'ls-remote', git_remote, git_ref])
    if result.returncode:
        log.error("Cannot find git remote repo: {} {}".format(git_remote,
                                                              git_ref))
        log.error(result.stderr)
        return False
    log.info("Remote repository: {} ref={}".format(git_remote, git_ref))

    # clone if needed
    result = runcmd(['git', 'rev-parse', git_ref], cwd=path)
    if result.returncode:
        log.info("Cloning repo...")
        result = runcmd(['git', 'clone', git_remote, path], cwd=path)
        if result.returncode:
            log.error("Failed to clone {}: {}".format(git_remote,
                                                      result.stderr))
            return False

    # create our own branch, and set it to proper ref
    result = runcmd(['git', 'checkout', '-B', 'gitzconsul', git_ref], cwd=path)
    if result.returncode:
        log.error("Failed to checkout {}: {}".format(git_ref, result.stderr))
        return False

    commit_id = get_local_commit_id(path)
    if not commit_id:
        return False
    log.info("Local commit id: {}".format(commit_id))

    return path


def get_local_commit_id(path):
    result = runcmd(['git', 'rev-parse', 'gitzconsul'], cwd=path)
    if result.returncode:
        log.error(result)
        return False

    return result.stdout.decode('utf-8').strip()


def get_remote_commit_id(path, git_ref):
    result = runcmd(['git', 'ls-remote', '--exit-code', 'origin', git_ref], cwd=path)
    if result.returncode:
        log.error(result)
        return False
    return result.stdout.decode('utf-8').strip().split()[0]


def sync_branch(path, git_ref):
    local_commit_id = get_local_commit_id(path)
    if not local_commit_id:
        return False

    remote_commit_id = get_remote_commit_id(path, git_ref)
    if not remote_commit_id:
        return False

    if local_commit_id != remote_commit_id:
        log.info("Resync needed: local {} != {} remote".format(
            local_commit_id, remote_commit_id))

        result = runcmd(['git', 'fetch', 'origin', git_ref], cwd=path)
        if result.returncode:
            log.error(result)
            return False

        result = runcmd(['git', 'reset', '--hard', 'FETCH_HEAD'], cwd=path)
        if result.returncode:
            log.error(result)
            return False

        commit_id = get_local_commit_id(path)
        if not commit_id:
            return False
        log.info("Synced to commit id: {}".format(commit_id))

    return False


@click.command()
@click.option(
    '-r',
    '--root-directory',
    help='root directory, relative to target directory',
    default=""
)
@click.option(
    '-o',
    '--target-directory',
    help='target directory, must be absolute path',
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
    default='refs/heads/master'
)
@click.option(
    '-n',
    '--name',
    help='top key name',
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
    '-d',
    '--delay',
    help='delay',
    default=15,
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
    help='consul token file',
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
    delay = context.options['delay']

    log.info("Options: %r" % context.options)
    repo_path = None
    git_ref = context.options['git_ref']
    git_url = context.options['git_url']
    if git_url:
        repo_path = init_git_repo(
            context.options['target_directory'],
            git_url,
            git_ref
        )
        if not repo_path:
            sys.exit(1)
    else:
        # no remote repository
        repo_path = Path(context.options['target_directory'])
        if not repo_path.is_dir():
            log.error("Target {} isn't a directory".format(repo_path))
            sys.exit(1)

    root_directory = Path(context.options['root_directory'])
    if root_directory.is_absolute():
        log.error("root directory must be relative to target directory")
        sys.exit(1)

    abs_root_directory = repo_path.joinpath(root_directory)
    while not context.kill_now:
        try:
            if repo_path:
                ret = sync_branch(repo_path, git_ref)
                if ret:
                    log.error("Git remote repo sync error")
            consul_connection = ConsulConnection(
                context.options['consul_url'],
                data_center=context.options['consul_datacenter'],
                acl_token=context.options['consul_token'],
                acl_token_file=context.options['consul_token_file']
            )
            sync = SyncKV(abs_root_directory,
                          context.options['name'], consul_connection)
            sync.do()
        except Exception as exc:  # pylint: disable=broad-except
            log.error(exc)
            log.error(traceback.format_exc())
        finally:
            if not context.kill_now:
                log.debug("sleeping %d second(s)...", delay)
                sleep(delay)


if __name__ == "__main__":
    main()
