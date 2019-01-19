"""
Flask-Gopher
------------

A Flask extension to support the Gopher Protocol
"""
import codecs
import setuptools
from version import __version__ as version


def long_description():
    with codecs.open('README.md', encoding='utf8') as f:
        return f.read()


setuptools.setup(
    name='Flask-Gopher',
    version=version,
    url='https://github.com/michael-lazar/flask-gopher',
    license='GPL-3.0',
    author='Michael Lazar',
    author_email='lazar.michael22@gmail.com',
    description='A Flask extension to support the Gopher Protocol',
    long_description=long_description(),
    packages=['flask_gopher'],
    zip_safe=False,
    include_package_data=True,
    platforms='any',
    install_requires=[
        'Flask>=0.11',
        # pyfiglet v0.8.0 removes a bunch of fonts due to licensing issues :(
        'pyfiglet<=0.7.6',
        'tabulate',
        'pyopenssl',
    ],
    test_suite='tests',
    classifiers=[
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ]
)
