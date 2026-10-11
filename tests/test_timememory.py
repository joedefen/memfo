"""Invariant / characterization tests for TimeMemory and TimeSlicer.

These pin the intended behaviour of the history buffer (newest-first, no
duplicates, gap-free, bounded size) so the hole-filling and compression
logic can be safely refactored.

Run with:  .venv/bin/python -m pytest -q
"""
import pytest

from memfo.TimeMemory import TimeMemory, TimeSlicer


class DummyMemFo:
    """Minimal stand-in; TimeMemory/TimeSlicer only touch .dbinfo."""
    def __init__(self):
        self.dbinfo = ''


def _info(mono, value=None):
    return {'_mono': mono,
            '_time': 1_700_000_000 + mono,
            'MemTotal': mono if value is None else value}


def _monos(tm):
    return [i['_mono'] for i in tm.infos]


def _assert_invariants(tm):
    ms = _monos(tm)
    assert ms == sorted(ms, reverse=True), f'not newest-first: {ms}'
    assert len(ms) == len(set(ms)), f'duplicate monos: {ms}'
    assert len(ms) <= TimeMemory.MAX_INFOS, f'over capacity: {len(ms)}'


# --------------------------------------------------------------------------
# TimeMemory basics
# --------------------------------------------------------------------------

def test_first_append():
    tm = TimeMemory(DummyMemFo())
    assert tm.append_info(_info(0)) is False
    assert _monos(tm) == [0]
    _assert_invariants(tm)


def test_sequential_one_second_samples():
    tm = TimeMemory(DummyMemFo())
    for m in range(10):
        tm.append_info(_info(m))
    assert _monos(tm) == list(range(9, -1, -1))
    _assert_invariants(tm)


def test_same_mono_overwrites_newest():
    tm = TimeMemory(DummyMemFo())
    tm.append_info(_info(0, value=1))
    tm.append_info(_info(0, value=2))
    assert len(tm.infos) == 1
    assert tm.infos[0]['MemTotal'] == 2


def test_sample_in_past_is_ignored():
    tm = TimeMemory(DummyMemFo())
    tm.append_info(_info(5))
    tm.append_info(_info(3))
    assert _monos(tm) == [5]


def test_small_gap_is_filled():
    tm = TimeMemory(DummyMemFo())
    tm.append_info(_info(0))
    tm.append_info(_info(3))
    assert _monos(tm) == [3, 2, 1, 0]
    _assert_invariants(tm)


def test_large_gap_does_not_crash():
    """A long pause (e.g. suspend/resume) must not blow the recursion limit."""
    tm = TimeMemory(DummyMemFo())
    tm.append_info(_info(0))
    tm.append_info(_info(1500))          # > Python's default recursion limit
    _assert_invariants(tm)
    assert _monos(tm)[0] == 1500
    assert _monos(tm)[-1] == 0


def test_long_run_stays_bounded_and_uniform():
    tm = TimeMemory(DummyMemFo())
    for m in range(2000):
        tm.append_info(_info(m))
    _assert_invariants(tm)
    assert tm.info_secs >= 1

    ms = _monos(tm)
    # Every entry below the live head sits on the info_secs grid...
    assert all(x % tm.info_secs == 0 for x in ms[1:])
    if len(ms) > 2:
        steps = {ms[i] - ms[i + 1] for i in range(1, len(ms) - 1)}
        assert steps == {tm.info_secs}, f'non-uniform spacing: {steps}'
    # ...and the live head is the newest sample, within one bucket of it.
    assert ms[0] == 1999
    assert 0 < ms[0] - ms[1] <= tm.info_secs


def test_force_compression_grows_interval():
    tm = TimeMemory(DummyMemFo())
    for m in range(50):
        tm.append_info(_info(m))
    before = tm.info_secs
    assert tm.append_info(_info(50), force_compression=True) is True
    assert tm.info_secs > before


# --------------------------------------------------------------------------
# TimeSlicer
# --------------------------------------------------------------------------

def test_var_slices_cover_span_oldest_to_newest():
    tm = TimeMemory(DummyMemFo())
    for m in range(10):
        tm.append_info(_info(m))
    ts = TimeSlicer(tm)
    slices = ts.get_var_slices(4)
    assert len(slices) == 4
    assert slices[0]['_mono'] == 0
    assert slices[-1]['_mono'] == 9


def test_var_slices_fewer_samples_than_columns():
    tm = TimeMemory(DummyMemFo())
    for m in range(3):
        tm.append_info(_info(m))
    ts = TimeSlicer(tm)
    slices = ts.get_var_slices(10)
    assert [s['_mono'] for s in slices] == [0, 1, 2]


def test_fixed_slices_newest_is_live_sample():
    tm = TimeMemory(DummyMemFo())
    for m in range(20):
        tm.append_info(_info(m))
    ts = TimeSlicer(tm)
    slices = ts.get_fixed_slices(interval_secs=5, max_col_cnt=4,
                                 is_mode_switch=False)
    assert slices, 'expected at least one column'
    assert slices[-1]['_mono'] == 19
    assert slices[0]['_mono'] <= slices[-1]['_mono']


def test_fixed_slices_single_sample():
    tm = TimeMemory(DummyMemFo())
    tm.append_info(_info(0))
    ts = TimeSlicer(tm)
    slices = ts.get_fixed_slices(interval_secs=5, max_col_cnt=4,
                                 is_mode_switch=False)
    assert [s['_mono'] for s in slices] == [0]
