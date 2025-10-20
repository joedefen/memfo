#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time
import copy
import math
from typing import List, Dict, Any

# --- Assumed External Definitions ---
# The original code used global/class constants, so we redefine them here.
SAMPLE_SECS: int = 1
# Placeholder for the terminal size function, as shutil is not available in all contexts.
class ShutilMock:
    @staticmethod
    def get_terminal_size():
        # Mock terminal width and height
        return 80, 24 

shutil = ShutilMock

# --- The Refactored TimeMemory Class ---

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

    def __init__(self, sample_secs: int):
        # List of info objects, ALWAYS running backwards: [Newest Info, ..., Oldest Info]
        self.infos: List[Dict[str, Any]] = []
        self.info_secs = sample_secs
        self.info_base_num: int = 0
        self.comp_idx: int = 0

    def _get_info_nums(self, info: Dict[str, Any]) -> tuple[int, int]:
        """Calculates the discrete sample and bucket indices for a given info object."""
        info_sample_num = int(round(info['_mono']))
        info_num = info_sample_num // self.info_secs
        return info_sample_num, info_num

    def _append_info(self, info: Dict[str, Any]):
        """
        Adds the info object, filling gaps with synthetic data and managing
        fixed-size, adaptively compressed memory.
        """
        _, new_info_num = self._get_info_nums(info)

        # --- 1. Initialization (First Run) ---
        if not self.infos:
            self.infos.append(info)
            self.info_base_num = new_info_num
            self.comp_idx = 0
            return

        current_top_num = self.info_base_num + len(self.infos) - 1

        # --- 2. Update/Overwrite Check (Same bucket) ---
        if new_info_num == current_top_num:
            self.infos[0] = info
            return

        # --- 3. Stale Check (Older data) ---
        if new_info_num < current_top_num:
            print(f"[{time.time():.2f}] Warning: Received stale info_num {new_info_num}. Dropping.")
            return

        # --- 4. Insert New Info and Fill Gaps (new_info_num > current_top_num) ---
        missing_count = new_info_num - current_top_num - 1
        
        for i in range(missing_count):
            missing_num = current_top_num + i + 1
            synthetic_info = copy.deepcopy(self.infos[0])
            synthetic_info['_mono'] = float(missing_num * self.info_secs)
            self.infos.insert(0, synthetic_info)

        self.infos.insert(0, info)

        # --- 5. History Pruning (Fixed Time Retention) ---
        cutoff_time = info['_mono'] - self.RETENTION_SEC

        while self.infos and self.infos[-1]['_mono'] < cutoff_time:
            self.infos.pop()
            self.info_base_num += 1

        # --- 6. Unified Adaptive Compression (Capacity and Spacing) ---
        if len(self.infos) > self.MAX_INFOS:
            factor = self.COMPRESSION_MULTIPLIERS[self.comp_idx % len(self.COMPRESSION_MULTIPLIERS)]
            
            compressed_infos = [self.infos[i] for i in range(0, len(self.infos), factor)]

            old_info_secs = self.info_secs
            self.info_secs *= factor
            self.comp_idx += 1
            self.infos = compressed_infos

            old_base_sample_num = self.info_base_num * old_info_secs
            self.info_base_num = old_base_sample_num // self.info_secs


# --- The Reporting Application Logic ---

class TimeSlicer:
    def __init__(self, history):
        # Data storage using the new class
        self.history = history

        # Application State (Mocked)
        self.key_width = 10
        self.data_width = 5
        self.page = 'report' # Or 'edit'
        self.report_interval = '5s' # Current selected interval
        self.report_intervals = {'5s': 5, '1m': 60, '5m': 300, 'Var': 0}
        
        # Slicing State (Persisted)
        self.last_complete_sample_index = 0
        self.historical_slices = []
        self.prev_report_interval = self.report_interval
        self.term_width, _ = shutil.get_terminal_size()
        self.slices: List[Dict[str, Any]] = []

    def _read_info(self) -> Dict[str, Any]:
        """Mock function to simulate reading new data."""
        # Use a high resolution monotonic time for the unique timestamp key
        return {'_mono': time.monotonic(), 'cpu_load': math.sin(time.time() / 10) * 100, 'ts': time.time()}

    def get_var_slices(self, max_col_cnt: int) -> List[Dict[str, Any]]:
        """
        Variable Interval Display: Samples uniformly across the whole history.
        The historical_slices state is cleared in this mode.
        """
        total_history_count = len(self.history.infos)
        
        col_cnt = min(max_col_cnt, total_history_count)
        slices = []

        if total_history_count <= col_cnt:
            slices = self.history.infos
        else:
            # Slices must run from oldest (right) to newest (left).
            # The list runs: [Newest (0), ..., Oldest (N-1)]
            
            for cnt in range(col_cnt):
                if col_cnt == 1:
                    index = 0
                else:
                    # Index in the backwards array (0=newest, N=oldest)
                    index = int(round(cnt * (total_history_count - 1) / (col_cnt - 1)))
                
                slices.append(self.history.infos[index])
                
        # In Var mode, reset the stable state variables for Fixed mode
        self.last_complete_sample_index = 0
        self.historical_slices = []
        
        # Slices were collected backwards (index 0 is newest), so reverse them to get [Oldest...Newest].
        slices.reverse()
        
        # --- FINAL SLICE PREPARATION ---
        # Ensure the current/latest snapshot (index 0) is always the last item (rightmost column).
        if not slices or slices[-1] is not self.history.infos[0]:
            slices.append(self.history.infos[0]) # Add the newest, current sample

        return slices


    def _get_fixed_slices(self, interval_samples: int, max_col_cnt: int, is_mode_switch: bool) -> List[Dict[str, Any]]:
        """
        Fixed Interval Display: Uses state to only add a new stable column when 
        a full 'interval_samples' bucket has completed.
        """
        total_history_count = len(self.history.infos)
        
        # 1. Guard Check: Not enough samples to fill even one historical column
        if total_history_count < interval_samples:
            self.last_complete_sample_index = 0
            self.historical_slices = []
            
            # --- FINAL SLICE PREPARATION ---
            # If no historical slices, just return the current slice if available
            return [self.history.infos[0]] if self.history.infos else []

        # 2. Calculate the newest complete historical bucket index
        
        # The incomplete tail is the chunk at the very front (index 0) of the backwards array
        incomplete_tail_size = total_history_count % interval_samples

        if incomplete_tail_size == 0:
            # History is perfectly aligned. The last sample of the *previous* complete bucket is at index (interval_samples - 1).
            new_complete_index = interval_samples - 1
        else:
            # History is not aligned. The newest complete bucket ENDED at the index 
            # immediately following the incomplete tail.
            new_complete_index = incomplete_tail_size - 1

        # 3. Check for a full bucket completion (The "Split" Event)
        should_regenerate = is_mode_switch
        
        # If the mode just switched, reset anchor index to the newest possible
        if is_mode_switch:
            self.last_complete_sample_index = new_complete_index
            should_regenerate = True
        
        # The index must be greater to trigger regeneration
        elif new_complete_index > self.last_complete_sample_index:
            self.last_complete_sample_index = new_complete_index
            should_regenerate = True


        # 4. Regeneration
        if should_regenerate:
            
            historical_slices = []
            current_idx = self.last_complete_sample_index
            
            # We want max_col_cnt - 1 historical slices
            for _ in range(max_col_cnt - 1):
                
                if current_idx >= total_history_count or current_idx < 0:
                    break
                    
                historical_slices.append(self.history.infos[current_idx])
                current_idx += interval_samples # Move to the next older complete bucket
                
            historical_slices.reverse() # Reverse to get [Oldest...Newest Stable]
            self.historical_slices = historical_slices

        # 5. Use the stable historical slices for display
        slices = self.historical_slices[:]
        
        # --- FINAL SLICE PREPARATION ---
        # Ensure the current/latest snapshot (index 0) is always the last item (rightmost column).
        if self.history.infos and (not slices or slices[-1] is not self.history.infos[0]):
            slices.append(self.history.infos[0]) # Add the newest, current sample

        return slices


    def mock_update_report_data(self):
        """ 
        Mock function to update data and calculate the final display slices.
        (This will eventually be integrated into the main application loop.)
        """
        
        # ----------------------------------------------------------------------
        # 0. INITIALIZATION AND SETUP
        # ----------------------------------------------------------------------
        
        # 1. READ and APPEND New Data 
        info = self._read_info()
        self.history._append_info(info)

        # 2. CALCULATE Screen Constraints
        self.term_width, _ = shutil.get_terminal_size()
        cols_width = self.term_width - self.key_width
        
        if self.page == 'edit':
            cols_width -= 4 
            
        # Maximum number of columns that can physically fit on the screen
        max_col_cnt = max(1, cols_width // (1 + self.data_width))

        # 3. DETERMINE Interval Mode
        interval_sec = self.report_intervals.get(self.report_interval, 0)
        is_mode_switch = (self.prev_report_interval != self.report_interval)
        is_var_mode = (self.report_interval == 'Var' or interval_sec == 0)
        
        interval_samples = max(1, interval_sec) 
        
        self.prev_report_interval = self.report_interval # Update for next loop's check
        
        # ----------------------------------------------------------------------
        # B. DISPLAY LOGIC (Dispatching to Helper Methods)
        # ----------------------------------------------------------------------
        
        if is_var_mode:
            self.slices = self.get_var_slices(max_col_cnt)
        else:
            self.slices = self._get_fixed_slices(interval_samples, max_col_cnt, is_mode_switch)
            
        # ----------------------------------------------------------------------
        # C. RENDERING
        # ----------------------------------------------------------------------
        self.mock_render_slices()
        
    def mock_render_slices(self):
        """Mock function to simulate rendering the final slices."""
        print("-" * self.term_width)
        print(f"REPORT: Mode={self.report_interval}, MaxCols={len(self.slices)}")
        
        # Print the data from each slice
        for i, info in enumerate(self.slices):
            # The newest is always the last one (index -1)
            is_newest = (i == len(self.slices) - 1)
            
            # Since we don't have a reliable _faked key, we use a simple heuristic for mock output:
            # If the current sample is *not* the newest, and its CPU load is a copy of the newest's
            # (which happens when synthetic data is created), it's likely synthetic.
            is_synthetic = not is_newest and self.history.infos and (info.get('cpu_load') == self.history.infos[0].get('cpu_load')) and (info['_mono'] != self.history.infos[0]['_mono'])
            
            status = 'Current' if is_newest else ('Synthetic' if is_synthetic else 'Hist')
            print(f"Col {i}: Time={info['_mono']:.1f}, CPU={info.get('cpu_load', 0.0):.2f}, Status={status}")
        print("-" * self.term_width)

# --- Example Execution ---

if __name__ == '__main__':
    app = TimeSlicer()
    
    # 1. Initial Fixed Mode (5s interval)
    print("\n--- Initial Run: Fixed Mode (5s Interval) ---")
    app.report_interval = '5s'
    
    # Log 1-4: Not enough for one 5s bucket. Slices should be [Current].
    for _ in range(4): # t=1, 2, 3, 4
        app.mock_update_report_data() 

    # Log 5: Completes the first 5s bucket (index 0 to 4 is complete).
    app.mock_update_report_data() # t=5
    print("\n--- Split Event 1: First 5s Bucket Completed ---")
    # Now, the slices should be [Hist (t=4), Current (t=5)]

    # Log 6: Starts the second bucket (incomplete)
    app.mock_update_report_data() # t=6
    print("\n--- After 1s into Second 5s Bucket ---")
    # Slices should still be [Hist (t=4), Current (t=6)]

    # Log 10: Completes the second 5s bucket (index 5 to 9)
    for _ in range(7, 10):
        app.mock_update_report_data() # t=7, 8, 9
    app.mock_update_report_data() # t=10 (This triggers the next regeneration)
    print("\n--- Split Event 2: Second 5s Bucket Completed (Two Historical Columns) ---")
    # Historical slices should be [Hist (t=4), Hist (t=9), Current (t=10)]
    
    # 2. Mode Switch to Variable
    app.report_interval = 'Var'
    print("\n--- Mode Switch: Variable Mode ---")
    app.mock_update_report_data()
