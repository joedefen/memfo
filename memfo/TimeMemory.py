#!/usr/bin/env python3
# -*- coding: utf-8 -*-
""" Encapsulates
    - TimeMemory - storing samples
    - TimeSlicer - selecting samples for display
"""
# pylint: disable=line-too-long,invalid-name,too-few-public-methods
import copy
from typing import List, Dict, Any

# --- The TimeMemory Class ---

class TimeMemory:
    """
    Manages a time-series history using discrete sample indices and adaptive
    compression, ensuring the 'infos' list is always complete (no missing gaps)
    and runs backwards (newest at index 0). 
    """

    # Configuration Constants
    MAX_INFOS: int = 600
    COMPRESSION_MULTIPLIERS: List[int] = [5, 3, 2, 2, 5, 3, 2, 2, 4, 3, 2, 2, 2, 2]
    RETENTION_SEC: int = 24 * 60 * 60

    def __init__(self, initial_sample_secs: int=1):
        # List of info objects, ALWAYS running backwards: [Newest Info, ..., Oldest Info]
        self.infos: List[Dict[str, Any]] = []
        self.info_secs = initial_sample_secs
        self.info_base_num: int = 0
        self.comp_idx: int = 0
        self.prev_info_mono = 0
        self.state = 'n/a'

    def append_info(self, info: Dict[str, Any], force_compression=False):
        """
        Adds the info object, filling gaps with synthetic data and managing
        fixed-size, adaptively compressed memory.

        Returns whether compressed
        """
        def get_fake_info(info, mono):
            fake_info = copy.deepcopy(info)
            fake_info['_mono'] = mono
            return fake_info

        # --- 1. Initialization (First Run) ---
        if not self.infos:
            self.infos.append(info)
            self.comp_idx = 0
            self.state = 'init'
            return False # not compressed

        # --- 2. In past (should not happen)
        this_mono = info['_mono']
        top_mono = self.infos[0]['_mono']
        if this_mono < top_mono:
            self.state = 'in-past'
            return False # not compressed

        # --- 3. Update/Overwrite Check (Same bucket) ---
        if this_mono == top_mono:
            self.infos[0] = info
            self.state = 'reuse'
            return False # not compressed

        hole = ''

        # --- 4. Hole Check (fill if needed) ---
        while this_mono > top_mono + 1:
            hole = self.state = 'hole-'
            top_mono += 1 # next missing mono
            if top_mono % self.info_secs != 0:
                self.infos[0]['_mono'] = top_mono
            else:
                self.append_info(get_fake_info(info, top_mono))

        # --- 5. Overwrite situation ---
        if top_mono % self.info_secs != 0:
            self.infos[0] = info
            self.state = f'{hole}reuse'
            return False # not compressed

        # --- 5. Insert situation (and this_mono == top_mono+1) ---
        self.state = f'{hole}grow'
        self.infos.insert(0, info)

        # --- 6. History Pruning (Fixed Time Retention) ---
        cutoff_time = info['_mono'] - self.RETENTION_SEC
        while len(self.infos) > self.MAX_INFOS and self.infos:
            if self.infos[-1]['_mono'] < cutoff_time:
                del self.infos[-1]

        # --- 7. Unified Adaptive Compression (Capacity and Spacing) ---
        if len(self.infos) > self.MAX_INFOS or force_compression:
            factor = self.COMPRESSION_MULTIPLIERS[self.comp_idx % len(self.COMPRESSION_MULTIPLIERS)]
            self.info_secs *= factor
            compressed_infos = [info for info in self.infos[1:] if info['_mono'] % self.info_secs == 0]
            self.infos = self.infos[:1] + compressed_infos
            self.comp_idx += 1
            return True

        return False # not compressed


# --- The TimeSlicer Logic ---

class TimeSlicer:
    """ Class for choosing samples for the few columns that are displayed """
    def __init__(self, history):
        # Data storage using the new class
        self.history = history
        # index of the last sample of the stable data columns
        self.stable_sample_mono = None

        # Slicing State (Persisted)
        self.last_complete_sample_index = 0
        self.slices: List[Dict[str, Any]] = []

    def get_var_slices(self, max_col_cnt: int) -> List[Dict[str, Any]]:
        """
        Variable Interval Display: Samples uniformly across the whole history.
        """
        infos = self.history.infos # shorthand
        total_history_count = len(infos)
        slices = []

        if total_history_count <= max_col_cnt:
            for info in infos:
                slices.append(info)
        else:
            where, spread = 0, (total_history_count-1) / (max_col_cnt-1)
            # Slices must run from newest (0) to oldest (N-1) for sampling.
            for _ in range(max_col_cnt):
                index = int(round(where))
                slices.append(infos[index])
                where += spread

        # Slices were collected backwards (index 0 is newest), so reverse them to get [Oldest...Newest].
        slices.reverse()
        return slices


    def get_fixed_slices(self, interval_secs: int, max_col_cnt: int,
                         is_mode_switch: bool) -> List[Dict[str, Any]]:
        """
        Fixed Interval Display: Uses state to hold columns stable. The last column
        is always the "live" current sample. Historical columns only change when
        a full bucket completes (shift) or the screen size changes (regenerate).
        """
        infos = self.history.infos # short hand
        total_history_count = len(infos)
        # number of samples in interval
        interval_samples = interval_secs // self.history.info_secs
        if is_mode_switch:
            self.stable_sample_mono = None

        # 1. Guard Check ... if there is only one column return it
        if total_history_count < interval_samples:
            self.last_complete_sample_index = 0

            # --- FINAL SLICE PREPARATION ---
            return [infos[0]] if infos else []

        # find the stable point sample of the last "fixed" column (i.e., the one
        # before the current column)
        stable_sample_idx = len(infos)-1
        if self.stable_sample_mono is not None:
            for idx, info in enumerate(infos):
                if self.stable_sample_mono >= info['_mono']:
                    stable_sample_idx = idx
                    break
        # shift stable_sample_idx to newest short of current
        stable_sample_idx = stable_sample_idx % interval_samples
        if stable_sample_idx == 0:
            stable_sample_idx += interval_samples
        self.stable_sample_mono = infos[stable_sample_idx]['_mono']

        # create the slices going backwards from our stable index
        # until we run out or need no more
        slices = []
        current_idx = stable_sample_idx
        for _ in range(max_col_cnt-1):
            if current_idx >= total_history_count or current_idx < 0:
                break
            slices.append(infos[current_idx])
            current_idx += interval_samples # Move to the next older complete bucket

        slices.reverse() # Reverse to get [Oldest...Newest Stable]
        slices.append(infos[0]) # Add the newest, current sample

        return slices
