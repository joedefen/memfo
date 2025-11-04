>**Quick Start**
>* **On python 3.11+, install with**: `pipx upgraded memfo || pipx install memfo`
>* **On python 3.8 to 3.10, install with**: `pip install --upgrade --user memfo`
>* **After install, run**: `memfo` and enter `?` for help.

# memfo: Memory Footprint Observer

An efficient, real-time Linux memory monitoring tool built in Python.

`memfo` provides a low-overhead, stable, and highly customizable view of your system's `/proc/meminfo` data, designed for both short-term and long-term monitoring and performance debugging.

## Features at a Glance

`memfo` is a viewer for `/proc/meminfo` that shows its data:
* as a continuously updated display of current and past values,
* with numbers represented in chosen units as absolute or delta values,
* in chosen time intervals,
* with selected fields at the top in the frozen section of the display,
* with the ability to hide certain fields, and
* more.

Also, it features:
* Fixed-Interval Stability: Unlike standard tools, `memfo` offers a stable, fixed-interval sliding window display (e.g., 5s buckets). Historical columns remain fixed until a new interval is fully completed, eliminating the frustrating visual "drift" common in adaptive monitoring tools.
* Adaptive History Mode ('Var'): Automatically samples the entire history buffer, distributing samples evenly across the display columns for a high-level overview.
* Minimal Overhead: Consumes less than 1% CPU and minimal memory, making it ideal for monitoring resource-constrained environments or performance-sensitive applications.
* Data Flexibility: Switch units instantly (MiB, KiB, GiB), toggle between absolute values and per-second deltas, and hide zero values.
* Full History Dump: Easily export the entire accumulated history (up to 600 samples cover the last 24 hours at most).

Additionally, `memfod` is a utility script that starts `memfo` in a `tmux` session if not already running, and then attaches to the new or preexisting session. Run `memfod help` to see its arguments, but normally, just run it w/o arguments.

## Example memfo Output
```
[u]nits:MiB [i]tvl=15s [d]eltas:off zeros=off Dump [c]lock [e]dit ?=help
        0s        15s        30s        35s 10/20 22:44:08
   7,813.4    7,813.4    7,813.4    7,813.4 MemTotal
   1,344.1    1,318.9    1,306.6    1,335.2 MemAvailable
─────────────────────────────────────────────────────────────────
     418.6      385.1      356.9      385.2 MemFree
       0.0        0.0        0.0        0.0 Buffers
   2,153.7    2,151.2    2,155.1    2,155.3 Cached
       7.9        7.9        7.9        7.9 SwapCached
```
NOTES:
* the columns are absolute or delta values for the given statistic for that interval; in this case, absolute values are shown.
* the non-scrolling stats above the line are chosen by the "edit" menu.
* in this example, the fourth column (35s) is the current, live, and incomplete interval, while the preceding columns represent full 15s buckets.

Interaction keys:
* `i`	- Interval control.	Cycles reporting interval (Var, 5s, 15s, 30s, 1m, 5m, 15m, 1h). Var means to fit the full time span of the data.
* `u` -	Units control.	Cycles display units between MiB, KiB, and GiB.
* `d` - Deltas control.	Toggles the display between absolute values and changes of the values.
* `z`	- Zeros control. Toggles display of stat lines where the value is zero (helps focus on active metrics).
* `e` - Edit Mode.	Allows nailing to top or hiding specific memory fields.
* `D`	- Dump History.	Exports all historical samples to `/tmp/memfo.csv` for analysis.
* `c`	- clock mode.	Shows clock as monotonic time since start of run, wall clock, or both.
* `q` -	Quit. Exits the program.
* `?`	- Help. Displays the help text.
* `<` `>` - Horizontally, shift columns left/right by 1.
* `{` `}` - Horizontally, shift columns left/right by about 1/8 of the time span of the data.
* `[` `]` - Horizontally, shift columns to the beginning / end of the data.
## Command Line Options
Your selection of statistics to put in the non-scrolled region and hidden is saved a config file. If you choose another config file on start up, you can have set of statistics per for each use case.
```
usage: memfo [-h] [-u {KiB,MB,MiB,GB,GiB,human}] [-i {Var,5s,15s,30s,1m,5m,15m,1hr}] [-d] [-c CONFIG]
             [--vmalloc-total] [-z]

options:
  -h, --help            show this help message and exit
  -u {KiB,MB,MiB,GB,GiB,human}, --units {KiB,MB,MiB,GB,GiB,human}
                        units of memory [dflt=MiB]
  -i {Var,5s,15s,30s,1m,5m,15m,1hr}, --report-interval {Var,5s,15s,30s,1m,5m,15m,1hr}
                        report interval [dflt=Var]
  -d, --show-deltas     show differences in columns rather than absolute values
  -c CONFIG, --config CONFIG
                        use "{config}.ini" for configuration
  --vmalloc-total       Show "VmallocTotal" row (which is mostly useless)
  -z, --zeros           Show lines with all zeros

```

## About Horizontal Scrolling
After the program has been running a while (and there are enough columns), then horizontal scrolling is available.  When you scroll left (or back in time), only the last column updates, and the first columns will have reverse video times to indicate they are scrolled.  Those columns will be fixed until their data is removed or compressed in a way that affects them.

## About memfod (i.e., Daemon mode)
`memfod` runs `memfo` in a named, special `tmux` session aimed to keep that one version of `memfo` running until you shut it down.  This feature requires:
* that you install `tmux` (e.g., on Debian-based distros, `sudo apt intall tmux`)
* that you configure `tmux` to outlive logging out (e.g., on `systemd` distros, run `sudo loginctl enable-linger {username}`).

Normally, just use `memfod` but it can take one command argument:
* `start` - start `memfo` in the special tmux session w/o attaching
* `stop` - stop `memfo` running the special tmux session
* `restart` - start `memfo` running the special tmux session after stopping it
* `status` - show whether `memfo` is running the special tmux session
* `attach` - attach to the `memfo` running the special tmux session, starting if not running.

You could use `start` to arrange for `memfod` to start on reboot using `cron` if desired.
