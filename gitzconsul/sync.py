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

from pathlib import Path

from gitzconsul.treewalk import treewalk
from gitzconsul.consultxn import (
    get_tree_kv,
    ConsulConnection,
    ConsulTransaction
)


def sync(root, name, consul_connection):
    if not isinstance(root, Path):
        root = Path(root)
    if not root.is_dir():
        raise Exception("a directory is required")
    if not isinstance(consul_connection, ConsulConnection):
        raise Exception("a ConsulConnection is required")
    if not name:
        raise Exception("a name is required")
    topkey = name + '/'
    known_kv_items = dict(get_tree_kv(consul_connection, topkey))
    to_add = []
    to_modify = []
    known_kv_keys = set(known_kv_items)
    print(known_kv_keys)
    for raw_key, value in treewalk(root):
        key = topkey + raw_key
        print(key)
        if key not in known_kv_keys:
            to_add.append((key, value))
        elif value != known_kv_items[key]:
            to_modify.append((key, value))
            del known_kv_items[key]
        else:
            del known_kv_items[key]
    to_delete = [key for key in list(known_kv_items)]

    print("Modify")
    print(to_modify)
    with ConsulTransaction(consul_connection) as txn:
        for tup in to_modify:
            key, value = tup
            txn.kv_set(key, value)
        for results, errors in txn.execute():
            if errors:
                print(errors)

    print("Add")
    print(to_add)
    with ConsulTransaction(consul_connection) as txn:
        for tup in to_add:
            key, value = tup
            txn.kv_set(key, value)
        for results, errors in txn.execute():
            if errors:
                print(errors)

    print("Delete")
    print(to_delete)
    with ConsulTransaction(consul_connection) as txn:
        for key in to_delete:
            txn.kv_delete(key)
        for results, errors in txn.execute():
            if errors:
                print(errors)
