"""Test sync module"""

import json
import socket
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
import tempfile
import unittest

import requests

from gitzconsul.consultxn import ConsulConnection
from gitzconsul.sync import SyncKV, SyncKVChanges, SyncKVException


def write(content, path):
    path.open("w", encoding="utf8").write(content)


def buildtree(root, tree):
    for name, content in tree.items():
        if isinstance(content, dict):
            subdir = root / name
            subdir.mkdir()
            buildtree(subdir, content)
        elif callable(content):
            content(root / name)
        else:
            (root / name).open("w", encoding="utf8").write(content)


# Reuse mock consul server pattern from txn_test.py
class MockConsulHandler(BaseHTTPRequestHandler):
    kv_store = {}
    idx = 0

    def log_message(self, format, *args):
        pass  # silence request logs

    def do_GET(self):
        if self.path == "/ping":
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_PUT(self):
        if self.path.startswith("/v1/txn"):
            length = int(self.headers.get("content-length", 0))
            content = json.loads(self.rfile.read(length))
            resp, errors = [], []
            self.idx += 1
            for i, op in enumerate(content):
                verb = op["KV"]["Verb"]
                key = op["KV"]["Key"]
                if verb in {"set", "cas"}:
                    if key in self.kv_store:
                        modidx = self.kv_store[key]["ModifyIndex"] + 1
                        createidx = self.kv_store[key]["CreateIndex"]
                    else:
                        modidx = createidx = self.idx
                    obj = {
                        "LockIndex": 0,
                        "Key": key,
                        "Flags": 0,
                        "Value": op["KV"].get("Value"),
                        "CreateIndex": createidx,
                        "ModifyIndex": modidx,
                    }
                    self.kv_store[key] = obj
                    r = obj.copy()
                    r["Value"] = None
                    resp.append({"KV": r})
                elif verb == "get":
                    if key in self.kv_store:
                        resp.append({"KV": self.kv_store[key]})
                    else:
                        errors.append({"OpIndex": i, "What": f'key "{key}" doesn\'t exist'})
                elif verb == "get-tree":
                    for k in sorted(self.kv_store):
                        if k.startswith(key):
                            resp.append({"KV": self.kv_store[k]})
                elif verb in {"delete", "delete-cas"}:
                    if key in self.kv_store:
                        del self.kv_store[key]
            code = 409 if errors else 200
            body = {
                "Results": None if errors else resp,
                "Errors": errors if errors else None,
            }
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())


def get_free_port():
    s = socket.socket(socket.AF_INET, type=socket.SOCK_STREAM)
    s.bind(("localhost", 0))
    _, port = s.getsockname()
    s.close()
    return port


def start_mock_server(port):
    server = HTTPServer(("localhost", port), MockConsulHandler)
    t = Thread(target=server.serve_forever)
    t.daemon = True
    t.start()
    for _ in range(20):
        try:
            requests.get(f"http://localhost:{port}/ping", timeout=0.5)
            return server
        except requests.exceptions.ConnectionError:
            time.sleep(0.2)
    raise RuntimeError("Mock server didn't start")


class TestSyncKVChanges(unittest.TestCase):
    def test_empty_changes(self):
        c = SyncKVChanges()
        self.assertFalse(c.needed)
        self.assertEqual(c.counts, {"add": 0, "mod": 0, "del": 0, "consul": 0, "dir": 0})

    def test_needed_with_adds(self):
        c = SyncKVChanges()
        c.to_add.append(("k", "v"))
        self.assertTrue(c.needed)

    def test_needed_with_deletes(self):
        c = SyncKVChanges()
        c.to_delete.append(("k", 1))
        self.assertTrue(c.needed)

    def test_needed_with_modifies(self):
        c = SyncKVChanges()
        c.to_modify.append(("k", "v", 1))
        self.assertTrue(c.needed)


class TestSyncKVInit(unittest.TestCase):
    def test_requires_directory(self):
        conn = ConsulConnection("http://localhost:8500")
        with self.assertRaises(SyncKVException):
            SyncKV(Path("/nonexistent"), "key", conn)

    def test_requires_consul_connection(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SyncKVException):
                SyncKV(Path(d), "key", "not a connection")

    def test_requires_name(self):
        conn = ConsulConnection("http://localhost:8500")
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SyncKVException):
                SyncKV(Path(d), "", conn)

    def test_accepts_string_root(self):
        conn = ConsulConnection("http://localhost:8500")
        with tempfile.TemporaryDirectory() as d:
            sync = SyncKV(d, "mykey", conn)
            self.assertIsInstance(sync.root, Path)
            self.assertEqual(sync.topkey, "mykey/")


class TestSyncKVDo(unittest.TestCase):
    def setUp(self):
        self.port = get_free_port()
        MockConsulHandler.kv_store = {}
        MockConsulHandler.idx = 0
        self.server = start_mock_server(self.port)
        self.consul = ConsulConnection(f"http://localhost:{self.port}")

    def _make_dir(self, tree):
        self.tmpdir = tempfile.mkdtemp()
        root = Path(self.tmpdir)
        buildtree(root, tree)
        return root

    def test_add_keys(self):
        root = self._make_dir(
            {
                "file.json": json.dumps({"k1": "v1", "k2": "v2"}),
            }
        )
        sync = SyncKV(root, "test", self.consul)
        sync.do()
        self.assertEqual(sync.changes.counts["add"], 2)
        self.assertEqual(sync.changes.counts["mod"], 0)
        self.assertEqual(sync.changes.counts["del"], 0)

    def test_no_changes_on_second_run(self):
        root = self._make_dir(
            {
                "file.json": json.dumps({"k1": "v1"}),
            }
        )
        sync = SyncKV(root, "test", self.consul)
        sync.do()
        self.assertTrue(sync.changes.needed)
        # Second run — no changes
        sync2 = SyncKV(root, "test", self.consul)
        sync2.do()
        self.assertFalse(sync2.changes.needed)

    def test_modify_keys(self):
        root = self._make_dir(
            {
                "file.json": json.dumps({"k1": "v1"}),
            }
        )
        sync = SyncKV(root, "test", self.consul)
        sync.do()
        # Modify the file
        (root / "file.json").write_text(json.dumps({"k1": "v2"}), encoding="utf8")
        sync2 = SyncKV(root, "test", self.consul)
        sync2.do()
        self.assertEqual(sync2.changes.counts["mod"], 1)
        self.assertEqual(sync2.changes.counts["add"], 0)

    def test_delete_keys(self):
        root = self._make_dir(
            {
                "file.json": json.dumps({"k1": "v1", "k2": "v2"}),
            }
        )
        sync = SyncKV(root, "test", self.consul)
        sync.do()
        # Remove a key from the file
        (root / "file.json").write_text(json.dumps({"k1": "v1"}), encoding="utf8")
        sync2 = SyncKV(root, "test", self.consul)
        sync2.do()
        self.assertEqual(sync2.changes.counts["del"], 1)

    def test_bool_values_stored_lowercase(self):
        root = self._make_dir(
            {
                "file.json": json.dumps({"flag": True}),
            }
        )
        sync = SyncKV(root, "test", self.consul)
        sync.do()
        # Verify the value was stored as "true" (lowercase)
        # Run again — should not detect a change
        sync2 = SyncKV(root, "test", self.consul)
        sync2.do()
        self.assertFalse(sync2.changes.needed)

    def test_invalid_json_leaves_keys_untouched(self):
        root = self._make_dir(
            {
                "file.json": json.dumps({"k1": "v1"}),
            }
        )
        sync = SyncKV(root, "test", self.consul)
        sync.do()
        self.assertEqual(sync.changes.counts["add"], 1)
        # Corrupt the file
        (root / "file.json").write_text("not json", encoding="utf8")
        sync2 = SyncKV(root, "test", self.consul)
        sync2.do()
        # Key should not be deleted
        self.assertEqual(sync2.changes.counts["del"], 0)

    def test_subdirectory(self):
        root = self._make_dir(
            {
                "sub": {
                    "file.json": json.dumps({"k": "v"}),
                },
            }
        )
        sync = SyncKV(root, "test", self.consul)
        sync.do()
        self.assertEqual(sync.changes.counts["add"], 1)
        # Verify key includes subdirectory
        self.assertIn("test/sub/file.json/k", [k for k, _ in sync.changes.to_add])
