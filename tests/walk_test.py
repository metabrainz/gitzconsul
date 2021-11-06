"""Test walk()"""

import json
from functools import partial
from os import mkfifo
from pathlib import Path
import tempfile
import unittest

from gitzconsul.treewalk import (
    InvalidJsonFileError,
    filepath2key,
    flatten_json_keys,
    readjsonfile,
    walk,
    treewalk,
)


def write(content, path):
    """write contents to file at path"""
    path.open('w', encoding="utf8").write(content)


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
    """Test of walk-related functions"""

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
                root.joinpath(path).open('w', encoding="utf8").write(content)

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
            self.assertEqual(file2path.read_text(encoding='utf8'), 'content2')
            symlink1path = root.joinpath('subdir').joinpath('symlink1')
            self.assertTrue(symlink1path.is_symlink())
            self.assertEqual(symlink1path.read_text(encoding='utf8'), 'content2')
            file3path = root.joinpath('file3')
            self.assertEqual(file3path.read_text(encoding='utf8'), tree['file3'])

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

    def test_readjsonfile(self):
        """test readjsonfile()"""
        with tempfile.TemporaryDirectory() as tmpdirname:
            root = Path(tmpdirname)
            self.assertTrue(root.is_dir())

            tree = {
                'topdir': {
                    'empty.json': touch,
                    'invalid.json': partial(write, '{key1: "value1"}'),
                    'valid.json': '{"key1": "value1"}',
                    'link_to_valid.json': partial(symlink, 'valid.json'),
                    'fifo.json': mkfifo,
                }
            }
            self.buildtree(root, tree)

            data = readjsonfile(root.joinpath('topdir/valid.json'))
            self.assertIn('key1', data)
            self.assertEqual(data['key1'], 'value1')

            with self.assertRaisesRegex(
                InvalidJsonFileError,
                    (r"^cannot read json from file.+"
                        r"Expecting property name enclosed in double quotes")):
                data = readjsonfile(root.joinpath('topdir/invalid.json'))

            with self.assertRaisesRegex(
                InvalidJsonFileError,
                    (r"^cannot read json from file.+"
                        r"doesn't exist")):
                data = readjsonfile(root.joinpath('doesntexist'))

            data = readjsonfile(root.joinpath('topdir/link_to_valid.json'))
            self.assertIn('key1', data)
            self.assertEqual(data['key1'], 'value1')

            with self.assertRaisesRegex(
                InvalidJsonFileError,
                (r"^cannot read json from file.+"
                    r"Expecting value: line 1 column 1 \(char 0\)")):
                data = readjsonfile(root.joinpath('topdir/empty.json'))

            with self.assertRaisesRegex(
                InvalidJsonFileError,
                (r"^cannot read json from file.+"
                    r"unsupported file type")):
                data = readjsonfile(root.joinpath('topdir/fifo.json'))

    def test_filepath2key(self):
        """Test filepath2key()"""

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
                        'subsubdir': {
                            'another.json': touch,
                            'subsubsubdir': {
                                'another.json': touch
                            }
                        }
                    },
                    'emptysubdir': {},
                    'linked_subdir': partial(symlink, 'subdir1'),
                    'not_a_json.2': 'content',
                    'fifo.json': mkfifo,
                    'skip|me.json': 'contains_separator',
                }
            }
            self.buildtree(root, tree)

            keys = [filepath2key(path, root, sep="|") for path in walk(root)]
            expected = {
                'topdir|empty.json',
                'topdir|invalid.json',
                'topdir|linked_subdir|link_to_valid.json',
                'topdir|linked_subdir|subsubdir|another.json',
                'topdir|linked_subdir|subsubdir|subsubsubdir|another.json',
                'topdir|linked_subdir|valid.json',
                'topdir|subdir1|link_to_valid.json',
                'topdir|subdir1|subsubdir|another.json',
                'topdir|subdir1|subsubdir|subsubsubdir|another.json',
                'topdir|subdir1|valid.json',
                None,  # happens when a part of the path contains separator
            }

            self.assertCountEqual(keys, expected)

            with self.assertRaises(ValueError):
                key = filepath2key('/a/b/c', '/d')  # noqa: F841 pylint: disable=unused-variable

    def test_flatten_json_keys(self):
        """test test_flatten_json_keys()"""
        jsondict = {
            "topkey": {
                "key1": "value1",
                "key2": {
                    "subkey1": "valuesubkey1",
                    "subkey2": "valuesubkey2",
                    "subkey3": {
                        "subsubkey1": "valuesubsubkey1",
                    }
                }
            },
            "weird": {
                "": "emptykey",
                123: "numerickey",
                (1, 2): "tuplekey",
                None: "Nonekey",
                'skip|me': 'skipme',
            }
        }
        expected = [
            ('topkey|key1', 'value1'),
            ('topkey|key2|subkey1', 'valuesubkey1'),
            ('topkey|key2|subkey2', 'valuesubkey2'),
            ('topkey|key2|subkey3|subsubkey1', 'valuesubsubkey1'),
            ('weird|123', 'numerickey'),
            ('weird|(1, 2)', 'tuplekey'),
        ]
        self.assertCountEqual(flatten_json_keys(jsondict, sep='|'), expected)
        self.assertCountEqual(flatten_json_keys({}), [])

    def test_treewalk(self):
        """test treewalk()"""
        jsondict1 = {
            "topkey1": {
                "key1": "value1",
                "key2": {
                    "subkey1": "valuesubkey1",
                    "subkey2": "valuesubkey2",
                    "subkey3": {
                        "subsubkey1": "valuesubsubkey1",
                    }
                },
                "num1": 123,
                'bool1': True,
            }
        }
        jsondict2 = {
            "topkey2": {
                "key1": "value1",
                "key2": {
                    "sub|key1": "skipme",
                    "subkey2": "valuesubkey2",
                    "subkey3": {
                        "subsubkey1": "valuesubsubkey1",
                    }
                },
                "array1": ['a', 'b', 'c'],
                'bool2': False,
            }
        }
        with tempfile.TemporaryDirectory() as tmpdirname:
            root = Path(tmpdirname)
            self.assertTrue(root.is_dir())

            tree = {
                'topdir': {
                    'empty.json': touch,
                    'invalid.json': partial(write, 'garbage'),
                    'valid1.json': partial(write, json.dumps(jsondict1)),
                    'valid2.json': partial(write, json.dumps(jsondict2)),
                },
                'skip|me': {
                    'valid1.json': partial(write, json.dumps(jsondict1)),
                }
            }
            self.buildtree(root, tree)
            result = list(treewalk(root, sep='|'))
            expected = [
                ('topdir|invalid.json|', None, True),
                ('topdir|empty.json|', None, True),
                ('topdir|valid1.json|topkey1|key1', 'value1', False),
                ('topdir|valid1.json|topkey1|key2|subkey1', 'valuesubkey1', False),
                ('topdir|valid1.json|topkey1|key2|subkey2', 'valuesubkey2', False),
                ('topdir|valid1.json|topkey1|key2|subkey3|subsubkey1', 'valuesubsubkey1', False),
                ('topdir|valid1.json|topkey1|num1', 123, False),
                ('topdir|valid1.json|topkey1|bool1', True, False),
                ('topdir|valid2.json|topkey2|array1', ['a', 'b', 'c'], False),
                ('topdir|valid2.json|topkey2|key1', 'value1', False),
                ('topdir|valid2.json|topkey2|bool2', False, False),
                ('topdir|valid2.json|topkey2|key2|subkey2', 'valuesubkey2', False),
                ('topdir|valid2.json|topkey2|key2|subkey3|subsubkey1', 'valuesubsubkey1', False),
            ]
            self.maxDiff = 4096  # pylint: disable=invalid-name
            self.assertCountEqual(result, expected)
