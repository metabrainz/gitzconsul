"""gitzconsul command-line"""
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
import traceback
from pathlib import Path
import sys
from time import sleep

import click

from gitzconsul import Context
from gitzconsul.sync import SyncKV
from gitzconsul.consultxn import ConsulConnection
from gitzconsul.repo import (
    init_git_repo,
    is_a_git_repository,
    sync_with_remote,
)

log = logging.getLogger('gitzconsul')


# pylint: disable=unused-argument
def loglevelfmt(ctx, param, value):
    """use to convert lowercased level passed as option to uppercase"""
    if value is not None:
        return value.upper()
    return None


POSSIBLE_LEVELS = (
    'CRITICAL',
    'ERROR',
    'WARNING',
    'INFO',
    'DEBUG',
)


@click.command()
@click.option(
    '-r',
    '--root',
    help='root directory to read files from, relative to directory',
    default="",
    show_default=True
)
@click.option(
    '-d',
    '--directory',
    help='directory of the repository, will be created if needed',
    required=True
)
@click.option(
    '-g',
    '--git-url',
    help='git repository remote url',
    default=None
)
@click.option(
    '-R',
    '--git-ref',
    help='git repository remote ref',
    default='refs/heads/master',
    show_default=True
)
@click.option(
    '-k',
    '--consul-key',
    help='add keys under this key',
    required=True
)
@click.option(
    '-u',
    '--consul-url',
    help='consul url',
    default='http://localhost:8500',
    show_default=True
)
@click.option(
    '-i',
    '--interval',
    help='interval in seconds between syncs',
    default=15,
    show_default=True
)
@click.option(
    '-a',
    '--consul-datacenter',
    help='consul datacenter',
    default=None,
)
@click.option(
    '-t',
    '--consul-token',
    help='consul token',
    default=None,
)
@click.option(
    '-T',
    '--consul-token-file',
    help='path to file containing consul token',
    default=None,
)
@click.option(
    '-f',
    '--logfile',
    help="log file path",
    default=None
)
@click.option(
    '-l',
    '--loglevel',
    help="log level",
    default="INFO",
    show_default=True,
    type=click.Choice(POSSIBLE_LEVELS, case_sensitive=False),
    callback=loglevelfmt
)
@click.option(
    '-G',
    '--debug',
    help='output extra debug info',
    is_flag=True
)
def main(**options):
    """Register kv values into consul based on git repository content"""
    context = Context(options)
    interval = context.options['interval']

    log.info("Options: %r", context.options)
    repo_path = None
    git_ref = context.options['git_ref']
    git_url = context.options['git_url']
    repo_path = Path(context.options['directory']).resolve()
    log.info("Directory: %s", repo_path)
    if git_url:
        if not init_git_repo(repo_path, git_url, git_ref):
            sys.exit(1)
    else:
        # no remote repository
        if not repo_path.is_dir():
            log.error("%s isn't a directory", repo_path)
            sys.exit(1)

    root_directory = Path(context.options['root'])
    if root_directory.is_absolute():
        log.error("%s must be relative to %s", root_directory, repo_path)
        sys.exit(1)

    while not context.kill_now:
        try:
            if git_url and is_a_git_repository(repo_path):
                log.info("Fetching from remote %s ref=%s repo=%s", git_url, git_ref, repo_path)
                sync_with_remote(repo_path, git_ref)
            consul_connection = ConsulConnection(
                context.options['consul_url'],
                data_center=context.options['consul_datacenter'],
                acl_token=context.options['consul_token'],
                acl_token_file=context.options['consul_token_file']
            )
            abs_root_directory = repo_path.joinpath(root_directory).resolve()
            if abs_root_directory.is_dir():
                sync = SyncKV(abs_root_directory,
                              context.options['consul_key'], consul_connection)
                log.info(
                    "Syncing consul @%s (%s) with %s",
                    sync.consul_connection,
                    sync.topkey,
                    sync.root)
                sync.do()
            else:
                log.error("Not a directory: %s", abs_root_directory)
        except Exception as exc:  # pylint: disable=broad-except
            log.error(exc)
            if context.options['debug']:
                log.debug(traceback.format_exc())
        finally:
            if not context.kill_now:
                log.debug("sleeping %d second(s)...", interval)
                for _unused in range(0, interval):
                    if not context.kill_now:
                        sleep(1)


if __name__ == "__main__":
    main()
