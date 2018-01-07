import os
import socket
import unittest
from threading import Thread
from urllib.request import Request, urlopen

from werkzeug.serving import make_server
from flask import Flask, request, url_for
from flask_gopher import GopherExtension, GopherRequestHandler, GopherMenu
from flask_gopher import render_menu, render_menu_template


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

        @app.route('/')
        def home():
            return 'Hello World!'

        @app.route('/menu')
        def menu():
            return render_menu(
                gopher.submenu('Submenu', url_for('menu')),
                gopher.file('Text', url_for('static', filename='file.txt')),
                gopher.info('x' * 200),  # Long lines should be truncated
                'x' * 200,  # Should looks the same as using menu.info()
                gopher.info('foo\r\nbar\t'))  # Tabs and newlines should be stripped

        @app.route('/template')
        def template():
            return render_menu_template('example_template', items=range(3))

        @app.route('/page/<int:page>')
        def page(page):
            return 'page: ' + str(page)

        @app.route('/internal_url')
        def internal_url():
            return url_for('page', page=2)

        @app.route('/external_menu_url')
        def external_menu_url():
            return gopher.url_for('page', page=2, _external=True)

        @app.route('/search')
        def search():
            return 'query: ' + request.environ['SEARCH_TEXT']

        @app.route('/internal_error')
        def internal_error():
            return 1 // 0

        # This is the same thing as calling app.run(), but it returns a handle
        # to the server so we can call server.shutdown() later.
        cls.server = make_server('127.0.0.1', 0, app, request_handler=GopherRequestHandler)
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
    def send_data(cls, data):
        """
        Send byte data to the server using a TCP/IP socket.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
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

    def test_search(self):
        """
        A tab in the request line should indicate search query text.
        """
        resp = self.send_data(b'/search\r\n')
        self.assertEqual(resp, b'query: ')
        resp = self.send_data(b'/search\tMy Search String\r\n')
        self.assertEqual(resp, b'query: My Search String')

    def test_not_found(self):
        """
        Check that the default 404 routing returns a gopher menu response.
        """
        resp = self.send_data(b'/invalid_url\r\n')
        self.assertTrue(resp.startswith(b'iError: 404 Not Found\tfake\texample.com\t0\r\n'))
        self.assertIn(b'The requested URL was not found', resp)
        self.assertTrue(resp.endswith(b'\r\n.\r\n'))

    def test_internal_error(self):
        """
        Check that internal errors return a gopher menu response.
        """
        resp = self.send_data(b'/internal_error\r\n')
        self.assertTrue(resp.startswith(b'iError: 500 Internal Error\tfake\texample.com\t0\r\n'))
        self.assertTrue(resp.endswith(b'\r\n.\r\n'))

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
        url = 'gopher://%s:%s/1/page/2' % (self.server.host, self.server.port)
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
            '1Submenu\t/menu\t{host}\t{port}',
            '0Text\t/static/file.txt\t{host}\t{port}',
            'i{line}\tfake\texample.com\t0',
            'i{line}\tfake\texample.com\t0',
            'ifoobar\tfake\texample.com\t0',
            '.', ''])
        text = text.format(
            host=self.server.host,
            port=self.server.port,
            line='x' * self.gopher.width)
        self.assertEqual(resp, text.encode())

    def test_render_menu_template(self):
        """
        Check that jinja templates generate correctly for gopher menus.
        """
        resp = self.send_data(b'/template\r\n')
        text = '\r\n'.join([
            'i{space}Title\tfake\texample.com\t0',
            'igopher://{host}:{port}/1/menu\tfake\texample.com\t0',
            '1Home\t/menu\t{host}\t{port}',
            'i0\tfake\texample.com\t0',
            'i1\tfake\texample.com\t0',
            'i2\tfake\texample.com\t0',
            '.', ''])
        text = text.format(
            host=self.server.host,
            port=self.server.port,
            space=' ' * (self.gopher.width - len('Title')))
        self.assertEqual(resp, text.encode())


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


if __name__ == '__main__':
    unittest.main()
