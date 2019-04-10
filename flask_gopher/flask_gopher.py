import re
import os
import ssl
import socket
import weakref
import textwrap
import traceback
import mimetypes
from pathlib import Path
from datetime import datetime
from itertools import zip_longest
from collections import namedtuple
from functools import partialmethod
from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode

from pyfiglet import figlet_format, FigletError
from tabulate import tabulate
from flask import _request_ctx_stack as request_ctx_stack
from flask import request, render_template, current_app, url_for
from flask.helpers import safe_join, send_file
from flask.sessions import SecureCookieSessionInterface, SecureCookieSession
from werkzeug.local import LocalProxy
from werkzeug.serving import WSGIRequestHandler, can_fork
from werkzeug.serving import BaseWSGIServer, ThreadingMixIn, ForkingMixIn
from werkzeug.serving import generate_adhoc_ssl_context, load_ssl_context
from werkzeug.exceptions import HTTPException, BadRequest
from jinja2.filters import escape
from itsdangerous import URLSafeSerializer, BadSignature

from .__version__ import __version__


@LocalProxy
def menu():
    """
    Shortcut for gopher.menu
    """
    return current_app.extensions['gopher'].menu


def render_menu(*lines):
    """
    Shortcut for gopher.render_menu
    """
    return current_app.extensions['gopher'].render_menu(*lines)


def render_menu_template(template_name, **context):
    """
    Shortcut for gopher.render_menu_template
    """
    return current_app.extensions['gopher'].render_menu_template(template_name, **context)


class TextFormatter:
    """
    Helper methods for applying formatting techniques to gopher menu text.
    """

    def __init__(self, default_width=70):
        self.default_width = default_width

    def banner(self, text, ch='=', side='-', width=None):
        """
        Surrounds the text with an ascii banner:

            ========================================
            -             Hello World!             -
            ========================================
        """
        width = width or self.default_width
        offset = len(side)
        lines = []
        for line in text.splitlines():
            if side:
                lines.append(side + line.center(width)[offset:-offset] + side)
            else:
                lines.append(line.center(width))
        if ch:
            # Add the top & bottom
            top = bottom = (ch * width)[:width]
            lines = [top] + lines + [bottom]
        return '\r\n'.join(lines)

    def wrap(self, text, indent='', width=None):
        """
        Wraps a block of text into a paragraph that fits the width of the page
        """
        width = width or self.default_width
        wrapper = textwrap.TextWrapper(
            width=width,
            initial_indent=indent,
            subsequent_indent=indent,
            expand_tabs=False,
            replace_whitespace=False,
            drop_whitespace=True)
        lines = text.splitlines()
        return '\r\n'.join(wrapper.fill(line) for line in lines)

    def center(self, text, fillchar=' ', width=None):
        """
        Centers a block of text.
        """
        width = width or self.default_width
        lines = text.splitlines()
        return '\r\n'.join(line.center(width, fillchar) for line in lines)

    def rjust(self, text, fillchar=' ', width=None):
        """
        Right-justifies a block of text.
        """
        width = width or self.default_width
        lines = text.splitlines()
        return '\r\n'.join(line.rjust(width, fillchar) for line in lines)

    def ljust(self, text, fillchar=' ', width=None):
        """
        Left-justifies a block of text.
        """
        width = width or self.default_width
        lines = text.splitlines()
        return '\r\n'.join(line.ljust(width, fillchar) for line in lines)

    def float_right(self, text_left, text_right, fillchar=' ', width=None):
        """
        Left-justifies text, and then overlays right justified text on top
        of it. This gives the effect of having a floating div on both
        sides of the screen.
        """
        width = width or self.default_width
        left_lines = text_left.splitlines()
        right_lines = text_right.splitlines()

        lines = []
        for left, right in zip_longest(left_lines, right_lines, fillvalue=''):
            padding = width - len(right)
            line = (left.ljust(padding, fillchar) + right)[-width:]
            lines.append(line)
        return '\r\n'.join(lines)

    def figlet(self, text, width=None, font='normal', justify='auto', **kwargs):
        """
        Renders the given text using the pyfiglet engine. See the pyfiglet
        package for more information on available fonts and options. There's
        also a  command line client (pyfiglet) that you can use to test out
        different fonts. There are over 500 of them!

        Options:
            font (str): The figlet font to use, see pyfiglet for choices
            direction (str): auto, left-to-right, right-to-left
            justify (str): auto, left, right, center
        """
        width = width or self.default_width
        try:
            text = figlet_format(text, font, width=width, justify=justify, **kwargs)
        except FigletError:
            # Could be that the character is too large for the width of the
            # screen, or some other figlet rendering error. Fall back to using
            # the bare text that the user supplied.
            pass

        if justify == 'center':
            text = self.center(text, width=width)
        elif justify == 'right':
            text = self.rjust(text, width=width)
        return text

    def tabulate(self, tabular_data, headers=(), tablefmt="simple", **kwargs):
        """
        Renders the given data into an ascii table using tabulate.

        See the tabulate package for more information on available options.
        """
        text = tabulate(tabular_data, headers, tablefmt, **kwargs)

        # Add whitespace to make each line in the table the same length
        # This allows it to be centered / right aligned
        lines = text.splitlines()
        width = max(len(line) for line in lines)
        return '\r\n'.join([line.ljust(width) for line in lines])

    @staticmethod
    def underline(text, ch='_'):
        """
        Adds an underline to a block of text

        The width of the underline will match the width of the text.
        """
        width = max(len(line) for line in text.splitlines())
        underline = (ch * width)[:width]
        return '\r\n'.join([text, underline])


class GopherMenu:
    """
    Helper methods for rendering gopher menu lines.

    A menu line has the following format:
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

        # The error spec doesn't seem to work in Lynx, so I'm using plain text
        # return self.entry('3', error_code, message, 'example.com', 0)
        return 'Error: {} {}'.format(error_code, message)


class GopherExtension:
    """
    This main gopher extension.
    """

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

    def __init__(self, app=None, menu_class=GopherMenu, formatter_class=TextFormatter):
        self.width = None
        self.show_stack_trace = None

        self.formatter = None

        self.menu_class = menu_class
        self.formatter_class = formatter_class

        self.app = app
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        self.width = app.config.setdefault('GOPHER_WIDTH', 70)
        self.show_stack_trace = app.config.setdefault('GOPHER_SHOW_STACK_TRACE', False)

        self.formatter = self.formatter_class(self.width)

        self._add_gopher_jinja_methods(app)
        self._add_gopher_url_redirect(app)
        self._add_gopher_error_handler(app)

        app.extensions['gopher'] = weakref.proxy(self)
        app.session_interface = GopherSessionInterface()

    def _add_gopher_jinja_methods(self, app):
        """
        Add the gopher helpers to the default jinja template environment.
        """
        app.jinja_env.trim_blocks = True
        app.jinja_env.lstrip_blocks = False

        @app.context_processor
        def add_context():
            return {
                'gopher': self,
                'menu': menu,
                'tabulate': self.formatter.tabulate
            }

        app.add_template_filter(self.formatter.wrap, 'wrap')
        app.add_template_filter(self.formatter.rjust, 'rjust')
        app.add_template_filter(self.formatter.ljust, 'ljust')
        app.add_template_filter(self.formatter.center, 'center')
        app.add_template_filter(self.formatter.banner, 'banner')
        app.add_template_filter(self.formatter.figlet, 'figlet')
        app.add_template_filter(self.formatter.underline, 'underline')
        app.add_template_filter(self.formatter.float_right, 'float_right')

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
            # Use the full_path because it keeps any query params intact
            url = request.full_path.split(':', 1)[1]  # Drop the "/URL:"
            url = url.rstrip('?')  # Flask adds an ? even if there are no params
            url = escape(url)
            return self.URL_REDIRECT_TEMPLATE.format(url=url).strip()

    def _add_gopher_error_handler(self, app):
        """
        Intercept all errors for GOPHER requests and replace the default
        HTML error document with a gopher compatible text document.
        """
        def handle_error(error):
            if request.scheme != 'gopher':
                # Pass through the error to the default handler
                return error

            code = getattr(error, 'code', 500)
            name = getattr(error, 'name', 'Internal Server Error')
            desc = getattr(error, 'description', None)
            if desc is None and self.show_stack_trace:
                desc = traceback.format_exc()
            elif desc is None:
                desc = 'An internal error has occurred'
            body = [menu.error(code, name), '', self.formatter.wrap(desc)]

            # There's no way to know if the client has requested a gopher
            # menu, a text file, or a binary file. But we can make a guess
            # based on if the request path has a file extension at the end.
            ext = os.path.splitext(request.path)[1]
            if ext:
                return '\r\n'.join(body)
            else:
                return self.render_menu(*body)

        # Attach this handler to all of the builtin flask exceptions
        for cls in HTTPException.__subclasses__():
            app.register_error_handler(cls, handle_error)

    @property
    def menu(self):
        """
        The current active instance of the GopherMenu class.

        This variable is instantiated on the request context so that it can be
        initialized with the same host/port that the request's url_adapter is
        using.
        """
        ctx = request_ctx_stack.top
        if ctx is not None:
            if not hasattr(ctx, 'gopher_menu'):
                host = request.environ['SERVER_NAME']
                port = request.environ['SERVER_PORT']
                ctx.gopher_menu = self.menu_class(host, port)
            return ctx.gopher_menu

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
                line = menu.info(line)

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

    def serve_directory(self, local_directory, view_name, url_token='filename',
                        show_timestamp=True, width=None):
        """
        This is a convenience wrapper around the GopherDirectory class.
        """
        return GopherDirectory(
            local_directory,
            view_name,
            url_token=url_token,
            show_timestamp=show_timestamp,
            width=width or self.width)

    @staticmethod
    def url_for(endpoint, _external=False, _type=1, **values):
        """
        Injects the type into the beginning of the selector for external URLs.

            gopher://127.0.0.1:70/home => gopher://127.0.0.1:70/1/home
        """
        if not _external:
            return url_for(endpoint, **values)

        values['_scheme'] = 'gopher'
        url = url_for(endpoint, _external=_external, **values)
        parts = url.split('/')
        parts.insert(3, str(_type))
        url = '/'.join(parts)
        return url


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

    The server responds to the client with a blob of text or bytes. Contrasted
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
            environ['SECURE'] = isinstance(self.request, ssl.SSLSocket)

            # Flask has a sanity check where if app.config['SERVER_NAME'] is
            # defined, it has to match either the HTTP host header or the
            # WSGI server's environ['SERVER_NAME']. With the werkzeug WSGI
            # server, environ['SERVER_NAME'] is set to the bind address
            # (e.g. 127.0.0.1) and it can't be configured. This means that
            # if we want to set app.config['SERVER_NAME'] to an external IP
            # address or domain name, we need to spoof either the HTTP_HOST
            # header or the SERVER_NAME env variable to match it.
            # Go look at werkzeug.routing.Map.bind_to_environ()
            try:
                server_name = self.server.app.config.get('SERVER_NAME')
            except Exception:
                pass
            else:
                if server_name:
                    if ':' in server_name:
                        environ['SERVER_PORT'] = server_name.split(':')[1]
                    environ['SERVER_NAME'] = server_name.split(':')[0]
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

        # Add a token to the requestline for server logging
        if isinstance(self.request, ssl.SSLSocket):
            self.requestline = '<SSL> ' + self.requestline

        return True


class GopherDirectory:
    """
    This class can be used as a helper to generate an gopher menu that maps to
    a directory on the filesystem.

    Usage:

        music_directory = GopherDirectory('/home/gopher/music', 'music', gopher.menu)

        @app.route('/files/music')
        @app.route('/files/music/<path:filename>')
        def music(filename=''):

            is_directory, file = music_directory.load_file(filename)
            if is_directory:
                return gopher.render_menu(file)
            else
                return file
    """
    result_class = namedtuple('file', ['is_directory', 'data'])
    timestamp_fmt = '%Y-%m-%d %H:%M:%S'

    def __init__(self,
                 local_directory,
                 view_name,
                 url_token='filename',
                 show_timestamp=False,
                 width=70):
        """
        Args:
            local_directory: The local file system path that will be served.
            view_name: The name of the app view that maps to the directory.
            url_token: The path will be inserted into this token in the URL.
            show_timestamp: Include the last accessed timestamp for each file.
            width: The page width to use when formatting timestamp strings.
        """
        self.local_directory = local_directory
        self.view_name = view_name
        self.url_token = url_token
        self.show_timestamp = show_timestamp
        self.width = width

        #  Custom file extensions can be added via self.mimetypes.add_type()
        self.mimetypes = mimetypes.MimeTypes()

    def load_file(self, filename):
        """
        Load the filename from the local directory. The type of the returned
        object depends on if the filename corresponds to a file or a directory.
        If it's a file, a flask Response object containing the file's data will
        be returned. If it's a directory, a gopher menu will be returned.

        This method uses the flask application context, which means that it
        can only be invoked from inside of a flask view.
        """
        abs_filename = safe_join(self.local_directory, filename)
        if not os.path.isabs(abs_filename):
            abs_filename = os.path.join(current_app.root_path, abs_filename)

        if os.path.isfile(abs_filename):
            return self.result_class(False, send_file(abs_filename))
        elif os.path.isdir(abs_filename):
            data = self._parse_directory(filename, abs_filename)
            return self.result_class(True, data)
        else:
            raise BadRequest()

    def _parse_directory(self, folder, abs_folder):
        """
        Construct a gopher menu that represents all of the files in a directory.
        """
        folder = Path(folder)

        lines = []

        # Add a link to the parent directory if we're not at the top level
        if folder.parent != folder:
            if folder.parent != folder.parent.parent:
                options = {self.url_token: folder.parent}
            else:
                options = {}
            lines.append(menu.submenu('..', url_for(self.view_name, **options)))

        for file in sorted(Path(abs_folder).iterdir()):
            relative_file = folder / file.name

            menu_type = self._guess_menu_type(file)

            item_text = file.name
            if file.is_dir():
                item_text += '/'

            if self.show_timestamp:
                last_modified = datetime.fromtimestamp(file.stat().st_mtime)
                timestamp = last_modified.strftime(self.timestamp_fmt)
                item_text = item_text.ljust(self.width - len(timestamp)) + timestamp

            options = {self.url_token: relative_file}
            lines.append(menu_type(item_text, url_for(self.view_name, **options)))

        return '\n'.join(lines)

    def _guess_menu_type(self, file):
        """
        Guess the gopher menu type for the given file.
        """
        if file.is_dir():
            return menu.submenu

        mime_type, encoding = self.mimetypes.guess_type(str(file))
        if encoding:
            return menu.archive

        if not mime_type:
            return menu.file

        menu_type_map = [
            ('text/', menu.file),
            ('image/gif', menu.gif),
            ('image/', menu.image),
            ('application/pdf', menu.doc),
            ('application/', menu.binary),
            ('audio/', menu.sound),
            ('video/', menu.video),
        ]
        for mime_type_prefix, mime_menu_type in menu_type_map:
            if mime_type.startswith(mime_type_prefix):
                return mime_menu_type

        return menu.file


class GopherSessionInterface(SecureCookieSessionInterface):
    """
    This enables session handling in gopher via the flask.session variable.

    Gopher doesn't have headers or cookies, so sessions are achieved using a
    special `_session` URL query parameter. Gopher requests containing this
    parameter will automatically have their session data loaded into flask.
    Sessions are transmitted by parsing the response body of gopher menus and
    inserting the _session param into any internal links.

    The session string will be encrypted, but it will still be passed over
    an insecure gopher connection. Don't use the session to store passwords
    or other sensitive information. Try to store minimal data in the session to
    avoid returning large and unwieldy URL's.
    """

    gopher_session_class = type('GopherSession', (SecureCookieSession,), {})

    def get_gopher_signing_serializer(self, app):
        """
        This is almost the same serializer that the cookie session uses,
        except that it doesn't set an `expiration` time for the session.
        """
        if not app.secret_key:
            return None
        signer_kwargs = dict(
            key_derivation=self.key_derivation,
            digest_method=self.digest_method)
        return URLSafeSerializer(
            app.secret_key,
            salt=self.salt,
            serializer=self.serializer,
            signer_kwargs=signer_kwargs)

    def open_session(self, app, request):
        """
        Load and decode the session from the request query string.
        """
        s = self.get_gopher_signing_serializer(app)
        if not s:
            return None
        val = request.args.get('_session', None)
        if not val:
            return self.gopher_session_class()
        try:
            data = s.loads(val)
            return self.gopher_session_class(data)
        except BadSignature:
            return self.gopher_session_class()

    def save_session(self, app, session, response):
        """
        Normally the session is saved by adding a cookie header to the
        response object. However, in this case, because were using a
        query param we need to insert the session into every internal
        link that's returned in the response body. Unfortunately there's
        no easy way to do this, so for now I'm using a regex search
        that looks for gopher internal menu links and appends the _session
        query param to the end of each link selector.
        """
        if not session or response.direct_passthrough:
            # Don't bother trying to save the session if there's nothing to save,
            # or if the response is a static file or streaming file.
            return None

        s = self.get_gopher_signing_serializer(app)
        session_str = s.dumps(dict(session))

        # Build the regex pattern that searches for internal gopher menu links
        host = request.environ['SERVER_NAME']
        port = request.environ['SERVER_PORT']
        url_pattern = '^(?P<type>[^i])(?P<desc>.+)\t(?P<selector>.*)\t%s\t%s\r$'
        url_pattern = url_pattern % (re.escape(host), re.escape(port))

        def on_match(matchobj):
            """
            This function is called on every regex match. It takes an
            existing gopher link, extracts the path and the query string,
            adds the _session param to it, and rebuilds the link.
            """
            url_parts = urlsplit(matchobj.group('selector'))
            query = parse_qs(url_parts.query)
            query['_session'] = [session_str]
            new_query = urlencode(query, doseq=True)
            new_url = urlunsplit([
                url_parts.scheme, url_parts.netloc, url_parts.path,
                new_query, url_parts.fragment])
            new_line = '%s%s\t%s\t%s\t%s\r' % (
                matchobj.group('type'), matchobj.group('desc'), new_url, host, port)
            return new_line

        data = bytes.decode(response.data)
        new_data = re.sub(url_pattern, on_match, data, flags=re.M)
        response.data = new_data.encode()


class GopherBaseWSGIServer(BaseWSGIServer):
    """
    WSGI server extension that enables SSL sockets on a per-connection basis.

    This is achieved by peeking at the first byte of each socket connection.
    If the first byte is a SYN, it indicates the start of an SSL handshake.
    """

    def __init__(self, host, port, app, handler=None,
                 passthrough_errors=False, ssl_context=None, fd=None):
        """
        Override the server initialization to save the SSL context without
        immediately wrapping the socket in an SSL connection.
        """
        super(GopherBaseWSGIServer, self).__init__(
            host, port, app, handler, passthrough_errors, fd=fd)

        if ssl_context is not None:
            if isinstance(ssl_context, tuple):
                ssl_context = load_ssl_context(*ssl_context)
            if ssl_context == 'adhoc':
                ssl_context = generate_adhoc_ssl_context()
            self.ssl_context = ssl_context

    def wrap_request_ssl(self, request):
        """
        Check the first byte of the request for an SSL handshake and optionally
        wrap the connection. This is a blocking action and should only
        performed from inside of a new thread/forked process when running a
        server that can handle simultaneous connections.
        """
        if self.ssl_context:
            # Check the first byte without removing it from the buffer.
            char = request.recv(1, socket.MSG_PEEK)
            if char == b'\x16':
                # It's a SYN byte, assume the client is trying to establish SSL
                request = self.ssl_context.wrap_socket(request, server_side=True)
        return request

    def serve_forever(self):
        """
        Add some extra log messages when launching the server.
        """
        display_hostname = self.host not in ('', '*') and self.host or 'localhost'
        if ':' in display_hostname:
            display_hostname = '[%s]' % display_hostname
        quit_msg = '(Press CTRL+C to quit)'
        self.log('info', ' * Running on %s://%s:%d/ %s',
                 self.ssl_context is None and 'http' or 'https',
                 display_hostname, self.port, quit_msg)

        super(GopherBaseWSGIServer, self).serve_forever()


class GopherSimpleWSGIServer(GopherBaseWSGIServer):
    """
    Add a hook to actually wrap the SSL requests. This is not applicable for
    the Threaded/Forking servers because they have their own entry points for
    where the hook needs to be installed. Because of how the exception handling
    works here, we need to override _handle_request_noblock() to make sure that
    self.shutdown_request() is always invoked with the correct request object.
    """

    def _handle_request_noblock(self):
        try:
            request, client_address = self.get_request()
        except OSError:
            return
        if self.verify_request(request, client_address):
            try:
                request = self.wrap_request_ssl(request)
                self.process_request(request, client_address)
            except Exception:
                self.handle_error(request, client_address)
                self.shutdown_request(request)
            except:
                self.shutdown_request(request)
                raise
        else:
            self.shutdown_request(request)


class GopherThreadedWSGIServer(ThreadingMixIn, GopherBaseWSGIServer):
    """
    Copy of werkzeug.serving.ThreadedWSGIServer using our custom base server.

    The SSL connection is established at the beginning of the child thread.
    """
    multithread = True
    daemon_threads = True

    def process_request_thread(self, request, client_address):
        request = self.wrap_request_ssl(request)
        super(GopherThreadedWSGIServer, self).process_request_thread(request, client_address)


class GopherForkingWSGIServer(ForkingMixIn, GopherBaseWSGIServer):
    """
    Copy of werkzeug.serving.ForkingWSGIServer using our custom base server.

    The SSL connection is established in the child process immediately after
    the fork.
    """
    multiprocess = True

    def __init__(self, host, port, app, processes=40, handler=None,
                 passthrough_errors=False, ssl_context=None, fd=None):
        if not can_fork:
            raise ValueError('Your platform does not support forking.')

        super(GopherForkingWSGIServer, self).__init__(
            host, port, app, handler, passthrough_errors, ssl_context, fd)
        self.max_children = processes

    def process_request(self, request, client_address):
        """Fork a new subprocess to process the request."""
        pid = os.fork()
        if pid:
            # Parent process
            if self.active_children is None:
                self.active_children = set()
            self.active_children.add(pid)
            self.close_request(request)
            return
        else:
            # Child process.
            # This must never return, hence os._exit()!
            status = 1
            try:
                request = self.wrap_request_ssl(request)
                self.finish_request(request, client_address)
                status = 0
            except Exception:
                self.handle_error(request, client_address)
            finally:
                try:
                    self.shutdown_request(request)
                finally:
                    os._exit(status)


def make_gopher_ssl_server(
        host=None, port=None, app=None, threaded=False, processes=1,
        request_handler=None, passthrough_errors=False, ssl_context=None,
        fd=None):
    """
    Create a new server instance that supports ad-hoc Gopher SSL connections.

    This server is only necessary when enabling experimental SSL over gopher.
    Otherwise, it's simpler to use app.run() instead. That method accepts the
    same arguments and has additional support for things like debug mode and
    auto-reloading.
    """
    if threaded and processes > 1:
        raise ValueError("cannot have a multithreaded and multi process server.")
    elif threaded:
        return GopherThreadedWSGIServer(host, port, app, request_handler,
                                        passthrough_errors, ssl_context, fd=fd)
    elif processes > 1:
        return GopherForkingWSGIServer(host, port, app, processes,
                                       request_handler, passthrough_errors,
                                       ssl_context, fd=fd)
    else:
        return GopherSimpleWSGIServer(host, port, app, request_handler,
                                      passthrough_errors, ssl_context, fd=fd)
