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
    ConsulConnection,
    chunks,
    set_kv,
    get_kv,
    get_tree_kv,
)


class MockServerRequestHandler(BaseHTTPRequestHandler):
    """Mock to simulate consul server"""
    kv_store = dict()
    idx = 0

    def do_GET(self):  # pylint: disable=invalid-name
        """Implement do_GET"""
        if self.path == 'ping':
            self.send_response(200, message="pong")
            self.end_headers()
        else:
            self.send_response(404, message="not found")
            self.end_headers()

    def do_PUT(self):  # pylint: disable=invalid-name
        """Simulate consul PUT txn"""
        if self.path == '/v1/txn':
            length = int(self.headers.get('content-length', 0))
            content = self.rfile.read(length)
            json_content = json.loads(content)
            num = len(json_content)
            if num > 64:
                self.send_response(
                    413,
                    message="Transaction contains too many operations (%d > 64)" % num)
                self.end_headers()
                return
            resp = []
            self.idx += 1
            for item in json_content:
                if item['KV']['Verb'] == 'set':
                    consul_obj = {
                            'LockIndex': 0,
                            'Key': item['KV']['Key'],
                            'Flags': 0,
                            'Value': item['KV']['Value'],
                            'CreateIndex': self.idx,
                            'ModifyIndex': self.idx
                        }
                    self.kv_store[item['KV']['Key']] = consul_obj
                    resp.append({
                        'KV': consul_obj
                    })
                elif item['KV']['Verb'] == 'get':
                    if item['KV']['Key'] in self.kv_store:
                        resp.append({
                            'KV': self.kv_store[item['KV']['Key']]
                        })
                elif item['KV']['Verb'] == 'get-tree':
                    # FIXME: incorrect logic
                    selected = [key for key in self.kv_store
                                if key.startswith(item['KV']['Key'])]
                    for key in selected:
                        resp.append({
                            'KV': self.kv_store[key]
                        })

            resp_json = {
                'Results': resp,
                'Errors': None
            }
            self.send_response(200)
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
            requests.get("http://localhost:%d/ping" % port, timeout=0.5)
            break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(0.3)
        loops += 1
        if loops > 10:
            raise Exception("Mock server didn't start!")


class TestTxnUtils(unittest.TestCase):
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

        self.consul = ConsulConnection('http://localhost:%d' % port)

    def test_consul_set_get_kv(self):
        """test set_kv() and get_kv()"""
        keysvalues = [
            ('topkey/subkey{}/key {}'.format(i % 8, i),
             'value '+str(i)) for i in range(0, 80)]

        all_keys = list(dict(keysvalues))
        set_kvs = list(set_kv(self.consul, keysvalues))
        self.assertCountEqual(set_kvs, all_keys)
        retrieved_kvs = dict(get_kv(self.consul, all_keys))
        self.maxDiff = None
        self.assertCountEqual(retrieved_kvs, dict(keysvalues))

        prefix = 'topkey/subkey1/'
        keys = list(get_tree_kv(self.consul, prefix))
        expected = [key for key in all_keys if key.startswith(prefix)]
        self.assertCountEqual(keys, expected)

        prefix = 'topkey/sub'
        keys = list(get_tree_kv(self.consul, prefix))
        expected = [key for key in all_keys if key.startswith(prefix)]
        self.assertCountEqual(keys, expected)
