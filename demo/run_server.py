#!/usr/bin/env python3
"""
This is a demo application built using Flask-Gopher.

Perhaps the easiest way to get up and running is:

    $ git clone https://github.com/michael-lazar/flask-gopher.git
    $ cd flask-gopher
    $ python3 -m virtualenv venv
    $ source venv/bin/activate
    $ pip install .
    $ ./demo/run_server.py

Then, connect to the server with:

    $ lynx gopher://localhost:7005
"""
import json
import os
from collections import OrderedDict

from flask import Flask, abort, request, session, url_for
from pyfiglet import FigletFont
from tabulate import tabulate_formats

from flask_gopher import GopherExtension, GopherRequestHandler

ROOT_DIR = os.path.dirname(__file__)

app = Flask(__name__, static_url_path="")
app.config.from_pyfile("demo.cfg")

gopher = GopherExtension(app)


@app.route("/")
def index():
    return gopher.render_menu_template("index.gopher")


@app.route("/render-figlet")
def figlet():
    """
    Render the search text using all possible figlet fonts.

    This loops through hundreds of fonts and may take a few seconds to return.
    """
    text = request.environ["SEARCH_TEXT"]
    lines = []
    for font in sorted(FigletFont.getFonts()):
        lines.extend(gopher.formatter.figlet(text, font=font).splitlines())
        lines.append(font)
        lines.append("")
    return gopher.render_menu(*lines)


@app.route("/render-tables")
def tables():
    """
    Render an ascii table using all possible styles provided by tabulate.
    """
    data = [
        ("text", "int", "float"),
        ("Cell 1", 100, 1 / 3),
        ("Cell 2", -25, 0.001),
        ("Cell 3", 0, 0),
    ]
    lines = []
    for table_fmt in tabulate_formats:
        lines.append(table_fmt)
        lines.append("")
        lines.append(gopher.formatter.tabulate(data, "firstrow", table_fmt))
        lines.append("\n")
    return gopher.render_menu(*lines)


@app.route("/error/<int:code>/<path:path>")
def error(code, path):
    """
    Endpoint that simulates error behavior for different types of files.
    """
    if code == 500:
        # Will raise a divide by zero error with a stack trace
        return 1 // 0
    else:
        # Return the specified error code through flask
        abort(code)


@app.route("/demo-links")
def demo_links():
    return gopher.render_menu_template("demo_links.gopher")


# This example uses the app's static folder, but you can also point to any
# absolute filepath that you want to serve files from.
static_directory = gopher.serve_directory(app.static_folder, "demo_directory", show_timestamp=True)


@app.route("/demo-directory")
@app.route("/demo-directory/<path:filename>")
def demo_directory(filename=""):
    is_directory, file = static_directory.load_file(filename)
    if is_directory:
        return gopher.render_menu_template("demo_directory.gopher", filename=filename, listing=file)
    else:
        return file


@app.route("/demo-errors")
def demo_errors():
    return gopher.render_menu_template("demo_errors.gopher")


@app.route("/demo-session", defaults={"action": None})
@app.route("/demo-session/<action>")
def demo_session(action):
    if action == "create":
        session["id"] = request.environ["SEARCH_TEXT"]
    elif action == "delete":
        session.clear()
    return gopher.render_menu_template("demo_session.gopher", action=action)


@app.route("/demo-formatting")
def demo_formatting():
    table_data = [
        ("text", "int", "float"),
        ("Cell 1", 100, 1 / 3),
        ("Cell 2", -25, 0.001),
        ("Cell 3", 0, 0),
    ]
    return gopher.render_menu_template("demo_formatting.gopher", table_data=table_data)


@app.route("/demo-environ")
def demo_environ():
    environ_table = [("Field", "Value")]
    for key, val in sorted(request.environ.items()):
        if not key.startswith(("werkzeug", "wsgi")):
            environ_table.append((key, val))

    return gopher.render_menu_template("demo_environ.gopher", environ_table=environ_table)


@app.route("/demo-form", defaults={"field": None})
@app.route("/demo-form/<field>")
def demo_form(field):
    form_fields = OrderedDict(
        [
            ("first_name", "First name"),
            ("last_name", "Last name"),
            ("email", "Email"),
            ("phone", "Phone number"),
            ("address", "Address"),
        ]
    )

    # Check if there was a new field added to the request
    request_query = request.args.to_dict()

    if field in form_fields:
        request_query[field] = request.environ["SEARCH_TEXT"]

    # Build the form using the currently populated fields
    lines = []
    for name, description in form_fields.items():
        if name in request_query:
            lines.append(f"{description:<13}: {request_query[name]}")
        else:
            url = url_for("demo_form", _external=False, field=name, **request_query)
            lines.append(gopher.menu.query(f"{description:<13}:", url))

    # Add the buttons at the bottom of the form
    lines.append("")
    if request_query:
        lines.append(gopher.menu.dir("clear", url_for("demo_form")))
    else:
        lines.append("clear")
    if request_query.keys() == form_fields.keys():
        url = url_for("demo_form", _external=False, field="submit", **request_query)
        lines.append(gopher.menu.dir("submit", url))
    else:
        lines.append("submit")

    # Show the query data if the "submit" button was pressed
    if field == "submit":
        lines.append("")
        lines.append("Submitted form data:")
        lines.append(json.dumps(request_query, indent=4, sort_keys=True))

    form = "\r\n".join(lines)
    return gopher.render_menu_template("demo_form.gopher", form=form)


if __name__ == "__main__":
    app.run(
        host=app.config["HOST"],
        port=app.config["PORT"],
        threaded=app.config["THREADED"],
        processes=app.config["PROCESSES"],
        request_handler=GopherRequestHandler,
    )
