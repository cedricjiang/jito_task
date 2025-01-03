# Jito Task: Identifying Atomic Arbitrage

## Files
- [jito.py](jito.py) is the Python code
- [jito.log](jito.log) is the log file for running the code - very large
- [jito.csv](jito.csv) is the generated arbitrage data in CSV format
- [jito.out](jito.out) is the output (stdout) of the program which includes summary statistics
- [jito.pdf](jito.pdf) is the writeup

## Usage
```
$ python3 jito.py --help
usage: jito.py [-h] [-b BEGIN_SLOT] [-e END_SLOT] [-l LOG_FILE] [-d DATA_FILE]
               [-t TOP]

options:
  -h, --help            show this help message and exit
  -b BEGIN_SLOT, --begin-slot BEGIN_SLOT
                        the beginning slot number (inclusive)
  -e END_SLOT, --end-slot END_SLOT
                        the end slot number (inclusive)
  -l LOG_FILE, --log-file LOG_FILE
                        the log file path
  -d DATA_FILE, --data-file DATA_FILE
                        the data (CSV) file path
  -t TOP, --top TOP     the number of top traders in statistics
```

You need to have `requests` module to run the program. All arguments above have default value (being/end slots are 308803801/308803900, top is 10, log and data files are jito.log and jito.csv)
