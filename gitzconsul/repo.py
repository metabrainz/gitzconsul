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
import os
from pathlib import Path
import subprocess
from time import sleep


log = logging.getLogger('gitzconsul')

WORKING_BRANCH = 'gitzconsul'


class RunCmdError(Exception):
    """Raises whenever rumcmd() returned with non-zero exit code"""

    def __init__(self, message, cmd, returncode=None):
        self.message = message
        self.cmd = cmd
        self.returncode = returncode
        super().__init__(self.message)

    def __str__(self):
        msg = f"msg: {self.message}"
        cmdstr = " ".join(self.cmd)
        msg += f" cmd: {cmdstr}"
        if self.returncode is not None:
            msg += f" code: {self.returncode}"
        return msg


def runcmd(cmd, cwd=None, exit_code=False, timeout=120, attempts=3,
           delay=5):  # pylint: disable=too-many-arguments
    """subprocess.run() wrapper
        It returns decoded stdout by default
        It raises RunCmdError if command exits with non-zero exit code,
        with stderr output as message.
        If exit_code is True, it just returns command exit code
    """
    exec_env = os.environ.copy()
    # set LC_ALL to force messages in English
    exec_env['LC_ALL'] = 'C'

    while attempts > 0:
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                check=False,
                env=exec_env,
                timeout=timeout  # safer, in case a command is stuck
            )
            log.debug("cmd: %s -> %d", " ".join(cmd), result.returncode)
            if exit_code:
                return result.returncode

            stderr = result.stderr.decode('utf-8').strip()
            if stderr:
                log.debug("stderr: %s", stderr)
            if result.returncode:
                raise RunCmdError(stderr, cmd, returncode=result.returncode)

            stdout = result.stdout.decode('utf-8').strip()
            if stdout:
                log.debug("stdout: %s", stdout)
            return stdout
        except subprocess.TimeoutExpired as exc:
            attempts -= 1
            if attempts:
                log.warning(
                    "Sleeping %0.1f seconds, remaining attempts: %d,"
                    " cmd timeout: %s", delay, attempts, exc
                )
                sleep(delay)
            else:
                raise RunCmdError(exc, cmd) from exc


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
        cmd = ('git', 'ls-remote', git_remote, git_ref)
        runcmd(cmd)
        log.info("Remote repository: %s ref=%s", git_remote, git_ref)

        # clone if needed
        if not is_a_git_repository(path):
            log.info("Cloning repo...")
            cmd = ('git', 'clone', git_remote, str(path))
            runcmd(cmd)

        # create our own branch, and set it to proper ref
        cmd = ('git', 'checkout', '-B', WORKING_BRANCH, git_ref)
        runcmd(cmd, cwd=path)

        log.info("Local commit id: %s", get_local_commit_id(path))
        return True
    except RunCmdError as exc:
        log.error("Failed to init repo path=%s remote=%s ref=%s exc=%s",
                  path, git_remote, git_ref, exc)
        return False


def get_local_commit_id(path):
    """Get current commit id from local directory"""
    cmd = ('git', 'rev-parse', WORKING_BRANCH)
    return runcmd(cmd, cwd=path)


def get_remote_commit_id(path, git_ref):
    """Get last commit id from git remote repository"""
    cmd = ('git', 'ls-remote', '--exit-code', 'origin', git_ref)
    output = runcmd(cmd, cwd=path)
    return output.split()[0]


def is_a_git_repository(path):
    """Check if path is a git repo, returns True if it is"""
    try:
        path = Path(path).resolve()
        cmd = ('git', 'rev-parse', '--git-dir')
        output = runcmd(cmd, cwd=path)
        gitpath = Path(path).joinpath(output).resolve().parent
        return path == gitpath
    except RunCmdError:
        pass
    return False


class SyncWithRemoteError(Exception):
    """Raised whenever sync_with_remote() fails"""


def sync_with_remote(path, git_ref):
    """Sync local directory with remote repository"""
    try:
        local_commit_id = get_local_commit_id(path)
        remote_commit_id = get_remote_commit_id(path, git_ref)
    except RunCmdError as exc:
        raise SyncWithRemoteError(
            f"Couldn't read local or remote commit ids: {exc}"
        ) from exc

    if local_commit_id != remote_commit_id:
        log.debug(
            "Resync needed: local %s != remote %s",
            local_commit_id, remote_commit_id
        )

        try:
            cmd = ('git', 'fetch', 'origin', git_ref)
            runcmd(cmd, cwd=path)
            cmd = ('git', 'reset', '--hard', 'FETCH_HEAD')
            runcmd(cmd, cwd=path)
            commit_id = get_local_commit_id(path)
        except RunCmdError as exc:
            raise SyncWithRemoteError(
                f"Couldn't fetch from remote: {exc}"
            ) from exc

        log.info("Synced to commit id: %s", commit_id)
