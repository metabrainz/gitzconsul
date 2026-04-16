"""Test repo module"""

import subprocess
import tempfile
import unittest
from pathlib import Path

from gitzconsul.repo import (
    GitError,
    git,
    init_git_repo,
    is_a_git_repository,
    get_local_commit_id,
    get_remote_commit_id,
    sync_with_remote,
    SyncWithRemoteError,
    WORKING_BRANCH,
)


class TestGitError(unittest.TestCase):
    def test_str_with_returncode(self):
        err = GitError("something failed", ["git", "status"], returncode=128)
        s = str(err)
        self.assertIn("something failed", s)
        self.assertIn("git status", s)
        self.assertIn("128", s)

    def test_str_without_returncode(self):
        err = GitError("fail", ["git", "push"])
        s = str(err)
        self.assertIn("fail", s)
        self.assertNotIn("code:", s)


class TestGitCommand(unittest.TestCase):
    def test_git_simple_command(self):
        # git --version always works
        output = git("--version")
        self.assertIn("git version", output)

    def test_git_bad_command_raises(self):
        with self.assertRaises(GitError) as ctx:
            git("not-a-real-command")
        self.assertIsNotNone(ctx.exception.returncode)

    def test_git_with_cwd(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", d], capture_output=True, check=True)
            output = git("rev-parse", "--git-dir", cwd=d)
            self.assertEqual(output, ".git")


class TestIsAGitRepository(unittest.TestCase):
    def test_valid_repo(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", d], capture_output=True, check=True)
            self.assertTrue(is_a_git_repository(d))

    def test_not_a_repo(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(is_a_git_repository(d))

    def test_nonexistent_path(self):
        self.assertFalse(is_a_git_repository("/nonexistent/path"))


def _create_bare_repo_with_commit(path):
    """Create a bare repo with one commit, return its path."""
    bare = Path(path) / "bare.git"
    work = Path(path) / "work"
    subprocess.run(["git", "init", "--bare", "--initial-branch=main", str(bare)], capture_output=True, check=True)
    subprocess.run(["git", "clone", str(bare), str(work)], capture_output=True, check=True)
    subprocess.run(["git", "checkout", "-b", "main"], cwd=str(work), capture_output=True, check=True)
    (work / "file.txt").write_text("hello", encoding="utf8")
    subprocess.run(["git", "add", "."], cwd=str(work), capture_output=True, check=True)
    subprocess.run(
        ["git", "-c", "user.email=test@test", "-c", "user.name=test", "commit", "-m", "init"],
        cwd=str(work),
        capture_output=True,
        check=True,
    )
    subprocess.run(["git", "push", "origin", "main"], cwd=str(work), capture_output=True, check=True)
    return bare, work


class TestInitGitRepo(unittest.TestCase):
    def test_relative_path_fails(self):
        result = init_git_repo("relative/path", "http://example.com/repo.git", "refs/heads/main")
        self.assertFalse(result)

    def test_path_is_file_fails(self):
        with tempfile.NamedTemporaryFile() as f:
            result = init_git_repo(f.name, "http://example.com/repo.git", "refs/heads/main")
            self.assertFalse(result)

    def test_clone_from_local_bare(self):
        with tempfile.TemporaryDirectory() as d:
            bare, _ = _create_bare_repo_with_commit(d)
            target = Path(d) / "clone"
            result = init_git_repo(str(target), str(bare), "refs/heads/main")
            self.assertTrue(result)
            self.assertTrue(is_a_git_repository(target))

    def test_bad_remote_fails(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "clone"
            result = init_git_repo(str(target), "/nonexistent/repo.git", "refs/heads/main")
            self.assertFalse(result)


class TestSyncWithRemote(unittest.TestCase):
    def test_no_changes_needed(self):
        with tempfile.TemporaryDirectory() as d:
            bare, _ = _create_bare_repo_with_commit(d)
            target = Path(d) / "clone"
            init_git_repo(str(target), str(bare), "refs/heads/main")
            # No new commits, should not raise
            sync_with_remote(target, "refs/heads/main")

    def test_syncs_new_commit(self):
        with tempfile.TemporaryDirectory() as d:
            bare, work = _create_bare_repo_with_commit(d)
            target = Path(d) / "clone"
            init_git_repo(str(target), str(bare), "refs/heads/main")
            old_id = get_local_commit_id(target)

            # Push a new commit via work dir
            (work / "file2.txt").write_text("new", encoding="utf8")
            subprocess.run(["git", "add", "."], cwd=str(work), capture_output=True, check=True)
            subprocess.run(
                ["git", "-c", "user.email=test@test", "-c", "user.name=test", "commit", "-m", "second"],
                cwd=str(work),
                capture_output=True,
                check=True,
            )
            subprocess.run(["git", "push", "origin", "main"], cwd=str(work), capture_output=True, check=True)

            sync_with_remote(target, "refs/heads/main")
            new_id = get_local_commit_id(target)
            self.assertNotEqual(old_id, new_id)

    def test_bad_repo_raises(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SyncWithRemoteError):
                sync_with_remote(Path(d), "refs/heads/main")
