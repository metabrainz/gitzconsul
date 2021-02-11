"""Test walk()"""

from functools import partial
from os import mkfifo
import tempfile
import unittest
from pathlib import Path

from gitzconsul.treewalk import walk


def write(content, path):
    """write contents to file at path"""
    path.open('w').write(content)


def touch(path):
    """create an empty file at path"""
    path.touch()


def symlink(target, path):
    """create a symlink from path to target"""
    path.symlink_to(target)


def fifo(path):
    """create a fifo at path"""
    mkfifo(path)


class TestWalk(unittest.TestCase):
    """Test of walk()"""

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def buildtree(self, root, tree):
        """helper to build a fs tree"""
        for path, content in tree.items():
            if isinstance(content, dict):
                subdir = root.joinpath(path)
                subdir.mkdir()
                self.buildtree(subdir, content)
            elif callable(content):
                content(root.joinpath(path))
            else:
                root.joinpath(path).open('w').write(content)

    def test_make_tree(self):
        """Test tree builder"""
        with tempfile.TemporaryDirectory() as tmpdirname:
            root = Path(tmpdirname)
            self.assertTrue(root.is_dir())

            tree = {
                'file1': touch,
                'subdir': {
                    'file2': partial(write, 'content2'),
                    'symlink1': partial(symlink, 'file2'),
                },
                'file3': '123',
            }
            self.buildtree(root, tree)

            file1path = root.joinpath('file1')
            self.assertTrue(file1path.is_file())
            file2path = root.joinpath('subdir').joinpath('file2')
            self.assertEqual(file2path.read_text(), 'content2')
            symlink1path = root.joinpath('subdir').joinpath('symlink1')
            self.assertTrue(symlink1path.is_symlink())
            self.assertEqual(symlink1path.read_text(), 'content2')
            file3path = root.joinpath('file3')
            self.assertEqual(file3path.read_text(), tree['file3'])

    def test_walk(self):
        """Test walk()"""

        with tempfile.TemporaryDirectory() as tmpdirname:
            root = Path(tmpdirname)
            self.assertTrue(root.is_dir())

            tree = {
                'topdir': {
                    'empty.json': touch,
                    'invalid.json': partial(write, 'garbage'),
                    'subdir1': {
                        'not_a_json': touch,
                        'valid.json': '{"key1": "value1"}',
                        'link_to_valid.json': partial(symlink, 'valid.json'),
                    },
                    'emptysubdir': {},
                    'linked_subdir': partial(symlink, 'subdir1'),
                    'not_a_json.2': 'content',
                    'fifo.json': mkfifo,
                }
            }
            self.buildtree(root, tree)

            # import subprocess
            # list_files = subprocess.run(["ls", "-lR", str(root)])
            # self.assertEqual(list_file, '')

            walked = list(walk(root))
            self.assertEqual(len(walked), 6)
            should_be_in = (
                'topdir/empty.json',
                'topdir/invalid.json',
                'topdir/subdir1/link_to_valid.json',
                'topdir/subdir1/valid.json',
                'topdir/linked_subdir/link_to_valid.json',
                'topdir/linked_subdir/valid.json',
            )
            for path in should_be_in:
                self.assertIn(root.joinpath(path), walked)

            should_not_be_in = (
                'topdir/subdir1/not_a_json',
                'topdir/not_a_json.2'
            )
            for path in should_not_be_in:
                self.assertNotIn(root.joinpath(path), walked)
