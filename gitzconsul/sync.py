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


def sync(root, name, consul_connection):
    if not isinstance(root, Path):
        root = Path(root)
    if not root.is_dir():
        raise Exception("a directory is required")
    if not isinstance(consul_connection, ConsulConnection):
        raise Exception("a ConsulConnection is required")
    if not name:
        raise Exception("a name is required")
    log.info("Querying consul %s" % consul_connection)
    topkey = name + '/'
    known_kv_items = dict(get_tree_kv(consul_connection, topkey))
    to_add = []
    to_modify = []
    known_kv_keys = set(known_kv_items)
    log.info("Found %d keys" % len(known_kv_keys))
    log.info("Parsing %s" % root)
    for raw_key, value in treewalk(root):
        key = topkey + raw_key
        if key not in known_kv_keys:
            to_add.append((key, value))
        elif str(value) != str(known_kv_items[key]):
            log.debug(value)
            log.debug(known_kv_items[key])
            # FIXME: int vs str, problem?
            to_modify.append((key, value))
            del known_kv_items[key]
        else:
            del known_kv_items[key]
    to_delete = [key for key in list(known_kv_items)]

    if to_modify:
        log.info("Modifying %d element(s)" % len(to_modify))
        log.debug(to_modify)
        with ConsulTransaction(consul_connection) as txn:
            for tup in to_modify:
                key, value = tup
                txn.kv_set(key, value)
            for results, errors in txn.execute():
                if errors:
                    log.error(errors)

    if to_add:
        log.info("Adding %d element(s)" % len(to_add))
        log.debug(to_add)
        with ConsulTransaction(consul_connection) as txn:
            for tup in to_add:
                key, value = tup
                txn.kv_set(key, value)
            for results, errors in txn.execute():
                if errors:
                    log.error(errors)

    if to_delete:
        log.info("Deleting %d element(s)" % len(to_delete))
        log.debug(to_delete)
        with ConsulTransaction(consul_connection) as txn:
            for key in to_delete:
                txn.kv_delete(key)
            for results, errors in txn.execute():
                if errors:
                    log.error(errors)
