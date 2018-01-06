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

Flask-Gopher is an extension library for the Python Flask web microframework that adds support for gopher request handling. The Gopher Protocol is an alternative to HTTP that peaked in popularity in the mid 90's. There are still a handful of gopher sites maintained by enthusiasts; you can learn more about the history of the protocol at http://gopher.floodgap.com/gopher/.

This extension works by adding a thin Gopher => HTTP compatability layer into the built-in WSGI server. It turns gopher requests into pseudo-HTTP GET requests so they can be handled by Flask (or any other python WSGI framework) natively. This means that you get full access to Flask's routing, templating engine, debugger, and other tools to build your gopher server.

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

## Gopher Protocol References

- https://tools.ietf.org/html/rfc1436
- https://tools.ietf.org/html/rfc4266
- https://tools.ietf.org/html/draft-matavka-gopher-ii-03
- https://www.w3.org/Addressing/URL/4_1_Gopher+.html

