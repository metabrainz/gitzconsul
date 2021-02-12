"""Test consul stuff"""
from http.server import (
    BaseHTTPRequestHandler,
    HTTPServer,
)
import base64
import json
import socket
import time
from threading import Thread
import unittest

import consul
import requests


from gitzconsul.treewalk import (
    chunks,
    prepare_for_consul_txn,
    txn_set_payload,
    txn_get_payload,
    txn_set_kv,
    txn_get_kv,
    set_kv,
    get_kv,
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


class TestConsulTxn(unittest.TestCase):
    """Test consul txn"""

    def setUp(self):
        port = None
        # use actual consul port to use real server
        # port = 8500

        if port is None:
            port = get_free_port()
            start_mock_server(port)

        self.consul = consul.Consul(port=port)

    def test_consul_txn(self):
        """test consul txn"""
        keysvalues = [('key'+str(i), 'value'+str(i)) for i in range(0, 80)]
        puts = []
        gets = []
        for key, value in prepare_for_consul_txn(keysvalues):
            puts.append(txn_set_payload(key, value))
            gets.append(txn_get_payload(key))

        with self.assertRaises(consul.base.ClientError):
            result = self.consul.txn.put(puts)

        all_keys = dict(keysvalues)
        for chunk in chunks(puts, 64):
            result = self.consul.txn.put(chunk)
            self.assertIsNone(result['Errors'])
            for entry in result['Results']:
                key = entry['KV']['Key']
                self.assertIn(key, all_keys)
                del all_keys[key]
        self.assertEqual(all_keys, {})

        all_values = dict(keysvalues)
        for chunk in chunks(gets, 64):
            result = self.consul.txn.put(chunk)
            self.assertIsNone(result['Errors'])
            for entry in result['Results']:
                key = entry['KV']['Key']
                value = entry['KV']['Value']
                self.assertIn(key, all_values)
                self.assertEqual(all_values[key], base64.b64decode(value).decode('utf-8'))

    def test_consul_txn_set_get_kv(self):
        """test txn_set_kv() and txn_get_kv()"""
        keysvalues = [('key'+str(i), 'value'+str(i)) for i in range(0, 80)]

        all_keys = dict(keysvalues)
        count = 0
        for result in txn_set_kv(self.consul, keysvalues):
            self.assertIsNone(result['Errors'])
            for entry in result['Results']:
                key = entry['KV']['Key']
                self.assertIn(key, all_keys)
                del all_keys[key]
            count += 1
        self.assertEqual(all_keys, {})
        self.assertEqual(count, 2)

        all_values = dict(keysvalues)
        for result in txn_get_kv(self.consul, all_values.keys()):
            for entry in result['Results']:
                key = entry['KV']['Key']
                value = entry['KV']['Value']
                self.assertIn(key, all_values)
                self.assertEqual(all_values[key], base64.b64decode(value).decode('utf-8'))

    def test_consul_set_get_kv(self):
        """test set_kv() and get_kv()"""
        keysvalues = [('key '+str(i), 'value '+str(i)) for i in range(0, 80)]

        all_keys = list(dict(keysvalues))
        set_kv(self.consul, keysvalues)
        retrieved_kv = dict(get_kv(self.consul, all_keys))
        # self.maxDiff = None
        self.assertCountEqual(retrieved_kv, dict(keysvalues))
