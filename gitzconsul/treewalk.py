"""functions to walk down git tree"""
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

import base64
from collections.abc import Mapping
import json
from pathlib import Path
import urllib.parse


def walk(root):
    """Walk down tree starting at root and return a generator among all json files"""
    for path in Path(root).iterdir():
        if path.is_dir():
            yield from walk(path)
        elif not path.is_file():
            continue
        elif path.suffix not in {'.json'}:
            continue
        else:
            yield path


class InvalidJsonFileError(OSError):
    """raised when trying to read json from a special file"""


def readjsonfile(path):
    """read file passed as Path as json, and return json data"""
    if not isinstance(path, Path):
        path = Path(path)
    if not path.exists():
        raise InvalidJsonFileError(
            "cannot read json from file {}: doesn't exist".format(path)
        )
    if not path.is_file():
        # avoid special files like fifo or socket
        raise InvalidJsonFileError(
            "cannot read json from file {}: unsupported file type".format(path)
        )
    try:
        with path.open() as json_file:
            return json.load(json_file)
    except (OSError, json.decoder.JSONDecodeError) as exc:
        raise InvalidJsonFileError("cannot read json from file {}: {}".format(path, exc)) from exc


def filepath2key(path, root, sep="/"):
    """Build a key from path which has to be relative to root
       path=/a/b/c root=/a -> b/c
    """
    if not isinstance(path, Path):
        path = Path(path)
    parts = path.relative_to(root).parts
    if any(sep in part for part in parts):
        return None
    return sep.join(parts)


def flatten_json_keys(jsondict, root=None, sep='/'):
    """Generator transforming a tree to a list, flattening all keys

    'a': {
        'b': 'v'
    }
    becomes: 'a/b': 'v'
    """
    if root is None:
        root = []
    for key, value in jsondict.items():
        if not key:
            # we skip empty keys
            continue
        key = str(key)
        if sep in key:
            # we skip containing sep
            continue
        flat_key = root + [key]
        if isinstance(value, Mapping):
            yield from flatten_json_keys(value, root=flat_key, sep=sep)
        else:
            yield sep.join(flat_key), value


def treewalk(root, sep='/'):
    """Parse a tree"""
    for path in walk(root):
        try:
            jsondict = readjsonfile(path)
            pathkey = filepath2key(path, root, sep=sep)
            if not pathkey:
                continue
            for key, value in flatten_json_keys(jsondict, sep=sep):
                yield pathkey + sep + key, value
        except InvalidJsonFileError:
            pass


def chunks(spliceable, chunk_size):
    """Generate chunks of chunk_size from spliceable"""
    for idx in range(0, len(spliceable), chunk_size):
        yield spliceable[idx:idx + chunk_size]


def prepare_for_consul_txn(kvlist):
    """Encode keys and values to suit consul txn"""

    # according to https://github.com/breser/git2consul#json
    # Expanded keys are URI-encoded.
    # The spaces in "you get the picture" are thus converted into %20.
    for key, value in kvlist:
        if not isinstance(value, bytes):
            value = str(value).encode('utf-8')
        # https://python-consul.readthedocs.io/en/latest/#consul.base.Consul.Txn
        # https://www.consul.io/api-docs/txn#kv-operations
        encoded_value = base64.b64encode(value).decode("utf-8")
        encoded_key = urllib.parse.quote(key)
        yield encoded_key, encoded_value


def txn_set_payload(key, value):
    """Build a consul.txn set payload"""
    return {
        'KV': {
            'Verb': 'set',
            'Key': key,
            'Value': value,
        }
    }


def txn_set_kv(cons, kvlist):
    """Execute txn.put set verb for each key/value in kvlist, using cons"""
    puts = []
    for key, value in prepare_for_consul_txn(kvlist):
        puts.append(txn_set_payload(key, value))

    for chunk in chunks(puts, 64):
        yield cons.txn.put(chunk)


def txn_get_payload(key):
    """Build a consul.txn get payload"""
    return {
        'KV': {
            'Verb': 'get',
            'Key': key,
        }
    }


def txn_get_kv(cons, keylist):
    """Execute txn.put for consul obj cons and get values matching for keys in keylist"""
    puts = []
    for key in keylist:
        encoded_key = urllib.parse.quote(key)
        puts.append(txn_get_payload(encoded_key))

    for chunk in chunks(puts, 64):
        yield cons.txn.put(chunk)


class ConsulKVException(Exception):
    """Raised if an error occurs while communicating with consul"""


def set_kv(cons, kvlist):
    """Write keys/values from kvlist to consul KV"""
    try:
        for result in txn_set_kv(cons, kvlist):
            if result['Errors'] is not None:
                raise ConsulKVException(result['Errors'])
    except ConsulKVException:
        raise
    except Exception as exc:
        raise ConsulKVException from exc


def get_kv(cons, keylist):
    """Get values for keys from consul KV"""
    try:
        for result in txn_get_kv(cons, keylist):
            if result['Errors'] is not None:
                raise ConsulKVException(result['Errors'])
            for entry in result['Results']:
                key = entry['KV']['Key']
                value = entry['KV']['Value']
                yield urllib.parse.unquote(key), base64.b64decode(value).decode('utf-8')
    except ConsulKVException:
        raise
    except Exception as exc:
        raise ConsulKVException from exc
