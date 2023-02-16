## v3.0.0 (2023-02-15)

This version pulls in some long overdue dependency updates and adds
support for the latest versions of Flask and Python.

- Supported Python versions: `3.7`, `3.8`, `3.9`, `3.10`, `3.11`.
- Supported Flask versions: `2.1`, `2.2`

This version also removes the capability to negotiate TLS over
gopher. The code for this was particularly annoying to monkey-patch,
and the feature never gained traction to make it worth maintaining.

- Removed the `make_gopher_ssl_server` function.
- Removed the following WSGI server classes:
  - ``GopherBaseWSGIServer``
  - ``GopherSimpleWSGIServer``
  - ``GopherThreadedWSGIServer``
  - ``GopherForkingWSGIServer``

### v2.2.1 (2020-04-11)

- Pin the werkzeug dependency to avoid breaking dependency changes.

### v2.2.0 (2020-01-11)

- Added support for python 3.8
- Dropped support for python 3.4
- Added support for flask 1.1
- Renamed the following methods:

  - ``menu.submenu()`` -> ``menu.dir()``
  - ``menu.file()`` -> ``menu.text()``
  - ``menu.binary()`` -> ``menu.bin()``

This was done as a personal preference because I found the original method
names to be overly verbose and hard to remember. The original methods will
remain for backwards compatibility, but they will no longer be listed in
the documentation.

### v2.1.1 (2019-04-10)

- Add a helper method to generate a gopher menu from a directory.
- Fixed bug when redirecting to HTTP pages that was causing query parameters
  to get lost.

### v2.1.0 (2019-01-08)

- Added support for establishing TLS connections with gopher clients. See the
  documentation for more details.

### v2.0.0 (2018-01-17)

- Major restructuring of the codebase and the public API.
- Added a ``TextFormatter`` class with several helper methods for formatting
  ASCII.
- Added a ``GopherSessionInterface`` class in order to support flask sessions.
- Added the ability to set the ``SERVER_NAME`` to an external URL.
- Included a ``demo/`` directory with a complete example gopher server.
- Several minor bug fixes and improvements.

### v1.0.0 (2018-01-07)

- First official release
