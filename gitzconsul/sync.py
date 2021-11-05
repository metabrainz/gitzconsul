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
    get_tree_kv_indexes,
    ConsulConnection,
    ConsulTransaction
)


log = logging.getLogger('gitzconsul')


class SyncKVException(Exception):
    """SyncKVException"""


class SyncKVChanges:
    """Hold required changes to sync consul with local directory"""

    def __init__(self, num_dir_keys=0, num_consul_keys=0):
        self.to_add = []
        self.to_modify = []
        self.to_delete = []
        self.num_dir_keys = num_dir_keys
        self.num_consul_keys = num_consul_keys

    @property
    def needed(self):
        """Returns True if changes are needed"""
        return self.to_add or self.to_modify or self.to_delete

    @property
    def counts(self):
        """Returns a dict with counts for each change"""
        return {
            'add': len(self.to_add),
            'mod': len(self.to_modify),
            'del': len(self.to_delete),
            'consul': self.num_consul_keys,
            'dir': self.num_dir_keys,
        }


class SyncKV:
    """Sync local directory with consul kv"""

    changes = None

    def __init__(self, root, name, consul_connection):
        """Init SyncKV Object"""
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

    def do(self):   # pylint: disable=invalid-name
        """Do the sync"""
        known_kv_items = dict(get_tree_kv_indexes(self.consul_connection,
                                                  self.topkey))
        log.debug("number of kv items in consul: %d", len(known_kv_items))
        known_kv_keys = set(known_kv_items)
        self.changes = SyncKVChanges(num_consul_keys=len(known_kv_items))
        for raw_key, value, error in treewalk(self.root):
            key = self.topkey + raw_key
            if error:
                for k in list(known_kv_items):
                    if k.startswith(key):
                        # do not touch kv matching bugged json file
                        del known_kv_items[k]
                continue
            if isinstance(value, bool):
                # compat with git2consul which stores True/False as true/false strings
                value = str(value).lower()
            else:
                value = str(value)  # all values are stored as strings
            if key not in known_kv_keys:
                self.changes.to_add.append((key, value))
            else:
                new_value, idx = known_kv_items[key]
                if value != new_value:
                    self.changes.to_modify.append((key, value, idx))
                del known_kv_items[key]
            self.changes.num_dir_keys += 1
        self.changes.to_delete = [(key, value[1]) for key, value in known_kv_items.items()]
        self.kv_sync()

    def kv_sync(self):
        """Count changes and sent them to consul if needed"""
        if not self.changes.needed:
            return
        log.info("Consul: %d Dir: %d Modified: %d Added: %d Deleted: %d",
                 self.changes.counts['consul'],
                 self.changes.counts['dir'],
                 self.changes.counts['mod'],
                 self.changes.counts['add'],
                 self.changes.counts['del'])
        with ConsulTransaction(self.consul_connection) as txn:
            self.kv_modify(txn)
            self.kv_add(txn)
            self.kv_delete(txn)
            for _results, errors in txn.execute():
                if errors:
                    log.error(errors)

    def kv_modify(self, txn):
        """Update modified keys/values"""
        if self.changes.to_modify:
            log.debug("to_modify: %r", self.changes.to_modify)
            for key, value, idx in self.changes.to_modify:
                txn.kv_cas(key, value, idx)

    def kv_add(self, txn):
        """Add new keys/values"""
        if self.changes.to_add:
            log.debug("to_add: %r", self.changes.to_add)
            for key, value in self.changes.to_add:
                txn.kv_cas(key, value, 0)

    def kv_delete(self, txn):
        """Delete keys/values"""
        if self.changes.to_delete:
            log.debug("to_delete: %r", self.changes.to_delete)
            for key, idx in self.changes.to_delete:
                txn.kv_delete_cas(key, idx)
