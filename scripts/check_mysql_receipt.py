"""Require the full MySQL gate inventory with zero skips/failures/errors."""
import sys
import xml.etree.ElementTree as ET


def main():
    root = ET.parse(sys.argv[1]).getroot()
    cases = root.findall('.//testcase')
    bad = root.findall('.//skipped') + root.findall('.//failure') + root.findall('.//error')
    if len(cases) != 15 or bad:
        raise SystemExit('MySQL receipt refused: require 15 executed tests and zero skips/failures/errors')
    print('MySQL receipt: 15 tests, zero skips/failures/errors')


if __name__ == '__main__':
    main()
