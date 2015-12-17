# coding=utf-8
"""
Common methods for UI code.
"""
from __future__ import absolute_import

import functools
import gzip
import json
import logging
import pathlib
from itertools import product

import click
import pkg_resources
import yaml

_DOCUMENT_SUFFIX_TYPES = ('.yaml', '.yml', '.json')
# Both compressed (*.gz) and uncompressed.
_ALL_SUPPORTED_DOC_SUFFIXES = tuple(a[0] + a[1] for a in product(_DOCUMENT_SUFFIX_TYPES, ('', '.gz')))


def is_supported_document_type(path):
    """
    Does a document path look like a supported type?
    :type path: pathlib.Path
    :rtype: bool
    >>> from pathlib import Path
    >>> is_supported_document_type(Path('/tmp/something.yaml'))
    True
    >>> is_supported_document_type(Path('/tmp/something.YML'))
    True
    >>> is_supported_document_type(Path('/tmp/something.yaml.gz'))
    True
    >>> is_supported_document_type(Path('/tmp/something.tif'))
    False
    >>> is_supported_document_type(Path('/tmp/something.tif.gz'))
    False
    """
    return any([str(path).lower().endswith(suffix) for suffix in _ALL_SUPPORTED_DOC_SUFFIXES])


def get_metadata_path(dataset_path):
    """
    Find a metadata path for a given input/dataset path.

    :type dataset_path: pathlib.Path
    :rtype: Path
    """

    # They may have given us a metadata file directly.
    if dataset_path.is_file() and is_supported_document_type(dataset_path):
        return dataset_path

    # Otherwise there may be a sibling file with appended suffix '.agdc-md.yaml'.
    expected_name = dataset_path.parent.joinpath('{}.agdc-md'.format(dataset_path.name))
    found = _find_any_metadata_suffix(expected_name)
    if found:
        return found

    # Otherwise if it's a directory, there may be an 'agdc-metadata.yaml' file describing all contained datasets.
    if dataset_path.is_dir():
        expected_name = dataset_path.joinpath('agdc-metadata')
        found = _find_any_metadata_suffix(expected_name)
        if found:
            return found

    raise ValueError('No metadata found for input %r' % dataset_path)


def _find_any_metadata_suffix(path):
    """
    Find any metadata files that exist with the given file name/path.
    (supported suffixes are tried on the name)
    :type path: pathlib.Path
    """
    existing_paths = list(filter(is_supported_document_type, path.parent.glob(path.name + '*')))
    if not existing_paths:
        return None

    if len(existing_paths) > 1:
        raise ValueError('Multiple matched metadata files: {!r}'.format(existing_paths))

    return existing_paths[0]


def read_documents(*paths):
    """
    Read & parse documents from the filesystem (yaml or json).

    Note that a single yaml file can contain multiple documents.

    :type paths: list[pathlib.Path]
    :rtype: tuple[(pathlib.Path, dict)]
    """
    for path in paths:
        suffix = path.suffix.lower()

        # If compressed, open as gzip stream.
        opener = open
        if suffix == '.gz':
            suffix = path.suffixes[-2].lower()
            opener = gzip.open

        if suffix in ('.yaml', '.yml'):
            for parsed_doc in yaml.safe_load_all(opener(str(path), 'r')):
                yield path, parsed_doc
        elif suffix == '.json':
            yield path, json.load(opener(str(path), 'r'))
        else:
            raise ValueError('Unknown document type for {}; expected one of {!r}.'
                             .format(path.name, _ALL_SUPPORTED_DOC_SUFFIXES))


def _print_version(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return

    #: pylint: disable=not-callable
    version = pkg_resources.require('datacube')[0].version
    click.echo(
        '{prog}, version {version}'.format(
            prog='Data Cube',
            version=version
        )
    )
    ctx.exit()


def compose(*functions):
    """
    >>> compose(
    ...     lambda x: x+1,
    ...     lambda y: y+2
    ... )(1)
    4
    """

    def compose2(f, g):
        return lambda x: f(g(x))

    return functools.reduce(compose2, functions, lambda x: x)


def _init_logging(ctx, param, value):
    logging_level = logging.WARN - 10 * value
    logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logging_level)
    logging.getLogger('datacube').setLevel(logging_level)


def _log_queries(ctx, param, value):
    if value:
        logging.getLogger('sqlalchemy.engine').setLevel('INFO')

# This is a function, so it's valid to be lowercase.
#: pylint: disable=invalid-name
common_cli_options = compose(
    click.option('--version', is_flag=True,
                 callback=_print_version, expose_value=False, is_eager=True),
    click.option('--verbose', '-v', count=True, callback=_init_logging,
                 expose_value=False,
                 help="Use multiple times for more verbosity"),
    click.option('--log-queries', is_flag=True, callback=_log_queries,
                 expose_value=False,
                 help="Print database queries.")
)
