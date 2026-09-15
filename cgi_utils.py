#!/usr/bin/python3

import os
from urllib.parse import parse_qs


class QueryForm:
    """Parse the URL query string used by this application's GET forms."""

    def __init__(self, environ=None):
        if environ is None:
            environ = os.environ
        self._values = parse_qs(
            environ.get("QUERY_STRING", ""),
            keep_blank_values=True,
        )

    def getfirst(self, name, default=None):
        values = self._values.get(name)
        if not values:
            return default
        return values[0]

    def getvalue(self, name, default=None):
        return self.getfirst(name, default)
