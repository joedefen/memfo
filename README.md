>**Quick Start**
* **On python 3.11+, install with**: `pipx upgraded memfo || pipx install memfo`
* **On python 3.8 to 3.10, install with**: `pip install --upgrade --user memfo`
* **After install, run**: `memfo` and enter `?` for help.
# memfo -- /proc/meminfo Viewer for Linux

`memfo` is a viewer for `/proc/meminfo` that shows meminfo:
* as a continuously updated display of current and past values,
* with numbers represented in chosen units,
* with selected fields at the top in the frozen section of the display,
* with the ability to hide certain fields, and
* more.

## Example memfo Output
```
u:MiB d:show-values z=show-if-zero e:enter-edit ?=help
        0s        10s        20s        28s        37s        47s 01/28 12:51:27
      +0.0       +0.0       +0.0       +0.0       +0.0   32,060.8 MemTotal
    +222.7     -106.9     -106.4     -103.4      -71.3   22,325.0 MemAvailable
──────────────────────────────────────────────────────────────────────────────────────
    +222.6     -106.6     -103.8     -101.1      -68.9   15,776.4 MemFree
      +0.0       +0.0       +0.0       +0.0       +0.0       93.6 Buffers
     -24.0       -0.3       -2.6       -2.2       -2.4    7,726.8 Cached
    -322.8      +14.5      +24.9      +22.9       -4.2    7,989.8 Active
      +0.1       -0.3       -2.6       -2.3       -2.4    5,464.2 Inactive
    -322.8      +14.5      +24.9      +22.9       -4.2    5,833.6 Active(anon)
```
NOTES:
* the columns are absolute or delta values for the given statistic for that interval; in this case, deltas are shown.
* the stats above the line can are chosen by the "edit" menu.

## Command Line Options
You selection of statistics to put in the non-scrolled region and hidden is saved a config file. If you choose another config file on start up, you can have set of statistics per for each use case.
```
$ memfo -h
usage: memfo [-h] [-u {KiB,MB,MiB,GB,GiB,human}] [-c CONFIG]
                [-i INTERVAL_SEC] [--vmalloc-total] [-z] [-d] [--DB]
options:
  -h, --help            show this help message and exit
  -u {KiB,MB,MiB,GB,GiB,human}, --units {KiB,MB,MiB,GB,GiB,human}
                        units of memory [dflt=MiB]
  -c CONFIG, --config CONFIG
                        use "{config}.ini" for configuration
  -i INTERVAL_SEC, --interval-sec INTERVAL_SEC
                        loop interval in seconds [dflt=1.0]
  --vmalloc-total       Show "VmallocTotal" row (which is mostly useless)
  -z, --zeros           Show lines with all zeros
  -d, --dump            "print" the data only once rather than "display" it
  --DB                  add some debugging output
```
