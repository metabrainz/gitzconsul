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
import signal
import subprocess
import sys
from time import sleep


log = logging.getLogger('gitzconsul')

WORKING_BRANCH = 'gitzconsul'

RUNCMD_TIMEOUT = 120
RUNCMD_ATTEMPTS = 3
RUNCMD_RETRY_DELAY = 5


class GitError(Exception):
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


def git(*args, cwd=None):
    """subprocess.run() wrapper
        It returns decoded stdout by default
        It raises GitError if command exits with non-zero exit code,
        with stderr output as message.
    """
    cmd = ['git']
    if cwd:
        cmd.extend(['-C', str(cwd)])
    cmd.extend(args)
    exec_env = os.environ.copy()
    # set LC_ALL to force messages in English
    exec_env['LC_ALL'] = 'C'

    attempts = RUNCMD_ATTEMPTS
    while attempts > 0:
        try:
            result = _run(
                *cmd,
                env=exec_env,
                timeout=RUNCMD_TIMEOUT  # safer, in case a command is stuck
            )
            log.debug("cmd: %s -> %d", " ".join(cmd), result.returncode)

            stdout = result.stdout.decode('utf-8').strip()
            if stdout:
                log.debug("stdout: %s", stdout)
            return stdout
        except subprocess.CalledProcessError as exc:
            # command failed
            log.debug('git exit code: %d', exc.returncode)
            log.debug('stdout: %r', exc.stdout)
            log.debug('stderr: %r', exc.stderr)
            raise GitError(exc.stderr.decode('utf-8').strip(), cmd, returncode=exc.returncode) from exc
        except subprocess.TimeoutExpired as exc:
            attempts -= 1
            if attempts:
                log.warning(
                    "Sleeping %0.1f seconds, remaining attempts: %d,"
                    " cmd timeout: %s", RUNCMD_RETRY_DELAY, attempts, exc
                )
                sleep(RUNCMD_RETRY_DELAY)
            else:
                raise GitError(exc, cmd) from exc


def _run(*args, timeout=None, env=None):
    """subprocess.Popen() wrapper"""
    encoded_args = [a.encode('utf-8') for a in args] if sys.platform != 'win32' else args
    with subprocess.Popen(encoded_args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=os.setsid) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except Exception:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            process.kill()
            process.wait()
            raise
        retcode = process.poll()
        if retcode:
            raise subprocess.CalledProcessError(retcode, process.args, output=stdout, stderr=stderr)
        return subprocess.CompletedProcess(process.args, retcode, stdout, stderr)



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
        git('ls-remote', git_remote, git_ref)
        log.info("Remote repository: %s ref=%s", git_remote, git_ref)

        # clone if needed
        if not is_a_git_repository(path):
            log.info("Cloning repo...")
            git('clone', git_remote, str(path))

        # create our own branch, and set it to proper ref
        git('checkout', '-B', WORKING_BRANCH, git_ref, cwd=path)

        log.info("Local commit id: %s", get_local_commit_id(path))
        return True
    except GitError as exc:
        log.error("Failed to init repo path=%s remote=%s ref=%s exc=%s",
                  path, git_remote, git_ref, exc)
        return False


def get_local_commit_id(path):
    """Get current commit id from local directory"""
    return git('rev-parse', WORKING_BRANCH, cwd=path)


def get_remote_commit_id(path, git_ref):
    """Get last commit id from git remote repository"""
    output = git('ls-remote', '--exit-code', 'origin', git_ref, cwd=path)
    return output.split()[0]


def is_a_git_repository(path):
    """Check if path is a git repo, returns True if it is"""
    try:
        path = Path(path).resolve()
        output = git('rev-parse', '--git-dir', cwd=path)
        gitpath = Path(path).joinpath(output).resolve().parent
        return path == gitpath
    except GitError:
        pass
    return False


class SyncWithRemoteError(Exception):
    """Raised whenever sync_with_remote() fails"""


def sync_with_remote(path, git_ref):
    """Sync local directory with remote repository"""
    try:
        local_commit_id = get_local_commit_id(path)
        remote_commit_id = get_remote_commit_id(path, git_ref)
    except GitError as exc:
        raise SyncWithRemoteError(
            f"Couldn't read local or remote commit ids: {exc}"
        ) from exc

    if local_commit_id != remote_commit_id:
        log.debug(
            "Resync needed: local %s != remote %s",
            local_commit_id, remote_commit_id
        )

        try:
            git('fetch', 'origin', git_ref, cwd=path)
            git('reset', '--hard', 'FETCH_HEAD', cwd=path)
            commit_id = get_local_commit_id(path)
        except GitError as exc:
            raise SyncWithRemoteError(
                f"Couldn't fetch from remote: {exc}"
            ) from exc

        log.info("Synced to commit id: %s", commit_id)
