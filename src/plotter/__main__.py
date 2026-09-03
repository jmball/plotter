#!/usr/bin/env python3

"""Run one of the live-data plotters with ``python -m plotter``."""

import argparse
import importlib
import sys


PLOTTER_MODULES = {
    "eqe": "plotter.eqe_plotter",
    "it": "plotter.it_plotter",
    "iv": "plotter.iv_plotter",
    "mppt": "plotter.mppt_plotter",
    "vt": "plotter.vt_plotter",
}


def main():
    """Select a plotter and pass remaining arguments to its existing CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plotter", choices=sorted(PLOTTER_MODULES))
    args = parser.parse_args(sys.argv[1:2])
    plotter_args = sys.argv[2:]

    module = importlib.import_module(PLOTTER_MODULES[args.plotter])
    sys.argv = [f"{args.plotter}-plotter", *plotter_args]
    module.main()


if __name__ == "__main__":
    main()
