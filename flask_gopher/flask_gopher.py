import re
import weakref
import textwrap
from functools import partialmethod, wraps

from flask import request, make_response, render_template, current_app, url_for
from flask import _app_ctx_stack as stack
from werkzeug.urls import url_quote
from werkzeug.serving import WSGIRequestHandler
from werkzeug.exceptions import HTTPException
from .__version__ import __version__


def _add_menu_func(method):
    """
    Helper wrapper to add GopherMenu methods to the Gopher class.
    """
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        return method(self.menu, *args, **kwargs)
    return wrapped


class GopherMenu(object):
    """
    This class handles text formatting for Gopher menu lines.

    A menu item (type 1) has the following format:
        T<itemtext><TAB><selector><TAB><host><TAB><port><CR><LF>

    Where:
        - `T` is the type code, which MUST be run together with the item text
        - <selector> is the selector string to send to the specified server
        - <host> is the server to send the selector to
        - <port> is the port on the server to connect to

    This gopher implementation supports the following subset of type
    codes defined by RPC 1436, Gopher II, and Gophernicus. Some of less common
    types have been omitted for simplicity (or because I don't understand what
    they mean).

        Type    Treat As    Meaning
        0       TEXT        Plain text file
        1       MENU        Gopher submenu
        2       EXTERNAL    CCSO flat database; other databases
        3       ERROR       Error message
        4       TEXT        Macintosh BinHex file
        5       BINARY      Archive file (zip, tar, gzip, etc)
        6       TEXT        UUEncoded file
        7       INDEX       Search query
        8       EXTERNAL    Telnet session
        9       BINARY      Binary file
        g       BINARY      GIF format graphics file
        I       BINARY      Image file
        d       BINARY      Word processing document (ps, pdf, doc, etc)
        s       BINARY      Sound file
        ;       BINARY      Video file
        h       TEXT        HTML document
        i       -           Info line

    Additional types are listed here for completeness, and may be added later:

        Type    Treat As    Meaning
        +       -           Redundant server
        T       EXTERNAL    Telnet to: tn3270 series server
        M       TEXT        MIME file (mbox, emails, etc)
        c       BINARY      Calendar file
    """

    TEMPLATE = '{}{:<1}\t{}\t{}\t{}'

    def __init__(self, default_host='127.0.0.1', default_port=70):
        self.default_host = default_host
        self.default_port = default_port

    def entry(self, type_code, text, selector='/', host=None, port=None):
        host = host if host is not None else self.default_host
        if port is None:
            if host == self.default_host:
                # Internal link, use the server's port
                port = self.default_port
            else:
                # External link, use the default gopher port
                port = 70

        # Strip any newline or tab characters from the components, these would
        # result in a corrupted menu line
        table = str.maketrans('', '', '\n\r\t')

        text = str(text).translate(table)
        selector = str(selector).translate(table)
        host = str(host).translate(table)
        port = str(port).translate(table)

        return self.TEMPLATE.format(type_code, text, selector, host, port)

    # Most of the selectors follow the same standard format
    file = partialmethod(entry, '0')
    submenu = partialmethod(entry, '1')
    ccso = partialmethod(entry, '2')
    binhex = partialmethod(entry, '4')
    archive = partialmethod(entry, '5')
    uuencoded = partialmethod(entry, '6')
    query = partialmethod(entry, '7')
    telnet = partialmethod(entry, '8')
    binary = partialmethod(entry, '9')
    gif = partialmethod(entry, 'g')
    image = partialmethod(entry, 'I')
    doc = partialmethod(entry, 'd')
    sound = partialmethod(entry, 's')
    video = partialmethod(entry, ';')

    # info has special placeholder values for the host/port
    info = partialmethod(entry, 'i', selector='fake', host='example.com', port=0)

    def html(self, text, url):
        """
        A Gopher `URL:` selector MUST take the following format:

        h<itemtext>^IURL:<address>^I<localhost>^I<localport>

        `URL:` selectors are, for the most part, identical to standard HTML
        selectors, but composed of particular data:

          - The item type corresponds to the type of document on the remote
            end. Most typically, this is a Web page authored in HTML;
            therefore, the item type is most commonly `h`.
          - <itemtext> is the text of the link; this can be almost anything.
          - <address> is the full URL, preceded by the string `URL:`. For
            example, this could be `URL:http://www.example.com`
          - <localhost> is the server that the link *originated* from; this
            MUST be ignored by a compliant client, but MUST also be sent by
            a compliant server
          - <localport> is the port that the link *originated* from; this MUST
            be ignored by a compliant client, but MUST also be sent by a
            compliant server
        """
        return self.entry('h', text, 'URL:' + url, None, None)

    def title(self, text):
        """
        A Gopher TITLE resource has the following format:

        i<titletext>^ITITLE^Iexample.com^I0

        It is identical to a normal informational resource (itemtype `i`); the
        selector string, however, is set to the specific value, `TITLE`.

        The composition of the above format is as follows:

          - `^I` is the ASCII character corresponding to a press of the `Tab` key
          - The type code MUST be `i` (information)
          - The selector string MUST be `TITLE`
          - There is no server to connect to; the dummy text used in place of
            the server SHOULD be `example.com`
          - There is no port to connect to; the placeholder number SHOULD
            therefore be `0` (zero).
        """
        return self.entry('i', text, 'TITLE', 'example.com', 0)

    def error(self, error_code, message):
        """
        When an error is encountered, the server MUST return a menu whose
        first item bears itemtype `3`. All other ways of signalling an error,
        such as redirecting to a Gopher error menu, an image, or (worst of
        all) an HTML page, are PROHIBITED.

        The selector string for itemtype `3` is the text of the error. It is
        the responsibility of the server application to have understandable
        and accurate strings for error handling. As they are well-understood
        and common, HTTP-style error codes are acceptable and RECOMMENDED;
        however, they SHOULD also be followed by a clear, legible description
        of the error in both English and the local language.
        """

        # This doesn't seem to work in Lynx, so I'm using a plain text message
        # return self.entry('3', error_code, message, 'example.com', 0)
        return 'Error: {} {}'.format(error_code, message)


class GopherExtension:

    # https://tools.ietf.org/id/draft-matavka-gopher-ii-03.html#rfc.section.11
    URL_REDIRECT_TEMPLATE = """
    <HTML>
    <HEAD>
    <META HTTP-EQUIV="refresh" content="2;URL={url}"> 
    </HEAD>
    <BODY>

    You are following an external link to a Web site. You will be automatically
    taken to the site shortly. If you do not get sent there, please click
    <A HREF="{url}">here</A> to go to the web site. 
    <P> 
    The URL linked is:{url}> 
    <P> 
    <A HREF="{url}">{url}</A> 
    <P> 
    Thanks for using Gopher! 
    </BODY> 
    </HTML>
    """

    def __init__(self, app=None):
        self.width = None
        self.text_wrap = None

        self.app = app
        if app is not None:
            self._init_app(app)

    def _init_app(self, app):
        self.width = app.config.setdefault('GOPHER_WIDTH', 70)
        self.text_wrap = textwrap.TextWrapper(self.width)

        app.jinja_env.trim_blocks = True
        app.jinja_env.lstrip_blocks = False

        self._add_gopher_jinja_methods(app)
        self._add_gopher_url_redirect(app)
        self._add_gopher_error_handler(app)

        app.extensions['gopher'] = weakref.proxy(self)

    def _add_gopher_jinja_methods(self, app):
        """
        Make this class object accessible to the jinja template engine.
        """
        @app.context_processor
        def add_context():
            return {'gopher': self}

        app.add_template_filter(lambda s: s.rjust(self.width), 'rjust')
        app.add_template_filter(lambda s: s.center(self.width), 'center')

    def _add_gopher_url_redirect(self, app):
        """
        When a Gopher server receives a request from a client beginning with
        the string `URL:`, it SHALL write out an HTML document that redirects
        the browser to the appropriate place.

        From what I understand, this should be a bare text response
        (i.e. no HTTP status line).
        """
        @app.route('/URL:<path:url>')
        def gopher_url_redirect(url):
            url = url_quote(url)
            return self.URL_REDIRECT_TEMPLATE.format(url=url).strip()

    def _add_gopher_error_handler(self, app):
        """
        Intercept all errors for GOPHER requests and replace the default
        HTML document with a gopher compatible menu document.
        """

        # https://stackoverflow.com/a/41655397
        def handle_error(error):
            if request.scheme == 'gopher':
                if isinstance(error, HTTPException):
                    body = [self.error(error.code, error.name), '']
                    body += self.text_wrap.wrap(error.description)
                    return self.render_menu(*body), error.code
                else:
                    body = self.menu.error(500, 'Internal Error')
                    return self.render_menu(body), 500
            return error

        for cls in HTTPException.__subclasses__():
            app.register_error_handler(cls, handle_error)

    @property
    def menu(self):
        ctx = stack.top
        if ctx is not None:
            if not hasattr(ctx, 'gopher_menu'):
                host = request.environ['SERVER_NAME']
                port = request.environ['SERVER_PORT']
                ctx.gopher_menu = GopherMenu(host, port)
            return ctx.gopher_menu

    # Add shortcuts for all of the GopherMenu types
    file = _add_menu_func(GopherMenu.file)
    submenu = _add_menu_func(GopherMenu.submenu)
    ccso = _add_menu_func(GopherMenu.ccso)
    binhex = _add_menu_func(GopherMenu.binhex)
    archive = _add_menu_func(GopherMenu.archive)
    uuencoded = _add_menu_func(GopherMenu.uuencoded)
    query = _add_menu_func(GopherMenu.query)
    telnet = _add_menu_func(GopherMenu.telnet)
    binary = _add_menu_func(GopherMenu.binary)
    gif = _add_menu_func(GopherMenu.gif)
    image = _add_menu_func(GopherMenu.image)
    doc = _add_menu_func(GopherMenu.doc)
    sound = _add_menu_func(GopherMenu.sound)
    video = _add_menu_func(GopherMenu.video)
    info = _add_menu_func(GopherMenu.info)
    html = _add_menu_func(GopherMenu.html)
    title = _add_menu_func(GopherMenu.title)
    error = _add_menu_func(GopherMenu.error)

    def render_menu(self, *lines):
        """
        This wraps the flask.make_response() formatting to generate
        syntactically valid gopher menus. This includes chopping the
        line length to stay within a predefined length, normalizing
        newlines to CR/LF, and making sure that the last line of the
        body is a (.) period.

        Args:
            *lines (str): Lines of text to add to the menu

        Reference:

            Servers SHOULD send a full stop (.) after menus and may
            optionally send it after other files.

            All programmes using Gopher MUST always use the Microsoft standard
            of CR/LF, irrespective of the operating system they run on. Both
            internal Gopher commands and policy files MUST comply with this
            standard. Other text files SHOULD use standard Gopher format, but
            this is not strictly required as a matter of technical form; the
            client MUST be capable of converting to and from all variants of
            line terminators. The recommendation stands for the benefit of
            non-compliant clients only.

            User display strings are intended to be displayed on a line on a
            typical screen for a user's viewing pleasure.  While many screens
            can accommodate 80 character lines, some space is needed to display
            a tag of some sort to tell the user what sort of item this is.
            Because of this, the user display string should be kept under 70
            characters in length.  Clients may truncate to a length convenient
            to them.

            https://tools.ietf.org/html/draft-matavka-gopher-ii-03
            https://tools.ietf.org/html/rfc1436
        """
        menu_line_pattern = re.compile('^.+\t.*\t.*\t.*$')
        raw_menu, menu_lines = '\n'.join(lines), []
        for line in raw_menu.splitlines():
            line = line.rstrip()
            if not menu_line_pattern.match(line):
                # The line is normal block of text, convert it to an INFO
                line = self.info(line)

            # Unfortunately we need to re-parse every line to make sure that
            # display string is under the configured width. Add +1 to
            # account for the one character type identifier.
            parts = line.split('\t')
            parts[0] = parts[0][:self.width + 1]
            line = '\t'.join(parts)
            menu_lines.append(line)

        if not menu_lines or menu_lines[-1] != '.':
            menu_lines.append('.')
        menu_lines.append('')

        return '\r\n'.join(menu_lines)

    def render_menu_template(self, template_name, **context):
        """
        This is convenience wrapper around flask.render_template() that
        renders a gopher menu.
        """
        template_string = render_template(template_name, **context)
        return self.render_menu(template_string)

    @staticmethod
    def url_for(endpoint, _external=False, _type=1, **values):
        """
        Injects the type into the beginning of the selector for external URLs.

            gopher://127.0.0.1:70/home => gopher://127.0.0.1:70/1/home
        """
        if not _external:
            url = url_for(endpoint, **values)
        else:
            values['_scheme'] = 'gopher'
            url = url_for(endpoint, _external=_external, **values)
            parts = url.split('/')
            parts.insert(3, str(_type))
            url = '/'.join(parts)
        return url


def render_menu(*lines):
    """
    Alternate method
    """
    return current_app.extensions['gopher'].render_menu(*lines)


def render_menu_template(template_name, **context):
    """
    Alternate method
    """
    method = current_app.extensions['gopher'].render_menu_template
    return method(template_name, **context)


class GopherRequestHandler(WSGIRequestHandler):
    """
    Gopher is a lightweight, client/server-oriented query/answer protocol built
    on top of TCP/IP. This class a shim for the base Werkzeug HTTP request
    handler that takes Gopher requests and converts them into a WSGI compatible
    format.

    A Gopher transaction looks like this:

      1. The gopher client opens a TCP connection with the server.
      2. The server accepts the connection and says nothing.
      3. The client sends a selector string followed by CR/LF, or nothing.
      4. The server sends the requested content and closed the connection.

    The <selector> string sent by the client tells the server what content
    to return. The selector string can be an arbitrary sequence of characters
    not including {\t, \r, \n}. Generally the selector string is formatted
    like an HTTP path that points to a document on the server, but this is
    not a strict requirement of the protocol.

        <selector><CR><LF>

    For gopher searches, the client will place a <TAB> between the selector
    and the text query. The search text, like the selector, can contain any
    character except for {\t, \r, \n}.

        <selector><TAB><search><CR><LF>

    The gopher+ protocol takes this a step further by adding another tab and
    the gopher+ string after the search query. This request handler does not
    attempt to handle this type of request.

        <selector><TAB><search><TAB><gopher+string><CR><LF>

    The server responds to the client with a blob of text or bytes. Constrasted
    with HTTP, there is no status code, version string, or request headers.
    There are different rules for how the response body should be formatted
    depending on if the request was for a menu item, a text item, or a binary
    item. However, it is left up to the WSGI application to make this
    distinction and build an appropriately formatted body.

    References:
        https://tools.ietf.org/id/draft-matavka-gopher-ii-03.html
        https://tools.ietf.org/html/rfc1436
    """

    @property
    def server_version(self):
        return 'Flask-Gopher/' + __version__

    def send_header(self, keyword, value):
        if self.request_version != 'gopher':
            return super().send_header(keyword, value)

    def end_headers(self):
        if self.request_version != 'gopher':
            return super().end_headers()

    def send_response(self, code, message=None):
        self.log_request(code)
        if self.request_version != 'gopher':
            if message is None:
                message = code in self.responses and self.responses[code][0] or ''
            if self.request_version != 'HTTP/0.9':
                hdr = "%s %d %s\r\n" % (self.protocol_version, code, message)
                self.wfile.write(hdr.encode('ascii'))

    def make_environ(self):
        environ = super().make_environ()
        if self.request_version == 'gopher':
            environ['wsgi.url_scheme'] = 'gopher'
            environ['SEARCH_TEXT'] = self.search_text
        return environ

    def parse_request(self):
        requestline = str(self.raw_requestline, 'iso-8859-1')
        self.requestline = requestline.rstrip('\r\n')

        # Determine the the request is HTTP, and if so let the
        # python HTTPRequestHandler handle it
        words = self.requestline.split()
        if len(words) == 3 and words[2][:5] == 'HTTP/':
            return super().parse_request()
        elif len(words) == 2 and words[0] == 'GET':
            return super().parse_request()

        # At this point, assume the request is a gopher://
        return self.parse_gopher_request()

    def parse_gopher_request(self):
        self.close_connection = True
        self.request_version = 'gopher'  # Instead of HTTP/1.1, etc
        self.command = 'GET'
        self.headers = {}

        url_parts = self.requestline.split('\t')
        self.path = url_parts[0] or '/'
        if not self.path.startswith('/'):
            # Gopher doesn't require the selector to start with a /, but
            # the werkzeug router does!
            self.path = '/' + self.path
        self.search_text = url_parts[1] if len(url_parts) > 1 else ''
        return True
