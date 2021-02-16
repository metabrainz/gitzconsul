"""functions to make consul txn queries and handle responses"""
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

from base64 import b64decode, b64encode
import json
from urllib.parse import unquote, quote, urlencode

import requests


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

    def __str__(self):
        return self.baseurl


class ConsulTransactionOp:

    def __init__(self, operation):
        payload = {
            'KV': {
                'Verb': operation['Verb'],
                'Key': encode_key(operation['Key']),
            }
        }
        if 'Value' in operation:
            payload['KV']['Value'] = encode_value(operation['Value'])
        if 'Index' in operation:
            payload['KV']['Index'] = int(operation['Index'])
        if 'Session' in operation:
            payload['KV']['Session'] = operation['Session']

        self.operation = operation
        self.payload = payload


class ConsulTransaction:
    MAX_PER_TRANSACTION = 64
    # https://requests.readthedocs.io/en/master/user/quickstart/#timeouts
    TIMEOUT = 0.5

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
                                    headers=conn.headers,
                                    timeout=self.TIMEOUT,
                                    )
        return response.status_code, json.loads(response.content)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def add(self, operation):
        self._operations.append(ConsulTransactionOp(operation))

    def _execute(self):
        size = self.MAX_PER_TRANSACTION
        for chunk in chunks(self._operations, size):
            code, response = self._query([op.payload for op in chunk])
            yield code, response, [op.operation for op in chunk]

    def execute(self, match_keys=None):
        if match_keys is None:
            match_keys = {'Key', 'Value'}
        else:
            match_keys = set(match_keys)
        for code, response, operations in self._execute():
            if code == 200:
                for entry in response['Results']:
                    resdict = {}
                    for kv_key, kv_value in entry['KV'].items():
                        if kv_key == 'Key':
                            kv_value = decode_key(kv_value)
                        elif kv_key == 'Value':
                            kv_value = decode_value(kv_value)
                        if match_keys is None or kv_key in match_keys:
                            resdict[kv_key] = kv_value
                    yield resdict, None
            else:
                yield None, (operations, response['Errors'])

    # https://www.consul.io/api-docs/txn#kv-operations

    # CAS: If the cas is 0, then Consul will only put the key if it does not
    # already exist. If the cas value is non-zero, then the key is only set
    # if the index matches the ModifyIndex of that key.

    def kv_set(self, key, value, flags=None):
        """Sets the Key to the given Value"""

        self.add({
            'Verb': 'set',
            'Key': key,
            'Value': value,
        })

    def kv_cas(self, key, value, index, flags=None):
        """Sets, but with CAS semantics"""

        self.add({
            'Verb': 'cas',
            'Key': key,
            'Value': value,
            'Index': index,
        })

    def kv_lock(self, key, value, session, flags=None):
        """Lock with the given Session"""

        self.add({
            'Verb': 'lock',
            'Key': key,
            'Value': value,
            'Session': session,
        })

    def kv_unlock(self, key, value, session, flags=None):
        """Unlock with the given Session"""

        self.add({
            'Verb': 'unlock',
            'Key': key,
            'Value': value,
            'Session': session,
        })

    def kv_get(self, key):
        """Get the key, fails if it does not exist"""

        self.add({
            'Verb': 'get',
            'Key': key,
        })

    def kv_get_tree(self, key):
        """Gets all keys with the prefix"""

        self.add({
            'Verb': 'get-tree',
            'Key': key,
        })

    def kv_check_index(self, key, index):
        """Fail if modify index != index"""

        self.add({
            'Verb': 'check-index',
            'Key': key,
            'Index': index,
        })

    def kv_check_session(self, key, session):
        """Fail if not locked by session"""

        self.add({
            'Verb': 'check-session',
            'Key': key,
            'Session': session,
        })

    def kv_check_not_exists(self, key):
        """Fail if key exists"""

        self.add({
            'Verb': 'check-not-exists',
            'Key': key,
        })

    def kv_delete(self, key):
        """Delete the key"""

        self.add({
            'Verb': 'delete',
            'Key': key,
        })

    def kv_delete_tree(self, key):
        """Delete all keys with a prefix"""

        self.add({
            'Verb': 'delete-tree',
            'Key': key,
        })

    def kv_delete_cas(self, key, index):
        """Delete, but with CAS semantics"""

        self.add({
            'Verb': 'delete-cas',
            'Key': key,
            'Index': index,
        })


def encode_value(value):
    if not isinstance(value, bytes):
        value = str(value).encode('utf-8')
    # https://python-consul.readthedocs.io/en/latest/#consul.base.Consul.Txn
    # https://www.consul.io/api-docs/txn#kv-operations
    return b64encode(value).decode("utf-8")


def decode_value(value):
    if value is not None:
        return b64decode(value).decode('utf-8')
    else:
        return ''


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
        for result, errors in txn.execute():
            if not errors:
                yield result['Key']


def get_kv(cons, keylist):
    """Get values for keys from consul KV"""
    with ConsulTransaction(cons) as txn:
        for key in keylist:
            txn.kv_get(key)
        for result, errors in txn.execute():
            if not errors:
                yield result['Key'], result['Value']


def get_tree_kv(cons, key):
    with ConsulTransaction(cons) as txn:
        txn.kv_get_tree(key)
        for result, errors in txn.execute():
            if not errors:
                yield result['Key'], result['Value']


def get_tree_kv_indexes(cons, key):
    match_keys = {'Key', 'Value', 'ModifyIndex'}
    with ConsulTransaction(cons) as txn:
        txn.kv_get_tree(key)
        for result, errors in txn.execute(match_keys=match_keys):
            if not errors:
                yield result['Key'], (result['Value'], result['ModifyIndex'])
