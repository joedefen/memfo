#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memfo is a viewer for /proc/meminfo
TODO:
- add [i]tvl=Var spiner values: Var, 30s, 1m, 5m, 15m, 1h, 4h
    - shows as many, say, 5m intervals as can fit on the screen (showing current last or rightmost)
    - if 5m not available, then it goes up to next option (silently)
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
import math
from datetime import datetime
from types import SimpleNamespace
from console_window import ConsoleWindow , OptionSpinner


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
        self.sample_secs = 1.0
        self.config_basename = opts.config

        self.units, self.divisor, self.data_width = opts.units, 0, 0
        self.delta = False # whether to show deltas
        self.win = None  # ConsoleWindow
        self.spin = None # Option Spinner
        self.page = 'normal' # or 'edit' or 'help'
        self.edit_mode = False # true in when editing
        self.help_mode = False # true in when in help screen
        self.report_interval = 'Var'  # column interval
        self.infos = []
        self.slices = []  # combined infos
        self.last_bucket_end_time = None
        self.historical_slices = None
        self.prev_report_interval = None
        self.report_anchor_mono_time = None
        self.last_processed_bucket_end = None
        self.comp_idx = 0  # tracks factor to use when squeezing memory
        self.loops_per_info = 1
        self.loops_fro_store = 0
        self.term_width = 0 # how wide is the terminal
        self.report_intervals = {'Var': 0, '5s': 5, '15s': 15,
                                '30s': 30, '1m': 60, '5m': 300,
                                '15m': 900, '1hr': 3600}

        self.key_width = None
        self.data_width = None
        self.report_rows = None # the stuff to display
        self._set_units()

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

    def render_slices(self):
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
        if self.page == 'normal':
            text = f'[u]nits:{self.units} [i]tvl={self.report_interval} [d]eltas:{delta} zeros={zeros} [e]dit ?=help'
        else:
            text = ('EDIT SCREEN:  e,ENTER:return'
                    + ' *:put-on-top -:hide-line [r]eset-line [R]reset-all-lines  ?=help')
        add_row(key='_lead', text=text)

        for ii, info in enumerate(self.slices):
            for key in list(info.keys())[:count]:
                if key == '_mono':
                    ago = f'{ago_str(info["_mono"]-self.mono_start)}'
                    text = f'{ago:>{self.data_width}}'
                    if ii == len(self.slices)-1:
                        time_str = datetime.now().strftime("%m/%d %H:%M:%S")
                        text += f' {time_str}'
                else:
                    val = info[key]
                    if ii < len(self.slices)-1 and self.delta:
                        next_val = self.slices[ii+1][key]
                        text = self.render(next_val-val, sign=True)
                    else:
                        text = self.render(val)
                # now add the text of the file to the text of the line
                if key in rows:
                    rows[key].text += ' ' + text
                elif key.startswith('_') or key in self.non_zeros:
                    add_row(key, text)
                else:
                    peak = max([info[key] for info in self.slices])
                    add_row(key, text, zero=bool(peak==0))
        self.report_rows = rows

    def _append_info(self, info):
        """ Add and compress memory with fixed time retention and unified
            physical/logical compression for uniform sample spacing.
        """
        # Configuration Constants
        MAX_INFOS = 600  # Target number of intervals (divisible by 2, 3, 5)
        COMPRESSION_MULTIPLIERS = [5, 3, 2, 2, 5, 3, 2, 2, 4, 3, 2, 2, 2, 2]
          # 5s, 15s, 30s, 1m, 5m, 15m, 30m, 1h, 4h, 12h, 1d, 2d, 4d, 8d
        RETENTION_SEC = 24 * 60 * 60  # 24 hours of retention

        # --- 1. Initial Storage / Overwrite ---
        if not self.infos:
            self.infos.append(info)
            self.loops_fro_store = 0
            self.loops_per_info = 1
            self.comp_idx = 0
            return

        self.loops_fro_store += 1
        if self.loops_fro_store < self.loops_per_info:
            # Overwrite the latest snapshot to keep the most recent data fresh
            self.infos[-1] = info
            return

        # --- 2. Store New Info (Bucket Close) ---
        # Re-incorporated Fuzzy Close Logic:
        # Check if enough time has actually passed to warrant closing the bucket.
        if len(self.infos) >= 2:
            # Floor is set to 95% of the expected time for this bucket interval
            floor_s = self.sample_secs * self.loops_per_info * 0.95
            delta_s = info['_mono'] - self.infos[-2]['_mono']

            if delta_s < floor_s:
                # Time says we should not close the bucket yet (too short)
                self.loops_fro_store -= 1
                self.infos[-1] = info # Still update the last entry
                return

        # If enough time has passed (or it's been here too long), store the new, permanent snapshot
        self.infos.append(info)
        self.loops_fro_store = 0

        # --- 3. History Pruning (Fixed Time Retention) ---
        # Remove snapshots older than the retention limit
        cutoff_time = info['_mono'] - RETENTION_SEC
        while len(self.infos) > MAX_INFOS and self.infos[0]['_mono'] < cutoff_time:
            self.infos.pop(0)

        # --- 4. Unified Adaptive Compression (Capacity and Spacing) ---
        # Compress if we are nearing the target capacity
        if len(self.infos) > MAX_INFOS:

            # Determine the compression factor for this step
            factor = COMPRESSION_MULTIPLIERS[self.comp_idx % len(COMPRESSION_MULTIPLIERS)]

            # A. Physical Compression: Drops 1/factor of entries, maintaining uniform spacing.
            self.infos = [self.infos[i] for i in range(0, len(self.infos), factor)]

            # B. Logical Coarsening: Sets the new, wider time interval for future samples.
            self.loops_per_info *= factor
            self.comp_idx += 1

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
        """ Get new data and report on it, sampling history based on sample count 
            (fixed interval) or adaptive logic (Var).
        """
        
        # ----------------------------------------------------------------------
        # 0. INITIALIZATION AND SETUP
        # ----------------------------------------------------------------------
        
        # Initialize stable state variables (must persist across loops)
        if not hasattr(self, 'last_complete_sample_index'):
            self.last_complete_sample_index = 0
        if not hasattr(self, 'prev_report_interval'):
            self.prev_report_interval = self.report_interval 
        if not hasattr(self, 'historical_slices'):
            self.historical_slices = []

        # 1. READ and APPEND New Data
        info = self._read_info()
        self._append_info(info)

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
        interval_sec = self.report_intervals.get(self.report_interval, 0)
        is_mode_switch = (self.prev_report_interval != self.report_interval)
        is_var_mode = (self.report_interval == 'Var' or interval_sec == 0)
        
        # Number of samples (which equals interval_sec if sampling is 1s per loop)
        interval_samples = max(1, interval_sec) 
        
        # Total number of available samples
        total_history_count = len(self.infos)
        
        self.prev_report_interval = self.report_interval # Update for next loop's check
        
        # ----------------------------------------------------------------------
        # B. DISPLAY LOGIC (Var vs. Fixed)
        # ----------------------------------------------------------------------
        
        slices = []

        if is_var_mode:
            # --- Variable Interval Display (Existing Adaptive Logic) ---
            
            col_cnt = min(max_col_cnt, total_history_count)

            if total_history_count <= col_cnt:
                slices = self.infos
            else:
                for cnt in range(col_cnt - 1):
                    position = int(round(cnt * (total_history_count - 1) / (col_cnt - 1)))
                    slices.append(self.infos[position])
                slices.append(self.infos[-1]) 
            
            # In Var mode, reset the stable state variables
            self.last_complete_sample_index = 0
            self.historical_slices = []
        else:
            # --- Fixed Interval Display (Sample Indexing Logic) ---
            
            # Guard Check: If we don't have enough samples for even one historical column, 
            # do NOT calculate new_complete_index. The historical_slices must remain empty.
            if total_history_count < interval_samples:
                self.last_complete_sample_index = 0
                self.historical_slices = []
                slices = [] # Ensure slices is empty for the next step, only current sample will be added.
            else:
                # If mode switched, reset the anchor index
                if is_mode_switch:
                     self.last_complete_sample_index = 0 
                     
                # --- Calculate the index of the newest complete historical bucket ---
                
                # Calculate how many samples are in the current, incomplete 'tail'
                incomplete_tail_size = total_history_count % interval_samples

                # Determine the index of the newest complete historical bucket
                
                if incomplete_tail_size == 0:
                    # History is perfectly aligned. We want the index of the 
                    # last sample of the *previous* complete bucket.
                    new_complete_index = max(0, total_history_count - interval_samples - 1)
                else:
                    # History is not aligned. We retreat by the size of the incomplete tail.
                    new_complete_index = max(0, total_history_count - incomplete_tail_size - 1)
                
                # 1. Check for a full bucket completion (The "Split" Event)
                should_regenerate = is_mode_switch
                
                if new_complete_index > self.last_complete_sample_index:
                    # A new bucket has completed, we must regenerate the stable columns.
                    self.last_complete_sample_index = new_complete_index
                    should_regenerate = True

                # 2. Regeneration
                if should_regenerate:
                    
                    historical_slices = []
                    current_idx = self.last_complete_sample_index
                    
                    # We want max_col_cnt - 1 historical slices
                    for _ in range(max_col_cnt - 1):
                        
                        if current_idx < 0 or current_idx >= total_history_count:
                            break
                            
                        historical_slices.append(self.infos[current_idx])
                        current_idx -= interval_samples
                    
                    historical_slices.reverse()
                    self.historical_slices = historical_slices 

                # 3. Use the stable historical slices for display
                slices = self.historical_slices[:]

        # ----------------------------------------------------------------------
        # C. FINAL SLICE PREPARATION AND RENDERING
        # ----------------------------------------------------------------------

        # Ensure the current/latest snapshot is always the last item (rightmost column).
        if not slices or slices[-1] is not self.infos[-1]:
            slices.append(self.infos[-1])

        self.slices = slices 
        self.render_slices()

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
            if row.key.startswith('_'):
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

            elif key in (ord('*'), ord('-'), ord('r'), ord('R') ):
                if self.page in ('edit', ):
                    row = list(self.report_rows.values())[self.win.pick_pos+2]
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
        do_key(self.win.prompt(seconds=self.sample_secs))

    def loop(self):
        """ The main loop for the program """
        while True:
            self.update_report_data()

            if self.dump:
                texts = [f'{row.text} {row.key}' for row in self.report_rows.values()
                         if not row.key.startswith('_')]
                print('\n' + '\n'.join(texts) + '\n')
                if self.DB:
                    print([ago_str(info['_mono']-self.mono_start) for info in self.slices])
                time.sleep(self.sample_secs)
                break
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
    parser.add_argument('-d', '--dump', action="store_true",
            help='"print" the data only once rather than "display" it')
    parser.add_argument('--DB', action="store_true",
            help='add some debugging output')
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
