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
from pathlib import Path
import subprocess


log = logging.getLogger('gitzconsul')

WORKING_BRANCH = 'gitzconsul'


class RunCmdError(Exception):
    """Raises whenever rumcmd() returned with non-zero exit code"""


def runcmd(args, cwd=None, exit_code=False, timeout=120):
    """subprocess.run() wrapper
        It returns decoded stdout by default
        It raises RunCmdError if command exits with non-zero exit code,
        with stderr output as message.
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
