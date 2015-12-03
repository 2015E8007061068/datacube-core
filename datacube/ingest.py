# coding=utf-8
"""
Ingest datasets into the agdc.
"""
from __future__ import absolute_import

import logging

from datacube import ui
from . import storage
from .index import index_connect

_LOG = logging.getLogger(__name__)


def _expected_metadata_path(dataset_path):
    """
    Get the path where we expect a metadata file for this dataset.

    (only supports eo metadata docs at the moment)

    :type dataset_path: pathlib.Path
    :rtype: Path
    """

    # - A dataset directory expects file 'agdc-metadata.yaml'.
    # - A dataset file expects a sibling file with suffix '.agdc-md.yaml'.
    # - Otherwise they gave us the metadata file directly.

    if dataset_path.is_file():
        if ui.is_supported_document_type(dataset_path):
            return dataset_path

        return dataset_path.parent.joinpath('{}.agdc-md.yaml'.format(dataset_path.name))

    elif dataset_path.is_dir():
        return dataset_path.joinpath('agdc-metadata.yaml')

    raise ValueError('Unhandled path type for %r' % dataset_path)


def ingest(path, index=None):
    """
    Add a dataset to the index and then create storage units from it

    :type index: datacube.index._api.Index
    :type path: pathlib.Path
    :rtype: datacube.model.Dataset
    """
    index = index or index_connect()

    metadata_path = _expected_metadata_path(path)
    if not metadata_path or not metadata_path.exists():
        raise ValueError('No supported metadata docs found for dataset {}'.format(path))

    for metadata_path, metadata_doc in ui.read_documents(metadata_path):
        dataset = index.datasets.add(metadata_doc, metadata_path)

        _write_missing_storage_units(index, dataset)

        _LOG.info('Completed dataset %s', path)


def _write_missing_storage_units(index, dataset):
    """
    Ensure all storage units have been written for the dataset.
    :type index: datacube.index._api.Index
    :type dataset: datacube.model.Dataset
    """
    # TODO: Query for missing storage units, not all storage units.
    storage_mappings = index.mappings.get_for_dataset(dataset)
    _LOG.info('%s applicable storage mapping(s)', len(storage_mappings))
    _LOG.debug('Storage mappings: %s', storage_mappings)
    if storage_mappings:
        storage_units = storage.store(storage_mappings, dataset)
        index.storage.add_many(storage_units)
