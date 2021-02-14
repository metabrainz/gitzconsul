from base64 import b64decode, b64encode
import json
from urllib.parse import unquote, quote, urlencode

import requests


class ConsulTransactionException(Exception):
    """Raised if an error occurs while communicating with consul"""


class ConsulConnection:

    def __init__(self, url, data_center=None, acl_token=None,
                 acl_token_file=None, user_agent="gitzconsul"):
        self.baseurl = url
        self._params = dict()

        if data_center is not None:
            self._params['dc'] = data_center

        if acl_token_file:
            with open(acl_token_file, "r") as tokenfile:
                value = tokenfile.read()
                if value:
                    acl_token = value
        if acl_token:
            acl_token = acl_token.strip()

        self.headers = {
            'Content-Type': "application/json",
            'User-Agent': user_agent,
            'Accept': "*/*",
            'Cache-Control': "no-cache",
        }
        if acl_token:
            self.headers['X-Consul-Token'] = acl_token

    @property
    def params(self):
        return urlencode(self._params)


class ConsulTransaction:
    MAX_PER_TRANSACTION = 64

    def __init__(self, consul_connection):
        self._operations = []
        self._errors = None
        self._consul_connection = consul_connection

    def _query(self, payload):
        conn = self._consul_connection
        data = json.dumps(payload)
        url = "{}/v1/txn".format(conn.baseurl)
        params = conn.params
        if params:
            url += '?' + params
        response = requests.request("PUT",
                                    url,
                                    data=data,
                                    headers=conn.headers
                                    )
        return response.status_code, json.loads(response.content)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def add(self, what):
        self._operations.append(what)

    def execute(self, result_keys=('Key', 'Value')):
        errors = dict()
        for count, chunk in enumerate(chunks(self._operations,
                                             self.MAX_PER_TRANSACTION)):
            code, content = self._query(chunk)
            if code == 200:
                for entry in content['Results']:
                    resdict = {}
                    for kv_key, kv_value in entry['KV'].items():
                        if kv_key == 'Key':
                            kv_value = decode_key(kv_value)
                        elif kv_key == 'Value':
                            kv_value = decode_value(kv_value)
                        resdict[kv_key] = kv_value
                    yield resdict
            else:
                error_msg = None
                if content and 'Errors' in content:
                    error_msg = content['Errors']
                errors[count] = code, error_msg, chunk
        if errors:
            raise ConsulTransactionException(errors)

    # https://www.consul.io/api-docs/txn#kv-operations

    def kv_set(self, key, value, flags=None):
        """Sets the Key to the given Value"""

        payload = {
            'KV': {
                'Verb': 'set',
                'Key': encode_key(key),
                'Value': encode_value(value),
            }
        }
        self.add(payload)

    def kv_cas(self, key, value, index, flags=None):
        """Sets, but with CAS semantics"""

        payload = {
            'KV': {
                'Verb': 'cas',
                'Key': encode_key(key),
                'Value': encode_value(value),
                'Index': int(index),
            }
        }
        self.add(payload)

    def kv_lock(self, key, value, session, flags=None):
        """Lock with the given Session"""

        payload = {
            'KV': {
                'Verb': 'lock',
                'Key': encode_key(key),
                'Value': encode_value(value),
                'Session': session,
            }
        }
        self.add(payload)

    def kv_unlock(self, key, value, session, flags=None):
        """Unlock with the given Session"""

        payload = {
            'KV': {
                'Verb': 'unlock',
                'Key': encode_key(key),
                'Value': encode_value(value),
                'Session': session,
            }
        }
        self.add(payload)

    def kv_get(self, key):
        """Get the key, fails if it does not exist"""

        payload = {
            'KV': {
                'Verb': 'get',
                'Key': encode_key(key),
            }
        }
        self.add(payload)

    def kv_get_tree(self, key):
        """Gets all keys with the prefix"""

        payload = {
            'KV': {
                'Verb': 'get-tree',
                'Key': encode_key(key),
            }
        }
        self.add(payload)

    def kv_check_index(self, key, index):
        """Fail if modify index != index"""

        payload = {
            'KV': {
                'Verb': 'check-index',
                'Key': encode_key(key),
                'Index': int(index),
            }
        }
        self.add(payload)

    def kv_check_session(self, key, session):
        """Fail if not locked by session"""

        payload = {
            'KV': {
                'Verb': 'check-session',
                'Key': encode_key(key),
                'Session': session,
            }
        }
        self.add(payload)

    def kv_check_not_exists(self, key):
        """Fail if key exists"""

        payload = {
            'KV': {
                'Verb': 'check-not-exists',
                'Key': encode_key(key),
            }
        }
        self.add(payload)

    def kv_delete(self, key):
        """Delete the key"""

        payload = {
            'KV': {
                'Verb': 'delete',
                'Key': encode_key(key),
            }
        }
        self.add(payload)

    def kv_delete_tree(self, key):
        """Delete all keys with a prefix"""

        payload = {
            'KV': {
                'Verb': 'delete-tree',
                'Key': encode_key(key),
            }
        }
        self.add(payload)

    def kv_delete_cas(self, key, index):
        """Delete, but with CAS semantics"""

        payload = {
            'KV': {
                'Verb': 'delete-cas',
                'Key': encode_key(key),
                'Index': int(index),
            }
        }
        self.add(payload)


def encode_value(value):
    if not isinstance(value, bytes):
        value = str(value).encode('utf-8')
    # https://python-consul.readthedocs.io/en/latest/#consul.base.Consul.Txn
    # https://www.consul.io/api-docs/txn#kv-operations
    return b64encode(value).decode("utf-8")


def decode_value(value):
    if value is not None:
        value = b64decode(value).decode('utf-8')
    return value


def encode_key(key):
    # according to https://github.com/breser/git2consul#json
    # Expanded keys are URI-encoded.
    # The spaces in "you get the picture" are thus converted into %20.
    return quote(key)


def decode_key(key):
    return unquote(key)


def chunks(spliceable, chunk_size):
    """Generate chunks of chunk_size from spliceable"""
    for idx in range(0, len(spliceable), chunk_size):
        yield spliceable[idx:idx + chunk_size]


def set_kv(cons, kvlist):
    """Write keys/values from kvlist to consul KV"""
    with ConsulTransaction(cons) as txn:
        for key, value in kvlist:
            txn.kv_set(key, value)
        for result in txn.execute():
            yield result['Key']


def get_kv(cons, keylist):
    """Get values for keys from consul KV"""
    with ConsulTransaction(cons) as txn:
        for key in keylist:
            txn.kv_get(key)
        for result in txn.execute():
            yield result['Key'], result['Value']


def get_tree_kv(cons, key):
    with ConsulTransaction(cons) as txn:
        txn.kv_get_tree(key)
        for result in txn.execute():
            yield result['Key']
