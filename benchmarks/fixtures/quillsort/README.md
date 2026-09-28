# quillsort

Sort, dedupe and tidy the lines of any text file, from the command line.

quillsort is a single-file Python tool with no dependencies. It reads a file (or stdin),
sorts the lines, removes duplicates and writes the result to stdout or back in place.

## Install

```bash
pip install quillsort        # or copy quillsort.py anywhere on your PATH
```

## Use

```bash
quillsort names.txt                  # sorted, to stdout
quillsort names.txt --unique         # sorted, duplicates removed
quillsort names.txt --natural        # "file2" before "file10"
quillsort names.txt -i --unique      # rewrite the file in place
cat log.txt | quillsort --reverse    # works on stdin too
```

## Features

- Natural sort order (`--natural`): numbers inside lines compare as numbers.
- Case-insensitive mode (`--ignore-case`).
- Duplicate removal that keeps the first occurrence (`--unique`).
- In-place editing with an automatic `.bak` backup (`-i`).
- Blank-line trimming (`--strip-blank`).
- Python 3.8 or newer; no third-party packages.

## License

MIT
