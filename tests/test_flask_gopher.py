import os
import ssl
import json
import socket
import unittest
from threading import Thread
from urllib.request import Request, urlopen

from flask import Flask, request, url_for, session
from flask_gopher import GopherExtension, GopherRequestHandler
from flask_gopher import GopherMenu, TextFormatter
from flask_gopher import make_gopher_ssl_server
from flask_gopher import menu, render_menu, render_menu_template


TEST_DIR = os.path.dirname(os.path.realpath(__file__))


class TestFunctional(unittest.TestCase):
    """
    Because the flask_gopher extension is built on hacking the WSGI protocol
    and the werkzeug HTTP server, I feel that the only way to sincerely
    know that it's working properly is through functional testing.

    So this class will spin up a complete test flask application and serve
    it on a local TCP port in a new thread. The tests will send real gopher
    connection strings to the server and check the validity of the response
    body from end-to-end.
    """
    app = gopher = server = thread = None

    @classmethod
    def setUpClass(cls):
        """
        Spin up a fully-functional test gopher application in a new thread.
        """

        cls.app = app = Flask(__name__, template_folder=TEST_DIR)
        cls.gopher = gopher = GopherExtension(app)
        cls.ssl_context = (
            os.path.join(TEST_DIR, 'test_cert.pem'),
            os.path.join(TEST_DIR, 'test_key.pem'))

        app.config['SECRET_KEY'] = 's3cr3tk3y'
        app.config['SERVER_NAME'] = 'gopher.server.com:7000'

        @app.route('/')
        def home():
            return 'Hello World!'

        @app.route('/menu')
        def menu_route():
            return render_menu(
                menu.submenu('Submenu', url_for('menu_route')),
                menu.file('Text', url_for('static', filename='file.txt')),
                menu.info('x' * 200),  # Long lines should be truncated
                'x' * 200,  # Should looks the same as using menu.info()
                menu.info('foo\r\nbar\t'))  # Tabs and newlines should be stripped

        @app.route('/template')
        def template():
            return render_menu_template('test_template.gopher', items=range(3))

        @app.route('/ssl')
        def ssl():
            return str(request.environ['SECURE'])

        @app.route('/page/<int:page>')
        def page(page):
            return 'page: ' + str(page)

        @app.route('/internal_url')
        def internal_url():
            return url_for('page', page=2)

        @app.route('/external_menu_url')
        def external_menu_url():
            return gopher.url_for('page', page=2, _external=True)

        @app.route('/query')
        def query():
            return 'query: ' + json.dumps(dict(request.args))

        @app.route('/search')
        def search():
            return 'search: ' + request.environ['SEARCH_TEXT']

        @app.route('/internal_error')
        def internal_error():
            return 1 // 0

        @app.route('/session')
        def session_route():
            resp = render_menu(
                'name: ' + session.get('name', ''),
                menu.submenu('Home', url_for('menu_route')),
                menu.submenu('External', host='debian.org'))
            session['name'] = 'fran'
            return resp

        # This is the same thing as calling app.run(), but it returns a handle
        # to the server so we can call server.shutdown() later.
        cls.server = make_gopher_ssl_server(
            '127.0.0.1', 0, app, request_handler=GopherRequestHandler,
            ssl_context=cls.ssl_context)
        cls.thread = Thread(target=cls.server.serve_forever)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        """
        Try to kill the server.
        """
        cls.server.shutdown()
        cls.thread.join(timeout=5)

    @classmethod
    def send_data(cls, data, use_ssl=False):
        """
        Send byte data to the server using a TCP/IP socket.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if use_ssl:
                s = ssl.wrap_socket(s)
            s.connect((cls.server.host, cls.server.port))
            s.sendall(data)

            # Receive data until the server disconnects
            chunks = []
            while True:
                data = s.recv(2048)
                if not data:
                    break
                chunks.append(data)
            return b''.join(chunks)

    def test_empty_request(self):
        """
        Empty request strings should return the root url.
        """
        resp = self.send_data(b'\n')
        self.assertEqual(resp, b'Hello World!')
        resp = self.send_data(b'\r\n')
        self.assertEqual(resp, b'Hello World!')

    def test_root_url(self):
        resp = self.send_data(b'/\r\n')
        self.assertEqual(resp, b'Hello World!')

    def test_multiline_request(self):
        """
        Anything past the first line of the request should be ignored.
        """
        resp = self.send_data(b'/\r\ntwo line request\r\nthird line')
        self.assertEqual(resp, b'Hello World!')

    def test_gopher_plus(self):
        """
        Gopher+ connections should ignore anything after the second tab.
        """
        resp = self.send_data(b'/\t\tgopher plus data\r\n')
        self.assertEqual(resp, b'Hello World!')

    def test_query_string(self):
        """
        Query strings should accepted by the server and parsed.
        """
        resp = self.send_data(b'/query\r\n')
        self.assertEqual(resp, b'query: {}')
        resp = self.send_data(b'/query?city=Grand%20Rapids\r\n')
        self.assertEqual(resp, b'query: {"city": ["Grand Rapids"]}')

    def test_search(self):
        """
        A tab in the request line should indicate search query text.
        """
        resp = self.send_data(b'/search\r\n')
        self.assertEqual(resp, b'search: ')
        resp = self.send_data(b'/search\tMy Search String\r\n')
        self.assertEqual(resp, b'search: My Search String')

    def test_not_found(self):
        """
        Check that the default 404 routing returns a gopher menu response.
        """
        resp = self.send_data(b'/invalid_url\r\n')
        self.assertTrue(resp.startswith(b'iError: 404 Not Found\tfake\texample.com\t0\r\n'))
        self.assertIn(b'The requested URL was not found', resp)
        self.assertTrue(resp.endswith(b'\r\n.\r\n'))

    def test_internal_error_menu(self):
        """
        Check that internal errors return a gopher menu response.
        """
        resp = self.send_data(b'/internal_error\r\n')
        line = b'iError: 500 Internal Server Error\tfake\texample.com\t0\r\n'
        self.assertTrue(resp.startswith(line))
        self.assertTrue(resp.endswith(b'\r\n.\r\n'))

    def test_internal_error_file(self):
        """
        Check that errors for non-menu endpoints return plain text messages.
        """
        resp = self.send_data(b'/internal_error.txt\r\n')
        self.assertTrue(resp.startswith(b'Error: 404 Not Found\r\n'))
        self.assertFalse(resp.endswith(b'\r\n.\r\n'))

    def test_internal_url(self):
        """
        Internal links should work with the default flask url_for method.
        """
        resp = self.send_data(b'/internal_url\r\n')
        self.assertEqual(resp, b'/page/2')

    def test_external_menu_url(self):
        """
        External Gopher menu links should have a "/1/" at the root.
        """
        resp = self.send_data(b'/external_menu_url\r\n')
        url = 'gopher://gopher.server.com:7000/1/page/2'
        self.assertEqual(resp, url.encode())

    def test_url_redirect(self):
        """
        Selectors starting with URL:<path> should be sent an HTML document.
        """
        resp = self.send_data(b'/URL:https://gopher.floodgap.com\r\n')
        self.assertTrue(resp.startswith(b'<HTML>'))
        self.assertTrue(resp.endswith(b'</HTML>'))

        href = b'<A HREF="https://gopher.floodgap.com">https://gopher.floodgap.com</A>'
        self.assertIn(href, resp)

    def test_http_get(self):
        """
        Regular HTTP requests should still work and headers should be passed
        """
        url = 'http://%s:%s/' % (self.server.host, self.server.port)
        request = Request(url)
        request.add_header('HOST', 'gopher.server.com:7000')
        resp = urlopen(request)
        self.assertEqual(resp.status, 200)
        self.assertIn('Content-Type', resp.headers)
        self.assertIn('Content-Length', resp.headers)
        self.assertTrue(resp.headers['Server'].startswith('Flask-Gopher'))
        self.assertEqual(resp.read(), b'Hello World!')

    def test_render_menu(self):
        """
        Check that gopher menu pages are properly formatted.
        """
        resp = self.send_data(b'/menu\r\n')
        text = '\r\n'.join([
            '1Submenu\t/menu\tgopher.server.com\t7000',
            '0Text\t/static/file.txt\tgopher.server.com\t7000',
            'i{line}\tfake\texample.com\t0',
            'i{line}\tfake\texample.com\t0',
            'ifoobar\tfake\texample.com\t0',
            '.', ''])
        text = text.format(line='x' * self.gopher.width)
        self.assertEqual(resp, text.encode())

    def test_render_menu_template(self):
        """
        Check that jinja templates generate correctly for gopher menus.
        """
        resp = self.send_data(b'/template\r\n')
        text = '\r\n'.join([
            'i{space}Title\tfake\texample.com\t0',
            'igopher://gopher.server.com:7000/1/menu\tfake\texample.com\t0',
            '1Home\t/menu\tgopher.server.com\t7000',
            'i0\tfake\texample.com\t0',
            'i1\tfake\texample.com\t0',
            'i2\tfake\texample.com\t0',
            '.', ''])
        text = text.format(space=' ' * (self.gopher.width - len('Title')))
        self.assertEqual(resp, text.encode())

    def test_session(self):
        """
        Sessions are supported in gopher using a special `_session` param.
        """

        # If the session is set on the server, it should be inserted into
        # any internal URLs in the response.
        resp = self.send_data(b'/session\r\n')
        text = '\r\n'.join([
            'iname:\tfake\texample.com\t0',
            '1Home\t/menu?_session={session_str}\tgopher.server.com\t7000',
            '1External\t/\tdebian.org\t70',
            '.', ''])

        # As long as the secret key, the salt, and the session data are fixed,
        # the session string should always encode to the same value.
        session_str = 'eyJuYW1lIjoiZnJhbiJ9.Ck3_ZpFWAkOiUONd-pmfkHV23A4'
        text = text.format(session_str=session_str)
        self.assertEqual(resp, text.encode())

        # Now add the session to the request URL, and make sure that it's
        # recognized and loaded into the server.
        selector = ('/session?_session=%s\r\n' % session_str).encode()
        resp = self.send_data(selector)
        text = '\r\n'.join([
            'iname: fran\tfake\texample.com\t0',
            '1Home\t/menu?_session={session_str}\tgopher.server.com\t7000',
            '1External\t/\tdebian.org\t70',
            '.', ''])
        text = text.format(session_str=session_str)
        self.assertEqual(resp, text.encode())

    def test_ssl_connection(self):
        """
        Clients should be able to optionally negotiate SSL connections.
        """
        # Insecure connection
        resp = self.send_data(b'/ssl\r\n')
        self.assertEqual(resp, b'False')

        # Secure connection
        resp = self.send_data(b'/ssl\r\n', use_ssl=True)
        self.assertEqual(resp, b'True')


class TestTextFormatter(unittest.TestCase):
    def setUp(self):
        self.formatter = TextFormatter(default_width=70)

    def test_banner_normal(self):
        output = self.formatter.banner('BANNER')
        lines = output.splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(all(len(line) == 70 for line in lines))
        self.assertEqual(lines[1][0], '-')
        self.assertEqual(lines[1][-1], '-')

    def test_banner_multiline(self):
        text = 'BANNER LINE 1\nBANNER LINE 2'
        output = self.formatter.banner(text, width=20)
        lines = output.splitlines()
        self.assertEqual(len(lines), 4)
        self.assertTrue(all(len(line) == 20 for line in lines))

    def test_banner_custom_ch(self):
        output = self.formatter.banner('BANNER', ch='+-', side='%$', width=40)
        lines = output.splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(all(len(line) == 40 for line in lines))

    def test_banner_no_border(self):
        output = self.formatter.banner('BANNER', ch='', side='')
        self.assertEqual(output, 'BANNER'.center(70))

    def test_wrap(self):
        text = 'f' * 100 + '\n' + 'g' * 100
        output = self.formatter.wrap(text, indent='**')
        lines = output.splitlines()
        self.assertEqual(len(lines), 4)
        self.assertEqual(max(len(line) for line in lines), 70)
        self.assertTrue(all(line.startswith('**') for line in lines))

    def test_center(self):
        text = 'line 1\nlonger line 2\n'
        output = self.formatter.center(text, fillchar='_')
        lines = output.splitlines()
        self.assertTrue(all(len(line) == 70 for line in lines))
        self.assertTrue(lines[0].startswith('_'))
        self.assertTrue(lines[1].startswith('_'))
        self.assertTrue(lines[0].endswith('_'))
        self.assertTrue(lines[1].endswith('_'))

    def test_rjust(self):
        text = 'line 1\nlonger line 2\n'
        output = self.formatter.rjust(text, fillchar='_')
        lines = output.splitlines()
        self.assertTrue(all(len(line) == 70 for line in lines))
        self.assertTrue(lines[0].startswith('_'))
        self.assertTrue(lines[1].startswith('_'))
        self.assertTrue(lines[0].endswith('_line 1'))
        self.assertTrue(lines[1].endswith('_longer line 2'))

    def test_ljust(self):
        text = 'line 1\nlonger line 2\n'
        output = self.formatter.ljust(text, fillchar='_')
        lines = output.splitlines()
        self.assertTrue(all(len(line) == 70 for line in lines))
        self.assertTrue(lines[0].startswith('line 1_'))
        self.assertTrue(lines[1].startswith('longer line 2_'))
        self.assertTrue(lines[0].endswith('_'))
        self.assertTrue(lines[1].endswith('_'))

    def test_float_right(self):
        left = 'left line 1\nleft line 2'
        right = 'right line 1'
        output = self.formatter.float_right(left, right, fillchar='_')
        lines = output.splitlines()
        self.assertTrue(all(len(line) == 70 for line in lines))
        self.assertTrue(lines[0].startswith('left line 1_'))
        self.assertTrue(lines[1].startswith('left line 2_'))
        self.assertTrue(lines[0].endswith('_right line 1'))
        self.assertTrue(lines[1].endswith('_'))

    def test_figlet_handle_error(self):
        # Sane defaults when the figlet renderer doesn't have a wide enough screen
        output = self.formatter.figlet('foo', font='doh', width=10)
        self.assertEqual(output, 'foo')
        output = self.formatter.figlet('foo', font='doh', width=10, justify='center')
        self.assertEqual(output, '   foo    ')
        output = self.formatter.figlet('foo', font='doh', width=10, justify='right')
        self.assertEqual(output, '       foo')

    def test_figlet(self):
        output = self.formatter.figlet('foobar', font='alpha')
        lines = output.splitlines()
        self.assertGreater(len(lines), 1)
        self.assertTrue(all(len(line) <= 70 for line in lines))

    def test_underline(self):
        output = self.formatter.underline('Super Duper')
        lines = output.splitlines()
        self.assertEqual(len(lines[0]), len(lines[1]))

    def test_underline_ch(self):
        output = self.formatter.underline('Super Duper', ch='*-')
        lines = output.splitlines()
        self.assertEqual(len(lines[0]), len(lines[1]))
        self.assertTrue(lines[1].startswith('*-'))

    def test_underline_multiline(self):
        output = self.formatter.underline('longer line\nshort line')
        lines = output.splitlines()
        self.assertEqual(len(lines[0]), len(lines[2]))

    def test_tabulate(self):
        data = [
            ('text', 'int', 'float'),
            ('Cell 1', 100, 1 / 3),
            ('Cell 2', -25, 0.001),
            ('Cell 3', 0, 0)]
        output = self.formatter.tabulate(data, headers='firstrow', tablefmt='psql')
        lines = output.splitlines()
        self.assertTrue(all(len(line) == 29 for line in lines))


class TestGopherMenu(unittest.TestCase):
    def setUp(self):
        self.menu = GopherMenu('10.10.10.10', 7007)

    def test_default_entry(self):
        line = self.menu.file('Hello World')
        self.assertEqual(line, '0Hello World\t/\t10.10.10.10\t7007')

    def test_default_no_port_external(self):
        line = self.menu.submenu('Hello World', host='hngopher.com')
        self.assertEqual(line, '1Hello World\t/\thngopher.com\t70')

    def test_strip_invalid_characters(self):
        line = self.menu.query('Hello \r\nWorld\t', selector='/\tfoo\t')
        self.assertEqual(line, '7Hello World\t/foo\t10.10.10.10\t7007')

    def test_html(self):
        line = self.menu.html('Firefox', 'http://www.firefox.com')
        self.assertEqual(line, 'hFirefox\tURL:http://www.firefox.com\t10.10.10.10\t7007')

    def test_title(self):
        line = self.menu.title('Hello World')
        self.assertEqual(line, 'iHello World\tTITLE\texample.com\t0')


class TestGopherBaseWSGIServer(unittest.TestCase):
    def test_make_gopher_server_forking(self):
        server = make_gopher_ssl_server('127.0.0.1', 0, processes=4)
        assert server.multiprocess
        assert server.max_children == 4

    def test_make_gopher_server_threaded(self):
        server = make_gopher_ssl_server('127.0.0.1', 0, threaded=True)
        assert server.multithread


if __name__ == '__main__':
    unittest.main()
