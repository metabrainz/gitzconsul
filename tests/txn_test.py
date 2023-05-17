"""Test consul stuff"""
from http.server import (
    BaseHTTPRequestHandler,
    HTTPServer,
)
import json
import socket
import time
from threading import Thread
import unittest

import requests


from gitzconsul.consultxn import (
    ConsulTransaction,
    ConsulConnection,
    chunks,
    set_kv,
    get_kv,
    get_tree_kv,
    get_tree_kv_indexes,
)


def resp_obj(consul_obj):
    """Returns a copy of consul_obj with Value sets to None"""
    obj = consul_obj.copy()
    obj['Value'] = None
    return obj


class MockServerRequestHandler(BaseHTTPRequestHandler):
    """Mock to simulate consul server"""
    kv_store = {}
    idx = 0

    def do_GET(self):  # pylint: disable=invalid-name
        """Implement do_GET"""
        if self.path == '/ping':
            self.send_response(200, message="pong")
            self.end_headers()
        else:
            self.send_response(404, message="not found")
            self.end_headers()

    def _load(self):
        length = int(self.headers.get('content-length', 0))
        content = self.rfile.read(length)
        json_content = json.loads(content)
        num = len(json_content)
        return num, json_content

    def _kv_set_cas(self, resp, _errors, _i, operation):
        op_kv_key = operation['KV']['Key']
        if op_kv_key in self.kv_store:
            cur = self.kv_store[op_kv_key]['ModifyIndex']
            modifyidx = cur + 1
            createidx = self.kv_store[op_kv_key][
                'CreateIndex']
        else:
            createidx = self.idx
            modifyidx = self.idx
        consul_obj = {
                'LockIndex': 0,
                'Key': op_kv_key,
                'Flags': 0,
                'Value': operation['KV']['Value'],
                'CreateIndex': createidx,
                'ModifyIndex': modifyidx,
            }
        self.kv_store[op_kv_key] = consul_obj
        resp.append({
            'KV': resp_obj(consul_obj)
        })

    def _kv_get(self, resp, errors, i, operation):
        op_kv_key = operation['KV']['Key']
        if op_kv_key in self.kv_store:
            resp.append({
                'KV': self.kv_store[op_kv_key]
            })
        else:
            errors.append({
                'OpIndex': i,
                'What': f'key "{op_kv_key}" doesn\'t exist'
            })

    def _kv_get_tree(self, resp, _errors, _i, operation):
        op_kv_key = operation['KV']['Key']
        selected = [key for key in self.kv_store
                    if key.startswith(op_kv_key)]
        for key in selected:
            resp.append({
                'KV': self.kv_store[key]
            })

    def _kv_delete(self, _resp, _errors, _i, operation):
        op_kv_key = operation['KV']['Key']
        if op_kv_key in self.kv_store:
            del self.kv_store[op_kv_key]
        # no error is generated if trying to delete an
        # unexisting key

    def do_PUT(self):  # pylint: disable=invalid-name
        """Simulate consul PUT txn"""
        if self.path == '/v1/txn':
            num, json_content = self._load()
            if num > 64:
                self.send_response(
                    413,
                    message=("Transaction contains too many operations "
                             f"({num} > 64)")
                )
                self.end_headers()
                return
            resp = []
            errors = []
            self.idx += 1
            for i, operation in enumerate(json_content):
                op_kv_verb = operation['KV']['Verb']
                if op_kv_verb in {'set', 'cas'}:
                    self._kv_set_cas(resp, errors, i, operation)
                elif op_kv_verb == 'get':
                    self._kv_get(resp, errors, i, operation)
                elif op_kv_verb == 'get-tree':
                    self._kv_get_tree(resp, errors, i, operation)
                elif op_kv_verb == 'delete':
                    self._kv_delete(resp, errors, i, operation)
            if errors:
                resp = None
                code = 409
            else:
                errors = None
                code = 200
            resp_json = {
                'Results': resp,
                'Errors': errors,
            }
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            json_str = json.dumps(resp_json)
            self.wfile.write(json_str.encode(encoding='utf_8'))


def get_free_port():
    """Returns the number of a free port"""
    sock = socket.socket(socket.AF_INET, type=socket.SOCK_STREAM)
    sock.bind(('localhost', 0))
    _unused, port = sock.getsockname()
    sock.close()
    return port


class MockException(Exception):
    """Mock Server Exception"""


def start_mock_server(port):
    """Start the mock server"""
    mock_server = HTTPServer(('localhost', port), MockServerRequestHandler)
    mock_server_thread = Thread(target=mock_server.serve_forever)
    mock_server_thread.setDaemon(True)
    mock_server_thread.start()
    # HACK: Wait for the server to be launched
    loops = 0
    while True:
        try:
            requests.get(f"http://localhost:{port}/ping", timeout=0.5)
            break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(0.3)
        loops += 1
        if loops > 10:
            raise MockException("Mock server didn't start!")


class TestTxnUtils(unittest.TestCase):
    """Test class for consul transaction utility methods"""
    def test_chunks(self):
        """test chunks()"""
        numchunks = 10
        chunk_size = 64
        sample = list(range(0, numchunks*chunk_size))
        count = 0
        for chunk in chunks(sample, chunk_size):
            self.assertEqual(len(chunk), chunk_size)
            count += 1
        self.assertEqual(count, numchunks)

        chunk_size = 10
        sample = list(range(0, int(chunk_size*2.5)))
        result = list(chunks(sample, chunk_size))
        expected = [
            [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
            [10, 11, 12, 13, 14, 15, 16, 17, 18, 19],
            [20, 21, 22, 23, 24]
        ]
        self.assertCountEqual(result, expected)


class TestConsulTxn(unittest.TestCase):
    """Test consul txn"""

    def setUp(self):
        port = None
        # use actual consul port to use real server
        # port = 8500

        if port is None:
            port = get_free_port()
            start_mock_server(port)

        self.consul = ConsulConnection(f'http://localhost:{port}')

    def test_consul_set_get_kv(self):
        """test set_kv() and get_kv()"""
        keysvalues = [
            (f'topkey/subkey{i%8}/key {i}', f'value {i}') for i in range(0, 80)
        ]

        all_keys = list(dict(keysvalues))
        set_kvs = list(set_kv(self.consul, keysvalues))
        self.assertCountEqual(set_kvs, all_keys)
        retrieved_kvs = dict(get_kv(self.consul, all_keys))
        self.maxDiff = None  # pylint: disable=invalid-name
        self.assertCountEqual(retrieved_kvs, dict(keysvalues))

        prefix = 'topkey/subkey1/'
        keys = list(dict(get_tree_kv(self.consul, prefix)))
        expected = [key for key in all_keys if key.startswith(prefix)]
        self.assertCountEqual(keys, expected)

        prefix = 'topkey/sub'
        keys = list(dict(get_tree_kv(self.consul, prefix)))
        expected = [key for key in all_keys if key.startswith(prefix)]
        self.assertCountEqual(keys, expected)

        key_idx = {}
        for key, (value, idx) in get_tree_kv_indexes(self.consul, prefix):
            key_idx[key] = idx

        with ConsulTransaction(self.consul) as txn:
            for key, idx in key_idx.items():
                txn.kv_cas(key, "value", idx)
            for results, errors in txn.execute():
                self.assertIsNotNone(results)
                self.assertIsNone(errors)

        for key, (value, idx) in get_tree_kv_indexes(self.consul, prefix):
            self.assertGreater(idx, key_idx[key])
            self.assertEqual(value, "value", idx)

    def test_consul_get_key_not_found(self):
        """Test key not found"""
        with ConsulTransaction(self.consul) as txn:
            # we first fill a chunk with valid ops
            for i in range(0, 64):
                txn.kv_set(f"known_key{i}", i)
            # we start next chunk with 2 valid ops, but third one should fail
            txn.kv_set("known_key", "666")
            txn.kv_get("known_key")
            txn.kv_get("unknown_key")
            count = 0
            for results, errors in txn.execute():
                if count < 64:
                    # we assert first chunk of operations did well
                    self.assertIsNone(errors)
                else:
                    # we assert second chunk of operations failed on third op
                    self.assertIsNone(results)
                    ops, errs = errors
                    self.assertEqual(len(errs), 1)
                    opindex = errs[0]['OpIndex']
                    self.assertEqual(opindex, 2)
                    self.assertEqual(ops[opindex],
                                     {'Verb': 'get', 'Key': 'unknown_key'})
                count += 1

    def test_consul_delete_key(self):
        """Test delete key"""
        with ConsulTransaction(self.consul) as txn:
            txn.kv_set("key_to_delete", "xxx")
            txn.kv_get("key_to_delete")
            txn.kv_delete("key_to_delete")
            txn.kv_get("key_to_delete")
            txn.kv_delete("unkown_key_to_delete")

            for results, errors in txn.execute():
                self.assertIsNone(results)
                ops, errs = errors
                self.assertEqual(len(errs), 1)
                opindex = errs[0]['OpIndex']
                self.assertEqual(opindex, 3)
                self.assertEqual(ops[opindex],
                                 {'Verb': 'get', 'Key': 'key_to_delete'})

    def test_consul_set_int(self):
        """Test set int"""
        with ConsulTransaction(self.consul) as txn:
            txn.kv_set("keyxxx", 666)
            txn.kv_get("keyxxx")

            results = list(txn.execute())
            self.assertEqual(results[0][0]['Value'], '')
            self.assertEqual(results[1][0]['Value'], '666')

    def test_consul_set_empty(self):
        """Test set empty"""
        with ConsulTransaction(self.consul) as txn:
            txn.kv_set("keyxzx", '')
            txn.kv_get("keyxzx")

            results = list(txn.execute())
            self.assertEqual(results[0][0]['Value'], '')
            self.assertEqual(results[1][0]['Value'], '')
