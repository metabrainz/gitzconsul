"""functions syncing consul KV with directory"""
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

import logging
from pathlib import Path

from gitzconsul.treewalk import treewalk
from gitzconsul.consultxn import (
    get_tree_kv,
    ConsulConnection,
    ConsulTransaction
)


log = logging.getLogger('gitzconsul')


class SyncKVException(Exception):
    """SyncKVException"""


class SyncKV:

    def __init__(self, root, name, consul_connection):
        if not isinstance(root, Path):
            root = Path(root)
        if not root.is_dir():
            raise SyncKVException("a directory is required")
        if not isinstance(consul_connection, ConsulConnection):
            raise SyncKVException("a ConsulConnection is required")
        if not name:
            raise SyncKVException("a name is required")
        self.root = root
        self.name = name
        self.consul_connection = consul_connection
        self.topkey = self.name + '/'

    def do(self):
        log.info("Syncing consul @%s (%s) with %s" % (
                    self.consul_connection,
                    self.topkey,
                    self.root,
                    )
                 )
        known_kv_items = dict(get_tree_kv(self.consul_connection, self.topkey))
        log.debug("kv items in consul: %r" % known_kv_items)
        known_kv_keys = set(known_kv_items)
        self.num_consul_keys = len(known_kv_items)
        self.num_dir_keys = 0
        self.to_add = []
        self.to_modify = []
        for raw_key, value in treewalk(self.root):
            value = str(value)  # all values are stored as strings
            key = self.topkey + raw_key
            if key not in known_kv_keys:
                self.to_add.append((key, value))
            elif value != known_kv_items[key]:
                self.to_modify.append((key, value))
                del known_kv_items[key]
            else:
                del known_kv_items[key]
            self.num_dir_keys += 1
        self.to_delete = [key for key in list(known_kv_items)]
        self.kv_sync()

    def kv_sync(self):
        num_add = len(self.to_add)
        num_del = len(self.to_delete)
        num_mod = len(self.to_modify)
        if not (num_add + num_del + num_mod):
            return
        log.info("Consul: %d Dir: %d Modified: %d Added: %d Deleted: %d" % (
                 self.num_consul_keys, self.num_dir_keys, num_mod, num_add,
                 num_del))
        if num_mod:
            self.kv_modify()
        if num_add:
            self.kv_add()
        if num_del:
            self.kv_delete()

    def kv_modify(self):
        log.debug("to_modify: %r" % self.to_modify)
        with ConsulTransaction(self.consul_connection) as txn:
            for tup in self.to_modify:
                key, value = tup
                txn.kv_set(key, value)
            for results, errors in txn.execute():
                if errors:
                    log.error(errors)

    def kv_add(self):
        log.debug("to_add: %r" % self.to_add)
        with ConsulTransaction(self.consul_connection) as txn:
            for tup in self.to_add:
                key, value = tup
                txn.kv_set(key, value)
            for results, errors in txn.execute():
                if errors:
                    log.error(errors)

    def kv_delete(self):
        log.debug("to_delete: %r" % self.to_delete)
        with ConsulTransaction(self.consul_connection) as txn:
            for key in self.to_delete:
                txn.kv_delete(key)
            for results, errors in txn.execute():
                if errors:
                    log.error(errors)
