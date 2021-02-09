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

from collections import UserDict
import logging
import signal
import sys


log = logging.getLogger('gitzconsul')


class Context:
    kill_now = False
    on_exit = dict()
    _sig2name = None
    gitzconsul = None

    def __init__(self, options):
        self.options = options
        self.configure_logging(options)

        # exit signals
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)
        # following signals may be used later
        signal.signal(signal.SIGUSR1, self.ignore_signal)
        signal.signal(signal.SIGUSR2, self.ignore_signal)
        signal.signal(signal.SIGHUP, self.ignore_signal)

    def _log_signal(self, signum):
        if self._sig2name is None:
            # extract signal names from signal module
            # signal.Signals is an enum
            self._sig2name = dict([(s.value, s.name) for s in signal.Signals])

        name = self._sig2name.get(signum, signum)
        log.info("Received {} signal".format(name))

    def ignore_signal(self, signum, frame):
        self._log_signal(signum)

    def exit_gracefully(self, signum, frame):
        self._log_signal(signum)
        self.kill_now = True
        for func in self.on_exit.values():
            func()
        log.info("Exiting gracefully...")

    def register_on_exit(self, name, func):
        self.on_exit[name] = func

    def configure_logging(self, options):
        console_handler = logging.StreamHandler(sys.stderr)
        handlers = [console_handler]
        logfile = self.options['logfile']
        if logfile:
            try:
                filehandler = logging.FileHandler(filename=logfile)
                handlers.append(filehandler)
            except Exception:
                pass

        logging.basicConfig(
            level=logging.ERROR,
            format='[%(asctime)s] {%(module)s:%(lineno)d} %(levelname)s - %(message)s',
            handlers=handlers
        )
        try:
            log.setLevel(options['loglevel'])
        except ValueError as e:
            log.error(e)
