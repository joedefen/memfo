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
import curses
from datetime import datetime
try:
    from PowerWindow import Window , OptionSpinner
    # from MyUtils import human, ago_whence, timestamp_str
except Exception:
    from memfo.PowerWindow import Window , OptionSpinner
    # from my_snaps.MyUtils import human, ago_whence, timestamp_str


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

##############################################################################
def clamp(least, value, most):
    """ Constrain a number between to values """
    return least if least > value else most if value > most else value

class MemFo:
    """ TBD """
    singleton = None
    max_value = 999*1000*1000*1000
    def __init__(self, opts):
        assert not MemFo.singleton

        self.mono_start = time.monotonic()
        self.fh = open('/proc/meminfo', 'r', encoding='utf-8')
        self.DB = opts.DB
        self.dump = opts.dump
        self.vmalloc_total = opts.vmalloc_total
        if self.vmalloc_total:
            MemFo.max_value *= 1000
        self.zeros = opts.zeros
        self.interval = clamp(0.5, opts.interval_sec, 3600.0)

        self.units, self.divisor, self.data_width = opts.units, 0, 0
        self.delta = False # whether to show deltas
        self.win = None  # PowerWindow
        self.spin = None # Option Spinner
        self.mode = 'normal' # or 'edit' or 'help'
        self.edit_mode = False # true in when editing
        self.infos = []
        self.loops_per_info = 1
        self.loops_fro_store = 0
        self.term_width = 0 # how wide is the terminal
        
        self.key_width = None
        self.data_width = None
        self.report_lines = None # the stuff to display
        self._set_units()
        
        self.freezes = []  # fields that are frozen (above the line)
        self.thaws = []    # fields that are thawed (below the line)
        self.hides = []    # fields that are hidden
        
    def start_curses(self, line_cnt=200):
        """ Start window mode"""
        if self.win:
            return
        self.spin = OptionSpinner()
#       self.spin.add_key('mode', '? - help screen',
#                         vals=['normal', 'help'], obj=self)
        self.spin.add_key('edit_mode', 'e - edit mode', vals=[False, True],
                comments='Select line and use "edit" key', obj=self)
#       self.spin.add_key('fit_to_window', 'f - fit rows to window',
#                         vals=[False, True], obj=self.opts)
#       self.spin.add_key('groupby', 'g - group by',
#                         vals=['exe', 'cmd', 'pid'], obj=self.opts)
#       self.spin.add_key('numbers', 'n - line numbers',
#                         vals=[False, True], obj=self.opts)
#       self.spin.add_key('others', 'o - less category detail',
#                         vals=[False, True], obj=self.opts)
#       self.spin.add_key('rise_to_top', 'r - raise new/changed to top',
#                         vals=[False, True], obj=self.opts)
#       self.spin.add_key('sortby', 's - sort by',
#                         vals=['mem', 'cpu', 'name'], obj=self.opts)
        self.spin.add_key('units', 'u - memory units',
                          vals=['KB', 'mB', 'MB', 'gB', 'GB', 'human'], obj=self)
        self.spin.add_key('delta', 'd - show deltas',
                          vals=[False, True], obj=self)
        self.spin.add_key('zeros', 'z - show all zeros lines',
                          vals=[False, True], obj=self)
#       self.spin.add_key('cpu_avg_secs', 'a - cpu moving avg secs',
#                         vals=[5, 10, 20, 45, 90], obj=self.opts)
#       self.spin.add_key('search', '/ - search string',
#                         prompt='Set search string, then Enter', obj=self.opts)

        keys_we_handle =  [ord('K'), curses.KEY_ENTER, 10] + list(self.spin.keys)

        self.win = Window(head_line=True, head_rows=line_cnt,
                          body_rows=line_cnt, keys=keys_we_handle)

    def stop_curses(self, line_cnt=200):
        """ Close down window mode """
        if self.win:
            self.win.stop_curses()

    def _set_units(self):
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
    
    def render(self, value, sign=''):
        """ Render a value into a string per the current options
            Given no value, render the max supported.
        """
        sign = '+' if sign else ''
        if not self.divisor:
            string = human(value)
            if sign and string[0] != '-':
                string = f'+{string}'
            rv = f'{human(value):>{self.data_width}}'
        else:
            value = round(value/self.divisor, self.precision)
            if self.precision:
                rv = f'{value:{sign}{self.data_width},.{self.precision}f}'
            else:
                rv = f'{int(value):{sign}{self.data_width},d}'
        return rv

    def render_slices(self, infos, count=5000):
        """ TBD """
        lines = []
        delta = 'DELTA' if self.delta else 'delta'
        zeros = 'ZEROS' if self.zeros else 'zeros'
        edit = 'EDIT' if self.edit_mode else 'edit'
        line = f'u:{self.units} d:{delta} z={zeros} e={edit}'
        lines.append(line)
        row_cnt = 1
        rows = {}

        for ii, info in enumerate(infos):
            ago = f'{ago_str(info["_mono"]-self.mono_start)}'
            for key in list(info.keys())[:count]:
                if key.startswith('_'):
                    ago = f'{ago_str(info["_mono"]-self.mono_start)}'
                    line = f'{ago:>{self.data_width}}'
                    if ii == len(infos)-1:
                        time_str = datetime.now().strftime("%m/%d %H:%M:%S")
                        line += f' {time_str}'
                else:
                    if rows.get(key, None) == -1:
                        continue
                    if ii == 0 and not self.zeros:
                        peak = max([info[key] for info in infos])
                        if peak == 0:
                            rows[key] = -1
                            continue

                    val = info[key]
                    if ii < len(infos)-1:
                        if self.delta:
                            next_val = self.infos[ii+1][key]
                            line = self.render(next_val-val, sign=True)
                        else:
                            line = self.render(val)
                    else: # ii == len(infos)-1:
                        line = self.render(val)
                        line += f' {key:<{self.key_width}}'
                if key not in rows:
                    row = rows[key] = row_cnt
                    row_cnt += 1
                    lines.append(line)
                else:
                    row = rows[key]
                    lines[row] += ' ' + line
        self.report_lines = lines
            
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
            floor_s = self.interval*self.loops_per_info * 0.95
            delta_s = info['_mono'] - self.infos[-2]['_mono']
            if delta_s < floor_s:
                # push out closing this bucket
                self.loops_fro_store -= 1
            else:
                self.loops_fro_store = 0
                if len(self.infos) > MAX_INFOS:
                    self.infos = [self.infos[i]
                               for i in range(0, MAX_INFOS+1, 2)]
                    self.loops_per_info *= 2

        # print([ago_str(info['_mono']-self.mono_zero) for info in self.infos])

    def _read_info(self):
        self.fh.seek(0)
        info = {'_mono': time.monotonic()}
        for line in self.fh:
            mat = re.match(r'^([^:]+):\s*(\d+)\s*(|kB)$', line)
            if mat:
                key, val, suffix = mat.group(1), int(mat.group(2)), mat.group(3)
                if key == 'VmallocTotal' and not self.vmalloc_total:
                    continue
                val *= 1024 if suffix == 'kB' else 1
                info[key] = val
        if not self.key_width:
            self.key_width = max([len(k) for k in info])

        # if self.DB:
            # self.dump_infos([info])
        return info
    
    def update_report_data(self):
        """ Get new data and report on it. """
        info = self._read_info()
        self._append_info(info)
        self.term_width, _ = shutil.get_terminal_size()
        cols_width = self.term_width - self.key_width
        col_cnt = max(1, cols_width//(1+self.data_width))
        
        if len(self.infos) <= col_cnt:
            slices = self.infos
        else:
            slices = []
            for cnt in range(col_cnt-1):
                position = int(round(cnt*(len(self.infos)-1)/(col_cnt-1)))
                slices.append(self.infos[position])
            slices.append(self.infos[-1])
        self.render_slices(slices)
        
    def do_window(self):
        """ one loop of window rendering """
        def do_key(key):
#           regroup = False
#           # ENSURE keys are in 'keys_we_handle'
#           if key in (ord('/'), ):
#               pass
            if key in self.spin.keys:
                self.spin.do_key(key, self.win)
                if key in (ord('u'), ):
                    self._set_units()
#               elif key in (ord('?'), ):
#                   self.window.set_pick_mode(False if self.mode == 'help'
#                                          else self.opts.kill_mode)
                elif key in (ord('e'), ):
                    if self.mode in ('normal', 'edit'):
                        self.win.set_pick_mode(self.edit_mode)

#           elif key in (curses.KEY_ENTER, 10):
#               if self.mode == 'help':
#                   self.mode = 'normal'
#               elif self.opts.kill_mode:
#                   win = self.window
#                   group = self.groups_by_line.get(win.pick_pos, None)
#                   if group:
#                       pids = [x.pid for x in group.prcset]
#                       answer = win.answer(seed='',
#                           prompt=f'Type "y" to kill: {group.summary["info"]} {pids}')
#                       if answer.lower().startswith('y'):
#                           killer = KillThem(pids)
#                           ok, message = killer.do_kill()
#                           win.alert(title='OK' if ok else 'FAIL', message=message)
#                   self.opts.kill_mode = False
#                   self.window.set_pick_mode(self.opts.kill_mode)
#           return regroup

        self.start_curses()

        if self.mode == 'help':
            pass
        elif self.mode == 'edit':
            pass
        else: # normal mode
            self.win.clear()
            self.win.add_header(self.report_lines[0])
            self.win.add_header(self.report_lines[1])
            for line in self.report_lines[2:]:
                self.win.add_body(line)
            self.win.render()
            do_key(self.win.prompt(seconds=self.interval))

    def loop(self):
        """ The main loop for the program """
        while True:
            self.update_report_data()

            if self.dump:
                print('\n' + '\n'.join(self.report_lines) + '\n')
                if self.DB:
                    print([ago_str(info['_mono']-self.mono_start) for info in slices])
                time.sleep(self.interval)
                continue
            else:
                self.do_window()

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
    parser.add_argument('-i', '--interval-sec', type=float, default=1.0,
            help='loop interval in seconds [dflt=1.0] ')
    parser.add_argument('--vmalloc-total', action="store_true",
            help='Show "VmallocTotal" row (which is mostly useless)')
    parser.add_argument('-z', '--zeros', action="store_true",
            help='Show lines with all zeros')
    parser.add_argument('-d', '--dump', action="store_true",
            help='"print" the data rather than "display" it')
#   parser.add_argument('--cron', type=str,
#           choices=('hourly', 'daily', 'weekly', 'monthly'),
#           help='install a periodic snapshot anacron job')
    parser.add_argument('-u', '--units', choices=('KB', 'mB', 'MB', 'gB', 'GB', 'human'),
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
