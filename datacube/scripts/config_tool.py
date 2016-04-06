#!/usr/bin/env python
# coding=utf-8
"""
Configure the Data Cube from the command-line.
"""
from __future__ import absolute_import

import logging
import sys
from pathlib import Path

import click
from click import echo

from datacube.index import index_connect
from datacube.ui import read_documents
from datacube.ui.click import global_cli_options, pass_index, pass_config, CLICK_SETTINGS

_LOG = logging.getLogger(__name__)

PASS_INDEX = pass_index(app_name='datacube-config')


@click.group(help="Configure the Data Cube", context_settings=CLICK_SETTINGS)
@global_cli_options
def cli():
    pass


@cli.group(help='Initialise the database')
def database():
    pass


@database.command('init', help='Initialise the database')
@click.option(
    '--default-collections/--no-default-collections', is_flag=True, default=True,
    help="Add default collections? (default: true)"
)
@click.option(
    '--init-users/--no-init-users', is_flag=True, default=True,
    help="Include user roles and grants. (default: true)"
)
@PASS_INDEX
def database_init(index, default_collections, init_users):
    echo('Initialising database...')
    was_created = index.init_db(with_default_collection=default_collections,
                                with_permissions=init_users)
    if was_created:
        echo('Done.')
    else:
        echo('Updated.')


@cli.group(help='Dataset collections')
def collections():
    pass


@cli.command('check', help='Verify & view current configuration.')
@pass_config
def check(config_file):
    echo('Host: {}:{}'.format(config_file.db_hostname or 'localhost', config_file.db_port or '5432'))
    echo('Database: {}'.format(config_file.db_database))
    echo('User: {}'.format(config_file.db_username))

    echo('\n')
    echo('Attempting connect')
    try:
        index_connect(local_config=config_file)
        echo('Success.')
    #: pylint: disable=broad-except
    except Exception:
        _LOG.exception("Connection error")
        echo('Connection error', file=sys.stderr)
        click.get_current_context().exit(1)


@collections.command('add')
@click.argument('files',
                type=click.Path(exists=True, readable=True, writable=False),
                nargs=-1)
@PASS_INDEX
def collection_add(index, files):
    for descriptor_path, parsed_doc in _read_docs(files):
        index.collections.add(parsed_doc)


@cli.group(help='Storage types')
def storage():
    pass


@storage.command('add')
@click.argument('files',
                type=click.Path(exists=True, readable=True, writable=False),
                nargs=-1)
@PASS_INDEX
@click.pass_context
def add_storage_types(ctx, index, files):
    for descriptor_path, parsed_doc in _read_docs(files):
        try:
            index.storage.types.add(parsed_doc)
            echo('Added "%s"' % parsed_doc['name'])
        except KeyError as ke:
            _LOG.exception(ke)
            _LOG.error('Invalid storage type definition: %s', descriptor_path)
            ctx.exit(1)


@storage.command('list')
@PASS_INDEX
def list_storage_types(index):
    """
    :type index: datacube.index._api.Index
    """
    for storage_type in index.storage.types.get_all():
        echo("{m.id:2d}. {m.name:15}: {m.description!s}".format(m=storage_type))


def _read_docs(paths):
    return read_documents(*(Path(f) for f in paths))


if __name__ == '__main__':
    cli()
