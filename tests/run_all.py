#!/usr/bin/env python
"""Run every headless test suite in this directory with one command.

Discovers tests/headless_*.py, runs each as a subprocess of the CURRENT
interpreter (so invoke this with the Anki venv python:
<anki-venv>/bin/python
tests/run_all.py), prints per-file pass/fail, and exits nonzero if any
suite fails. Intended for the weekly health check.
"""

import glob
import os
import subprocess
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    suites = sorted(glob.glob(os.path.join(TESTS_DIR, 'headless_*.py')))
    if not suites:
        print('run_all: no tests/headless_*.py suites found in {}'.format(TESTS_DIR))
        return 1

    results = []
    for path in suites:
        name = os.path.basename(path)
        print('=== {} ==='.format(name), flush=True)
        proc = subprocess.run([sys.executable, path])
        results.append((name, proc.returncode))
        print(flush=True)

    print('=== run_all summary ===')
    failures = 0
    for name, returncode in results:
        if returncode == 0:
            print('PASS  {}'.format(name))
        else:
            failures += 1
            print('FAIL  {} (exit {})'.format(name, returncode))
    print('{}/{} suites passed'.format(len(results) - failures, len(results)))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
