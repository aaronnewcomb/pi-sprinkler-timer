#!/usr/bin/python3

"""Filesystem paths shared by the scheduler and CGI scripts."""

import os


APPLICATION_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.environ.get(
    "OPEN_SPRINKLER_CONFIG",
    os.path.join(APPLICATION_DIRECTORY, "sprinkler.config"),
)
