#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memfo is a viewer for /proc/meminfo
TODO:
- add dump-to-csv key and it put current samples into a file.... maybe takes
   over header line for 10s to show feedback
- ensure collection is being done during help screen and edit screen (not sure)
- update README considerably
"""
# pylint: disable=invalid-name,global-statement
# pylint: disable=import-outside-toplevel,consider-using-with
# pylint: disable=broad-exception-caught,too-few-public-methods
# pylint: disable=too-many-branches,too-many-statements,consider-using-generator
# pylint: disable=too-many-instance-attributes,too-many-locals,line-too-long
# pylint: disable=too-many-lines


import sys
import os
import re
import traceback
import configparser
import time
import curses
import shutil
from datetime import datetime
from types import SimpleNamespace
from console_window import ConsoleWindow , OptionSpinner
from memfo.TimeMemory import TimeMemory, TimeSlicer
from memfo.dumper import dump_to_csv


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

        self.sample_secs = 1
        self.history = TimeMemory(sample_secs=self.sample_secs)
        self.slicer = TimeSlicer(self.history)
        self.mono_start = time.monotonic()
        self.fh = open('/proc/meminfo', 'r', encoding='utf-8')
        self.vmalloc_total = opts.vmalloc_total
        if self.vmalloc_total:
            MemFo.max_value *= 1000
        self.zeros = opts.zeros
        self.config_basename = opts.config

        self.units, self.divisor, self.data_width = opts.units, 0, 0
        self.delta = False # whether to show deltas
        self.win = None  # ConsoleWindow
        self.spin = None # Option Spinner
        self.page = 'normal' # or 'edit' or 'help'
        self.edit_mode = False # true in when editing
        self.help_mode = False # true in when in help screen
        self.report_interval = 'Var'  # column interval
        self.prev_report_interval_secs = None
        self.term_width = 0 # how wide is the terminal
        self.report_intervals = {'Var': 0, '5s': 5, '15s': 15,
                                '30s': 30, '1m': 60, '5m': 300,
                                '15m': 900, '1hr': 3600}

        self.key_width = None
        self.data_width = None
        self.report_rows = None # the stuff to display
        self._set_units()
        self.message = ''
        self.message_mono = None

        self.non_zeros = set() # ever non-zero since program started
        self.freezes = set()  # fields that are frozen (above the line)
        self.hides = set()    # fields that are hidden
        self.edit_cnt = 0     # number of pending edits
        self.config = None
        self.config_file = None
        self.init_config()

    def start_curses(self, line_cnt=200):
        """ Start window mode"""
        if self.win:
            return
        self.spin = OptionSpinner()
        self.spin.add_key('units', 'u - memory units',
                          vals=['KiB', 'MB', 'MiB', 'GB', 'GiB', 'human'], obj=self)
        self.spin.add_key('report_interval', 'i - report interval',
                          vals=list(self.report_intervals.keys()), obj=self)
        self.spin.add_key('delta', 'd - show deltas',
                          vals=[False, True], obj=self)
        self.spin.add_key('zeros', 'z - show all zeros lines',
                          vals=[False, True], obj=self)
        self.spin.add_key('dump_report', 'D - dump history stats to /tmp/memfo.csv',
                          vals=[False, True], obj=self)
        self.spin.add_key('edit_mode', 'e - edit mode', vals=[False, True],
                comments='"*" freezes lines; "-" hides lines', obj=self)
        self.spin.add_key('help_mode', '? - help screen',
                          vals=[False, True], obj=self)

        keys_we_handle =  [ord('*'), ord('-'), ord('r'), ord('R'),
                           curses.KEY_ENTER, 10] + list(self.spin.keys)

        self.win = ConsoleWindow(head_line=True, head_rows=line_cnt,
                          body_rows=line_cnt, keys=keys_we_handle)

    def init_config(self):
        """ Get the configuration ... create if missing. """
        self.config_file = os.path.expanduser(
            '~/.config/memfo/{self.config_basename}.ini')
        if not os.path.isfile(self.config_file):
            self.edit_cnt = 1 # make it "dirty"
            self.commit_config(freezes='MemTotal MemAvailable'.split(),
                               hides='KernelStack Active(file)'.split())
        self.config = configparser.RawConfigParser(allow_no_value=True)
        self.config.optionxform = lambda option: option
        self.config.read(self.config_file)
        if 'Frozen Fields' in self.config.sections():
            self.freezes = set(self.config['Frozen Fields'].keys())
        if 'Hidden Fields' in self.config.sections():
            self.hides = set(self.config['Hidden Fields'].keys())
        # print(f'{self.freezes=}')
        # print(f'{self.hides=}')

    def commit_config(self, freezes=None, hides=None):
        """ Write the config file from the current state or a given."""
        if self.edit_cnt == 0:
            return
        self.edit_cnt = 0
        freezes = list(self.freezes if freezes is None else freezes)
        hides = list(self.hides if hides is None else hides)
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        with open(self.config_file, "w+", encoding='utf-8') as fh:
            fh.write('[Frozen Fields]\n' + '\n'.join(freezes) + '\n')
            fh.write('\n[Hidden Fields]\n' + '\n'.join(hides) + '\n')

    def stop_curses(self):
        """ Close down window mode """
        if self.win:
            self.win.stop_curses()

    def _set_units(self):
        self.precision = 1
        if self.units == 'MB':
            self.divisor = 1000*1000
        elif self.units == 'MiB':
            self.divisor = 1024*1024
        elif self.units == 'GB':
            self.divisor = 1000*1000*1000
        elif self.units == 'GiB':
            self.divisor = 1024*1024*1024
        elif self.units == 'KiB':
            self.divisor = 1024 # KiB (the original)
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

    def render_slices(self, slices):
        """ TBD """
        def add_row(key, text, zero=False):
            nonlocal rows
            rows[key] = SimpleNamespace(key=key, zero=zero, text=text)
            if not zero:
                self.non_zeros.add(key)

        count = 5000
        rows = {}
        delta = 'ON' if self.delta else 'off'
        zeros = 'ON' if self.zeros else 'off'
        if self.message and self.message_mono is not None:
            text = f"****  ALERT: {self.message} ****"
            if time.monotonic() - self.message_mono >= 10.0:
                self.message, self.message_mono = '', None
        elif self.page == 'normal':
            text = f'[u]nits:{self.units} [i]tvl={self.report_interval} [d]eltas:{delta} zeros={zeros} Dump [e]dit ?=help'
        else:
            text = ('EDIT SCREEN:  e,ENTER:return'
                    + ' *:put-on-top -:hide-line [r]eset-line [R]reset-all-lines  ?=help')
        add_row(key='_lead', text=text)

        for ii, info in enumerate(slices):
            for key in list(info.keys())[:count]:
                if key == '_mono':
                    ago = f'{ago_str(info["_mono"])}'
                    text = f'{ago:>{self.data_width}}'
                    if ii == len(slices)-1:
                        time_str = datetime.now().strftime("%m/%d %H:%M:%S")
                        text += f' {time_str}'
                else:
                    val = info[key]
                    if ii < len(slices)-1 and self.delta:
                        next_val = slices[ii+1][key]
                        text = self.render(next_val-val, sign=True)
                    else:
                        text = self.render(val)
                # now add the text of the file to the text of the line
                if key in rows:
                    rows[key].text += ' ' + text
                elif key.startswith('_') or key in self.non_zeros:
                    add_row(key, text)
                else:
                    peak = max([info[key] for info in slices])
                    add_row(key, text, zero=bool(peak==0))
        self.report_rows = rows

    def _read_info(self):
        self.fh.seek(0)
        info = {'_mono': int(round(time.monotonic()-self.mono_start)),
                '_time': time.time()}
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

        return info

    def update_report_data(self):
        """ Get new data and report on it, sampling history based on sample count
            (fixed interval) or adaptive logic (Var).
        """

        # ----------------------------------------------------------------------
        # 0. INITIALIZATION AND SETUP
        # ----------------------------------------------------------------------

        # 1. READ and APPEND New Data
        info = self._read_info()
        self.history.append_info(info)

        # 2. CALCULATE Screen Constraints
        self.term_width, _ = shutil.get_terminal_size()
        self.key_width = getattr(self, 'key_width', 0)
        self.data_width = getattr(self, 'data_width', 0)
        cols_width = self.term_width - self.key_width

        if self.page == 'edit':
            cols_width -= 4

        # Maximum number of columns that can physically fit on the screen
        max_col_cnt = max(1, cols_width // (1 + self.data_width))

        # 3. DETERMINE Interval Mode
        interval_secs = self.report_intervals.get(self.report_interval, 0)
        if interval_secs > 0:
            interval_secs = max(interval_secs, self.history.info_secs)
        is_mode_switch = bool(self.prev_report_interval_secs != interval_secs)
        is_var_mode = (self.report_interval == 'Var' or interval_secs == 0)

        self.prev_report_interval_secs = self.report_interval # Update for next loop's check

        if is_var_mode:
            slices = self.slicer.get_var_slices(max_col_cnt)
        else:
            slices = self.slicer.get_fixed_slices(interval_secs,
                        max_col_cnt, is_mode_switch)

        self.render_slices(slices)

    def render_help_screen(self):
        """Populate help screen"""
        self.win.clear()
        self.win.add_header(
                "-- HELP SCREEN ['?' or ENTER closes Help; Ctrl-C exits ] --",
                 attr=curses.A_BOLD)
        self.spin.show_help_nav_keys(self.win)
        self.spin.show_help_body(self.win)
        self.win.render()


    def render_normal_report(self):
        """ TBD"""
        self.win.clear()
        for row in self.report_rows.values():
            if row.key.startswith('_time'):
                pass
            elif row.key.startswith('_'):
                self.win.add_header(row.text, attr=curses.A_BOLD)
            elif row.key in self.freezes:
                self.win.add_header(f'{row.text} {row.key}')
            elif not self.zeros and row.zero:
                continue
            elif row.key not in self.hides:
                self.win.add_body(f'{row.text} {row.key}')
        self.win.render()

    def render_edit_report(self):
        """ TBD"""
        def text(row, flag):
            return f'{row.text} {flag} {row.key}'

        self.win.clear()
        for row in self.report_rows.values():
            if row.key.startswith('_'):
                self.win.add_header(row.text)
            elif row.key in self.freezes:
                self.win.add_body(text(row, '***'))
            elif row.key in self.hides:
                self.win.add_body(text(row, '---'))
            else:
                self.win.add_body(text(row, '   '))
        self.win.render()

    def do_window(self):
        """ one loop of window rendering """
        def set_page():
            if self.help_mode:
                self.page = 'help'
                self.win.set_pick_mode(False)
                self.commit_config()
            elif self.edit_mode:
                self.page = 'edit'
                self.win.set_pick_mode(True)
            else:
                self.page = 'normal'
                self.win.set_pick_mode(False)
                self.commit_config()

        def do_key(key):
#           # ENSURE keys are in 'keys_we_handle'
#           if key in (ord('/'), ):
#               pass
            if key in self.spin.keys:
                self.spin.do_key(key, self.win)
                if key in (ord('u'), ):
                    self._set_units()
                elif key in (ord('?'), ):
                    set_page()
                elif key in (ord('e'), ):
                    set_page()
                elif self.dump_report:
                    self.message = dump_to_csv(self.history.infos)
                    self.message_mono = time.monotonic()
                    self.dump_report = False

            elif key in (ord('*'), ord('-'), ord('r'), ord('R') ):
                if self.page in ('edit', ):
                    row = list(self.report_rows.values())[self.win.pick_pos+3]
                    param = row.key
                    if key == ord('*'):
                        self.hides.discard(param)
                        self.freezes.add(param)
                    elif key == ord('-'):
                        self.freezes.discard(param)
                        self.hides.add(param)
                    elif key == ord('r'):
                        self.hides.discard(param)
                        self.freezes.discard(param)
                    elif key == ord('R'):
                        self.hides, self.freezes = set(), set()
                    self.edit_cnt += 1
                    if key in (ord('*'), ord('-'), ord('r') ):
                        self.win.last_pick_pos = self.win.pick_pos
                        self.win.pick_pos = min(
                            self.win.pick_pos+1, self.win.body.row_cnt-1)

            elif key in (curses.KEY_ENTER, 10):
                if self.help_mode:
                    self.help_mode = False
                elif self.edit_mode:
                    self.edit_mode = False
                set_page()

        self.start_curses()

        if self.page == 'help':
            self.render_help_screen()
        elif self.page == 'edit':
            self.render_edit_report()
        else: # normal mode
            self.render_normal_report()

        delta_float = time.monotonic() - self.mono_start
        delta_int = int(round(delta_float))
        pause_secs = delta_int - delta_float # how early in secs
        if delta_int <= self.history.prev_info_mono:
            pause_secs += 1.0

        do_key(self.win.prompt(seconds=max(0.0, pause_secs)))

    def loop(self):
        """ The main loop for the program """
        while True:
            self.update_report_data()

            self.do_window()

memfo = None
def main():
    """ TBD """
    global memfo
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-u', '--units', choices=('KiB', 'MB', 'MiB', 'GB', 'GiB', 'human'),
            default='MiB', help='units of memory [dflt=MiB]')
    parser.add_argument('-c', '--config', type=str, default='memfo',
            help='use "{config}.ini" for configuration')
    parser.add_argument('-i', '--interval-sec', type=float, default=1.0,
            help='loop interval in seconds [dflt=1.0] ')
    parser.add_argument('--vmalloc-total', action="store_true",
            help='Show "VmallocTotal" row (which is mostly useless)')
    parser.add_argument('-z', '--zeros', action="store_true",
            help='Show lines with all zeros')
    opts = parser.parse_args()

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
