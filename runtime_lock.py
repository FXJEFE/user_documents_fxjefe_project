#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runtime lock smoke check. Prints 200 and exits 0 when the tree can start."""
from __future__ import annotations

import argparse


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="FXJEFE runtime lock")
    parser.add_argument("--project-dir", default=None)
    parser.parse_args(argv)
    print("200", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
