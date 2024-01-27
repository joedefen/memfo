#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memfo is a viewer for /proc/meminfo
"""
# pylint: disable=invalid-name,global-statement
# pylint: disable=import-outside-toplevel,consider-using-with
# pylint: disable=broad-exception-caught,too-few-public-methods


import sys
import re
import traceback
import time
import shutil

##############################################################################
def ago_str(delta_secs, signed=False):
    """ Turn time differences in seconds to a compact representation;
    ¦   e.g., '18h·39m'
    """
    ago = int(max(0, round(delta_secs if delta_secs >= 0 else -delta_secs)))
    divs = (60, 60, 24, 7, 52, 9999999)
    units = ('s', 'm', 'h', 'd', 'w', 'y')
    vals = (ago%60, int(ago/60)) # seed with secs, mins (step til 2nd fits)
    uidx = 1 # best units
    for div in divs[1:]:
        # print('vals', vals, 'div', div)
        if vals[1] < div:
            break
        vals = (vals[1]%div, int(vals[1]/div))
        uidx += 1
    rv = '-' if signed and delta_secs < 0 else ''
    rv += f'{vals[1]}{units[uidx]}' if vals[1] else ''
    rv += f'{vals[0]:d}{units[uidx-1]}'
    return rv


##############################################################################
##   human()
##############################################################################
def human(number):
    """ Return a concise number description."""
    if number < 0:
        return '-' + human(-number)
    suffixes = ['K', 'M', 'G', 'T']
    while suffixes:
        suffix = suffixes.pop(0)
        number /= 1024
        if number < 999.95 or not suffixes:
            return f'{number:.1f}{suffix}'
    return '' # impossible, but make pylint happy


class MemFo:
    """ TBD """
    max_value = 999*1000*1000*1000*10000
    def __init__(self, opts):
        self.mono_zero = time.monotonic()
        self.fh = open('/proc/meminfo', 'r', encoding='utf-8')
        self.DB = opts.DB
        self.units, self.divisor, self.data_width = opts.units, 0, 0
        self.win = None
        self.infos = []
        self.loops_per_info = 1
        self.loops_fro_store = 0
        self.term_width = 0 # how wide is the terminal
        
        self.key_width = None
        self.data_width = None
        self._init_units()

    def _init_units(self):
        self.precision = 1
        if self.units == 'mB':
            self.divisor = 1000*1000
        elif self.units == 'MB':
            self.divisor = 1024*1024
        elif self.units == 'gB':
            self.divisor = 1000*1000*1000
        elif self.units == 'GB':
            self.divisor = 1024*1024*1024
        elif self.units == 'KB':
            self.divisor = 1024 # KB (the original)
            self.precision = 0
        else: # human
            self.divisor = 0 # human
            self.precision = 0
        self.data_width = 1
        self.data_width = len(self.render(-self.max_value))
        # if self.units == 'human':
         #    self.data_width = 1+min(self.data_width, 7)
    
    def render(self, value):
        """ Render a value into a string per the current options
            Given no value, render the max supported.
        """
        if not self.divisor:
            rv = f'{human(value):>{self.data_width}}'
        else:
            value = round(value/self.divisor, self.precision)
            if self.precision:
                rv = f'{value:{self.data_width},.{self.precision}f}'
            else:
                rv = f'{int(value):{self.data_width},d}'
        return rv

    def dump_infos(self, infos, count=5):
        """ TBD """
        lines = []
        line = f'\nunits={self.units}'
        lines.append(line)
        for info in infos:
            ago = f'{ago_str(info["_mono"]-self.mono_zero)}'
            for idx, key in enumerate(list(info.keys())[:count]):
                if key.startswith('_'):
                    ago = f'{ago_str(info["_mono"]-self.mono_zero)}'
                    line = f'{ago:>{self.data_width}}'
                else:
                    line = {self.render(info[key])}
                    if idx == len(infos)-1:
                        line += f'{key:<{self.key_width}}'
                idx += 1
                if idx >= len(lines):
                    lines.append(line)
                else:
                    lines[idx] += ' ' + line
        if self.DB:
            print(lines)
            
    def _append_info(self, info):
        """ Add and compress memory in a pattern like:
        ['0s']
        ['0s', '1s']
        ['0s', '1s', '2s']
        ['0s', '1s', '2s', '3s']
        ['0s', '1s', '2s', '3s', '4s']
        ['0s', '1s', '2s', '3s', '4s', '5s']
        ['0s', '1s', '2s', '3s', '4s', '5s', '6s']
        ['0s', '1s', '2s', '3s', '4s', '5s', '6s', '7s']
        ['0s', '2s', '4s', '6s', '8s']
        ['0s', '2s', '4s', '6s', '8s', '9s']
        ['0s', '2s', '4s', '6s', '8s', '10s']
        ['0s', '2s', '4s', '6s', '8s', '10s', '11s']
        ['0s', '2s', '4s', '6s', '8s', '10s', '12s']
        ['0s', '2s', '4s', '6s', '8s', '10s', '12s', '13s']
        ['0s', '2s', '4s', '6s', '8s', '10s', '12s', '14s']
        ['0s', '2s', '4s', '6s', '8s', '10s', '12s', '14s', '15s']
        ['0s', '4s', '8s', '12s', '16s']

        
        """
        MAX_INFOS = 8
        MAX_INFOS = 128
        if not self.infos:
            self.infos.append(info)
            self.loops_fro_store = 0
            self.loops_per_info = 1
        elif self.loops_fro_store == 0:
            self.infos.append(info)
            self.loops_fro_store += 1
        else:
            self.infos[-1] = info
            self.loops_fro_store += 1
        if self.loops_fro_store >= self.loops_per_info:
            self.loops_fro_store = 0
            if len(self.infos) > MAX_INFOS:
                self.infos = [self.infos[i] for i in range(0, MAX_INFOS+1, 2)]
                self.loops_per_info *= 2

        # print([ago_str(info['_mono']-self.mono_zero) for info in self.infos])

    def _read_info(self):
        self.fh.seek(0)
        info = {'_mono': time.monotonic()}
        for line in self.fh:
            mat = re.match(r'^([^:]+):\s*(\d+)\s*(|kB)$', line)
            if mat:
                key, val, suffix = mat.group(1), int(mat.group(2)), mat.group(3)
                val *= 1024 if suffix == 'kB' else 1
                info[key] = val
        if not self.key_width:
            self.key_width = max([len(k) for k in info])

        if self.DB:
            self.dump_infos([info])
        return info

    def loop(self):
        """ The main loop for the program """
        while True:
            info = self._read_info()
            self._append_info(info)
            self.term_width, _ = shutil.get_terminal_size()
            cols_width = self.term_width - self.key_width
            col_cnt = max(1, cols_width//(1+self.data_width))
            
            if len(self.infos) <= col_cnt:
                reports = self.infos
            else:
                reports = []
                for cnt in range(col_cnt-1):
                    position = int(round(cnt*(len(self.infos)-1)/(col_cnt-1)))
                    reports.append(self.infos[position])
                reports.append(self.infos[-1])

            print([ago_str(info['_mono']-self.mono_zero) for info in reports])

            time.sleep(1)

memfo = None
def main():
    """ TBD """
    global memfo
    import argparse

    parser = argparse.ArgumentParser()
#   parser.add_argument('-s', '--add-snap-max', type=int, default=0,
#           help='add snapshots limited to value per subvol [1<=val<=8]')
#   parser.add_argument('-L', '--label', type=str,
#           help='add given label to -s snapshots')
#   parser.add_argument('-p', '--print', action="store_true",
#           help='print the subvolumes/snaps and exit')
#   parser.add_argument('--cron', type=str,
#           choices=('hourly', 'daily', 'weekly', 'monthly'),
#           help='install a periodic snapshot anacron job')
    parser.add_argument('-u', '--units', choices=('MB', 'mB', 'KB', 'GB', 'gB', 'human'),
            default='MB', help='units of memory [dflt=MB]')
    
    parser.add_argument('--DB', action="store_true",
            help='add some debugging output')
    opts = parser.parse_args()
#   if opts.add_snap_max > 0:
#       opts.add_snap_max = min(opts.add_snap_max, 8)
#   if opts.cron:
#       if not opts.label:
#           opts.label = '=' + opts.cron.capitalize()

    memfo = MemFo(opts)
    memfo.loop()


def run():
    """ Entry point"""
    try:
        main()
    except KeyboardInterrupt:
        if memfo and memfo.win:
            memfo.stop_curses()
        print('\n   OK, QUITTING NOW\n')
        sys.exit(0)
    except Exception as exce:
        if memfo and memfo.win:
            memfo.stop_curses()
        print("exception:", str(exce))
        print(traceback.format_exc())
        sys.exit(15)


if __name__ == "__main__":
    run()
