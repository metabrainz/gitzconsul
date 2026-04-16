"""Test consultxn utility functions and ConsulConnection"""

import tempfile
import unittest

from gitzconsul.consultxn import (
    ConsulConnection,
    ConsulTransactionOp,
    decode_key,
    decode_value,
    encode_key,
    encode_value,
)


class TestEncoding(unittest.TestCase):
    """Test encode/decode functions"""

    def test_encode_value_bytes(self):
        result = encode_value(b"hello")
        self.assertEqual(decode_value(result), "hello")

    def test_encode_value_string(self):
        result = encode_value("hello")
        self.assertEqual(decode_value(result), "hello")

    def test_decode_value_none(self):
        self.assertEqual(decode_value(None), "")

    def test_encode_decode_key(self):
        key = "my key/with spaces"
        self.assertEqual(decode_key(encode_key(key)), key)


class TestConsulConnection(unittest.TestCase):
    """Test ConsulConnection"""

    def test_basic(self):
        conn = ConsulConnection("http://localhost:8500")
        self.assertEqual(str(conn), "http://localhost:8500")
        self.assertEqual(conn.params, "")
        self.assertNotIn("X-Consul-Token", conn.headers)

    def test_with_datacenter(self):
        conn = ConsulConnection("http://localhost:8500", data_center="dc1")
        self.assertIn("dc=dc1", conn.params)

    def test_with_acl_token(self):
        conn = ConsulConnection("http://localhost:8500", acl_token="mytoken")
        self.assertEqual(conn.headers["X-Consul-Token"], "mytoken")

    def test_with_acl_token_stripped(self):
        conn = ConsulConnection("http://localhost:8500", acl_token="  mytoken  ")
        self.assertEqual(conn.headers["X-Consul-Token"], "mytoken")

    def test_with_acl_token_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".token", delete=False) as f:
            f.write("filetoken")
            f.flush()
            conn = ConsulConnection("http://localhost:8500", acl_token_file=f.name)
        self.assertEqual(conn.headers["X-Consul-Token"], "filetoken")

    def test_with_empty_acl_token_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".token", delete=False) as f:
            f.write("")
            f.flush()
            conn = ConsulConnection("http://localhost:8500", acl_token_file=f.name)
        self.assertNotIn("X-Consul-Token", conn.headers)


class TestConsulTransactionOp(unittest.TestCase):
    """Test ConsulTransactionOp"""

    def test_with_value(self):
        op = ConsulTransactionOp({"Verb": "set", "Key": "k", "Value": "v"})
        self.assertEqual(op.payload["KV"]["Verb"], "set")
        self.assertIn("Value", op.payload["KV"])

    def test_with_index(self):
        op = ConsulTransactionOp({"Verb": "cas", "Key": "k", "Value": "v", "Index": 5})
        self.assertEqual(op.payload["KV"]["Index"], 5)

    def test_with_session(self):
        op = ConsulTransactionOp({"Verb": "lock", "Key": "k", "Value": "v", "Session": "sess1"})
        self.assertEqual(op.payload["KV"]["Session"], "sess1")

    def test_without_optional_fields(self):
        op = ConsulTransactionOp({"Verb": "get", "Key": "k"})
        self.assertNotIn("Value", op.payload["KV"])
        self.assertNotIn("Index", op.payload["KV"])
        self.assertNotIn("Session", op.payload["KV"])
