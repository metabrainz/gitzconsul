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

import json
from pathlib import Path


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
