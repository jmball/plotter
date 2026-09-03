"""Command-line validators shared by live plotters."""

import argparse


def positive_integer(value):
    """Parse a strictly positive integer."""
    integer = int(value)
    if integer <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return integer


def valid_port(value):
    """Parse a valid TCP port."""
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("must be between 1 and 65535")
    return port
