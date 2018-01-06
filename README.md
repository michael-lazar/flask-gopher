<h1 align="center">Flask-Gopher</h1>

<p align="center">
  <img alt="gopher" src="resources/gopher_alt.jpg"/>
</p>

<p align="center">
  <a href="https://pypi.python.org/pypi/flask-gopher/">
    <img alt="pypi" src="https://img.shields.io/pypi/v/flask-gopher.svg?label=version"/>
  </a>
  <a href="https://pypi.python.org/pypi/flask-gopher/">
    <img alt="python" src="https://img.shields.io/badge/python-3.4+-blue.svg"/>
  </a>
  <a href="https://travis-ci.org/michael-lazar/flask-gopher">
    <img alt="travis-ci" src="https://travis-ci.org/michael-lazar/flask-gopher.svg?branch=master"/>
  </a>
  <a href="https://coveralls.io/github/michael-lazar/flask-gopher?branch=master">
    <img alt="coveralls" src="https://coveralls.io/repos/michael-lazar/flask-gopher/badge.svg?branch=master&service=github"/>
  </a>
</p>

## About

Flask-Gopher is an extension library for the Python Flask web microframework that adds support for gopher request handling. The Gopher Protocol is an alternative to HTTP that peaked in popularity in the mid 90's. There are still a handful of gopher sites maintained by enthusiasts; you can learn more about its history at http://gopher.floodgap.com/gopher/

This extension works by adding a thin Gopher => HTTP compatability layer into Flask's built-in WSGI server. It turns gopher requests into pseudo HTTP GET requests so they can be handled by Flask (or any other python WSGI app) natively. This means that you get full access to Flask's routing, templating engine, debugger, and other tools to build your gopher server.

## Installation

This package requires **python 3**

```
pip install flask_gopher
```

## Quickstart

```python
from flask import Flask
from flask_gopher import GopherExtension, GopherRequestHandler

app = Flask(__name__)
gopher = GopherExtension(app)

@app.route('/')
def index():
    return gopher.render_menu(
        gopher.title('Menu Page'),
        gopher.submenu('Home', url_for('index')),
        gopher.info("Look Ma, it's a gopher server!"))

if __name__ == '__main__':
   app.run('127.0.0.1', 70, request_handler=GopherRequestHandler)
```

## Gopher and WSGI

Python's WSGI (Web Server Gateway Interface) is an established API that defines how python web servers (gunicorn, mod_wsgi, etc) communicate with application frameworks (Flask, Django, etc). It defines a clean boundary between low-level socket and request handling, and high-level application logic.

WSGI was designed to be a very simple and flexible API, but at its heart it's built around HTTP. As such, it incorperates some HTTP specific components like request/response headers and status codes. Gopher is more basic and doesn't use these components. Here's an example of the difference in fetching a document with the two protocols:

<table>
<tr><th colspan=2>HTTP</th><th colspan=2>Gopher</th></tr>
<tr><th>request</th><th>response</th><th>request</th><th>response</th></tr>
<tr>
<td width="20%"><pre>
GET /path HTTP/1.1
Accept: text/plain
Accept-Charset: utf-8
...more headers
</pre></td>
<td width="20%"><pre>
HTTP/1.1 200 OK
Server: Apache
Content-Type: text/html
...more headers<br>
(body)
</pre></td>
<td width="20%"><pre>/path\r\n</pre></td>
<td width="20%"><pre>(body)</pre></td>
</tr></table>

In order to resolve the differences between gopher and HTTP, **Flask-Gopher** provides a custom ``GopherRequestHandler``. The handler hooks into the WSGI server (``werkzeug.BaseWSGIServer``). It reads the first line of every TCP connection and determines which protocol the client is attempting to use. If the client is using gopher, the following assumptions are made:

- Set the request's *REQUEST_METHOD* (e.g. *GET*, *POST*) to ``GET``
- Set the request's *SERVER_PROTOCOL* (e.g. *HTTP/1.1*) to ``gopher``
- Set the request's *wsgi.url_scheme* (e.g. *https*)  to ``gopher``
- Discard the response status line
- Discard all response headers

Doing this makes a gopher connection *appear* like a normal HTTP request from the perspective of the WSGI application. It also provides metadata that can be accessed from the Flask request object.

```python
@app.route('/')
def index():
    if flask.request.scheme == 'gopher':
        return "iThis was a gopher request\tfake\texample.com\t0\r\n"
    else:
        return "<html><body>This was an HTTP request</body></html>" 
```


## Gopher Protocol References

- https://tools.ietf.org/html/rfc1436 (1993)
- https://tools.ietf.org/html/rfc4266 (2005)
- https://tools.ietf.org/html/draft-matavka-gopher-ii-03 (2015)
- https://www.w3.org/Addressing/URL/4_1_Gopher+.html

