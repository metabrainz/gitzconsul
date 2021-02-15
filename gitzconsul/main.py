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
from time import sleep

import click


from gitzconsul import Context
from gitzconsul.sync import sync
from gitzconsul.consultxn import ConsulConnection


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
    '--root-directory',
    help='root directory',
    required=True
)
@click.option(
    '-n',
    '--name',
    help='top key name',
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
    '-d',
    '--delay',
    help='delay',
    default=15,
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
    help='consul token file',
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
    delay = context.options['delay']

    print(context.options)
    while not context.kill_now:
        try:
            consul_connection = ConsulConnection(
                context.options['consul_url'],
                data_center=context.options['consul_datacenter'],
                acl_token=context.options['consul_token'],
                acl_token_file=context.options['consul_token_file']
            )
            sync(context.options['root_directory'], context.options['name'], consul_connection)
        except Exception as exc:  # pylint: disable=broad-except
            log.error(exc)
            log.error(traceback.format_exc())
        finally:
            if not context.kill_now:
                log.debug("sleeping %d second(s)...", delay)
                sleep(delay)


if __name__ == "__main__":
    main()
