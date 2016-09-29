# coding=utf-8
"""
Module
"""
from __future__ import absolute_import

import copy

import pytest
from datacube.index.postgres._fields import NumericRangeDocField
from datacube.model import Range

_DATASET_METADATA = {
    'id': 'f7018d80-8807-11e5-aeaa-1040f381a756',
    'instrument': {'name': 'TM'},
    'platform': {
        'code': 'LANDSAT_5',
        'label': 'Landsat 5'
    },
    'size_bytes': 4550,
    'product_type': 'NBAR',
    'bands': {
        '1': {
            'type': 'reflective',
            'cell_size': 25.0,
            'path': 'product/LS8_OLITIRS_NBAR_P54_GALPGS01-002_112_079_20140126_B1.tif',
            'label': 'Coastal Aerosol',
            'number': '1'
        },
        '2': {
            'type': 'reflective',
            'cell_size': 25.0,
            'path': 'product/LS8_OLITIRS_NBAR_P54_GALPGS01-002_112_079_20140126_B2.tif',
            'label': 'Visible Blue',
            'number': '2'
        },
        '3': {
            'type': 'reflective',
            'cell_size': 25.0,
            'path': 'product/LS8_OLITIRS_NBAR_P54_GALPGS01-002_112_079_20140126_B3.tif',
            'label': 'Visible Green',
            'number': '3'
        },
    }
}


def test_metadata_indexes_views_exist(db, default_metadata_type):
    """
    :type db: datacube.index.postgres._api.PostgresDb
    :type default_metadata_type: datacube.model.MetadataType
    """
    # Ensure indexes were created for the eo metadata type (following the naming conventions):
    assert _object_exists(db, 'dix_eo_platform')

    # Ensure view was created (following naming conventions)
    assert _object_exists(db, 'dv_eo_dataset')


def test_dataset_indexes_views_exist(db, ls5_nbar_gtiff_type):
    """
    :type db: datacube.index.postgres._api.PostgresDb
    :type ls5_nbar_gtiff_type: datacube.model.DatasetType
    """
    assert ls5_nbar_gtiff_type.name == 'ls5_nbart_p54_gtiff'

    # Ensure field indexes were created for the dataset type (following the naming conventions):
    assert _object_exists(db, "dix_ls5_nbart_p54_gtiff_orbit")

    # Ensure it does not create a 'platform' index, because that's a fixed field
    # (ie. identical in every dataset of the type)
    assert not _object_exists(db, "dix_ls5_nbart_p54_gtiff_platform")

    # Ensure view was created (following naming conventions)
    assert _object_exists(db, 'dv_ls5_nbart_p54_gtiff_dataset')


def test_dataset_composit_indexes_exist(db, ls5_nbar_gtiff_type):
    # This type has fields named lat/lon/time, so composite indexes should now exist for them:
    # (following the naming conventions)
    assert _object_exists(db, "dix_ls5_nbart_p54_gtiff_time_lat_lon")
    assert _object_exists(db, "dix_ls5_nbart_p54_gtiff_lat_lon_time")

    # But no individual field indexes for these
    assert not _object_exists(db, "dix_ls5_nbart_p54_gtiff_lat")
    assert not _object_exists(db, "dix_ls5_nbart_p54_gtiff_lon")
    assert not _object_exists(db, "dix_ls5_nbart_p54_gtiff_time")


def _object_exists(db, index_name):
    val = db._connection.execute("SELECT to_regclass('agdc.%s')" % index_name).scalar()
    return val == ('agdc.%s' % index_name)


def test_idempotent_add_dataset_type(index, ls5_nbar_gtiff_type, ls5_nbar_gtiff_doc):
    """
    :type ls5_nbar_gtiff_type: datacube.model.DatasetType
    :type index: datacube.index._api.Index
    """
    assert index.datasets.types.get_by_name(ls5_nbar_gtiff_type.name) is not None

    # Re-add should have no effect, because it's equal to the current one.
    index.datasets.types.add_document(ls5_nbar_gtiff_doc)

    # But if we add the same type with differing properties we should get an error:
    different_telemetry_type = copy.deepcopy(ls5_nbar_gtiff_doc)
    different_telemetry_type['metadata']['ga_label'] = 'something'
    with pytest.raises(ValueError):
        index.datasets.types.add_document(different_telemetry_type)

        # TODO: Support for adding/changing search fields?


def test_update_dataset_type(index, ls5_nbar_gtiff_type, ls5_nbar_gtiff_doc, default_metadata_type_doc):
    """
    :type ls5_nbar_gtiff_type: datacube.model.DatasetType
    :type index: datacube.index._api.Index
    """
    assert index.datasets.types.get_by_name(ls5_nbar_gtiff_type.name) is not None

    # Update with a new description
    ls5_nbar_gtiff_doc['description'] = "New description"
    index.datasets.types.update_document(ls5_nbar_gtiff_doc)
    # Ensure was updated
    assert index.datasets.types.get_by_name(ls5_nbar_gtiff_type.name).definition['description'] == "New description"

    # Remove some match rules (looser rules -- that match more datasets -- should be allowed)
    assert 'format' in ls5_nbar_gtiff_doc['metadata']
    del ls5_nbar_gtiff_doc['metadata']['format']['name']
    del ls5_nbar_gtiff_doc['metadata']['format']
    index.datasets.types.update_document(ls5_nbar_gtiff_doc)
    # Ensure was updated
    updated_type = index.datasets.types.get_by_name(ls5_nbar_gtiff_type.name)
    assert updated_type.definition['metadata'] == ls5_nbar_gtiff_doc['metadata']

    # Specifying metadata type definition (rather than name) should be allowed
    full_doc = copy.deepcopy(ls5_nbar_gtiff_doc)
    full_doc['metadata_type'] = default_metadata_type_doc
    index.datasets.types.update_document(full_doc)

    # Remove fixed field, forcing a new index to be created (as datasets can now differ for the field).
    assert not _object_exists(index._db, 'dix_ls5_nbart_p54_gtiff_product_type')
    del ls5_nbar_gtiff_doc['metadata']['product_type']
    index.datasets.types.update_document(ls5_nbar_gtiff_doc)
    # Ensure was updated
    assert _object_exists(index._db, 'dix_ls5_nbart_p54_gtiff_product_type')
    updated_type = index.datasets.types.get_by_name(ls5_nbar_gtiff_type.name)
    assert updated_type.definition['metadata'] == ls5_nbar_gtiff_doc['metadata']

    # But if we make metadata more restrictive we get an error:
    different_telemetry_type = copy.deepcopy(ls5_nbar_gtiff_doc)
    assert 'ga_label' not in different_telemetry_type['metadata']
    different_telemetry_type['metadata']['ga_label'] = 'something'
    with pytest.raises(ValueError):
        index.datasets.types.update_document(different_telemetry_type)
    # Check was not updated.
    updated_type = index.datasets.types.get_by_name(ls5_nbar_gtiff_type.name)
    assert 'ga_label' not in updated_type.definition['metadata']

    # But works when unsafe updates are allowed.
    index.datasets.types.update_document(different_telemetry_type, allow_unsafe_updates=True)
    updated_type = index.datasets.types.get_by_name(ls5_nbar_gtiff_type.name)
    assert updated_type.definition['metadata']['ga_label'] == 'something'


def test_update_metadata_type(index, default_metadata_type_docs, default_metadata_type):
    """
    :type default_metadata_type_docs: list[dict]
    :type index: datacube.index._api.Index
    """
    mt_doc = [d for d in default_metadata_type_docs if d['name'] == default_metadata_type.name][0]

    assert index.metadata_types.get_by_name(mt_doc['name']) is not None

    # Update with no changes should work.
    index.metadata_types.update_document(mt_doc)

    # Add search field
    mt_doc['dataset']['search_fields']['testfield'] = {
        'description': "Field added for testing",
        'offset': ['test']
    }

    # TODO: Able to remove fields?
    # Indexes will be difficult to handle, as dropping them may affect other users. But leaving them there may
    # lead to issues if a different field is created with the same name.

    index.metadata_types.update_document(mt_doc)
    # Ensure was updated
    updated_type = index.metadata_types.get_by_name(mt_doc['name'])
    assert 'testfield' in updated_type.dataset_fields

    # But if we change an existing field type we get an error:
    different_mt_doc = copy.deepcopy(mt_doc)
    different_mt_doc['dataset']['search_fields']['time']['type'] = 'numeric-range'
    with pytest.raises(ValueError):
        index.metadata_types.update_document(different_mt_doc)

    # But works when unsafe updates are allowed.
    index.metadata_types.update_document(different_mt_doc, allow_unsafe_updates=True)
    updated_type = index.metadata_types.get_by_name(mt_doc['name'])
    assert isinstance(updated_type.dataset_fields['time'], NumericRangeDocField)


def test_filter_types_by_fields(index, ls5_nbar_gtiff_type):
    """
    :type ls5_nbar_gtiff_type: datacube.model.DatasetType
    :type index: datacube.index._api.Index
    """
    assert index.datasets.types
    res = list(index.datasets.types.get_with_fields(['lat', 'lon', 'platform']))
    assert res == [ls5_nbar_gtiff_type]

    res = list(index.datasets.types.get_with_fields(['lat', 'lon', 'platform', 'favorite_icecream']))
    assert len(res) == 0


def test_filter_types_by_search(index, ls5_nbar_gtiff_type):
    """
    :type ls5_nbar_gtiff_type: datacube.model.DatasetType
    :type index: datacube.index._api.Index
    """
    assert index.datasets.types

    # No arguments, return all.
    res = list(index.datasets.types.search())
    assert res == [ls5_nbar_gtiff_type]

    # Matching fields
    res = list(index.datasets.types.search(
        product_type='nbart',
        product='ls5_nbart_p54_gtiff'
    ))
    assert res == [ls5_nbar_gtiff_type]

    # Matching fields and non-available fields
    res = list(index.datasets.types.search(
        product_type='nbart',
        product='ls5_nbart_p54_gtiff',
        lat=Range(142.015625, 142.015625),
        lon=Range(-12.046875, -12.046875)
    ))
    assert res == []

    # Matching fields and available fields
    [(res, q)] = list(index.datasets.types.search_robust(
        product_type='nbart',
        product='ls5_nbart_p54_gtiff',
        lat=Range(142.015625, 142.015625),
        lon=Range(-12.046875, -12.046875)
    ))
    assert res == ls5_nbar_gtiff_type
    assert 'lat' in q
    assert 'lon' in q

    # Or expression test
    res = list(index.datasets.types.search(
        product_type=['nbart', 'nbar'],
    ))
    assert res == [ls5_nbar_gtiff_type]

    # Mismatching fields
    res = list(index.datasets.types.search(
        product_type='nbar',
    ))
    assert res == []
