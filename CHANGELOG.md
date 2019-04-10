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
