# coding=utf-8
"""
Module
"""
from __future__ import absolute_import

import copy

import pytest

from datacube.model import Dataset


_STORAGE_TYPE = {
    'name': '30m_bands',
    'driver': 'NetCDF CF',
    'base_path': '/short/v10/dra547/tmp/7/',
    'chunking': {'t': 1, 'x': 500, 'y': 500},
    'dimension_order': ['t', 'y', 'x'],
    'filename_format': '{platform[code]}_{instrument[name]}_{lons[0]}_{lats[0]}_{creation_dt:%Y-%m-%dT%H-%M-%S.%f}.nc',
    'projection': {
        'spatial_ref': 'GEOGCS["WGS 84",\n'
                       '    DATUM["WGS_1984",\n'
                       '        SPHEROID["WGS 84",6378137,298.257223563,\n'
                       '            AUTHORITY["EPSG","7030"]],\n'
                       '        AUTHORITY["EPSG","6326"]],\n'
                       '    PRIMEM["Greenwich",0,\n'
                       '        AUTHORITY["EPSG","8901"]],\n'
                       '    UNIT["degree",0.0174532925199433,\n'
                       '        AUTHORITY["EPSG","9122"]],\n'
                       '    AUTHORITY["EPSG","4326"]]\n'
    },
    'resolution': {'x': 0.00025, 'y': -0.00025},
    'tile_size': {'x': 1.0, 'y': -1.0}
}

_15M_STORAGE_TYPE = {
    'name': '15m_bands',
    'driver': 'NetCDF CF',
    'base_path': '/short/v10/dra547/tmp/5/',
    'chunking': {'t': 1, 'x': 500, 'y': 500},
    'dimension_order': ['t', 'y', 'x'],
    'filename_format': '{platform[code]}_{instrument[name]}_{lons[0]}_{lats[0]}_{creation_dt:%Y-%m-%dT%H-%M-%S.%f}.nc',
    'projection': {
        'spatial_ref': 'epsg:1234'
    },
    'resolution': {'x': 0.00015, 'y': -0.00015},
    'tile_size': {'x': 1.0, 'y': -1.0}
}


_STORAGE_MAPPING = {
    'name': 'LS5 NBAR',
    'match': {
        'metadata':
            {
                'instrument': {'name': 'TM'},
                'platform': {'code': 'LANDSAT_5'},
                'product_type': 'NBAR'
            }
    },
    'storage': [
        {

            'name': _STORAGE_TYPE['name'],
            'location_name': 'eotiles',
            'file_path_template': '/file_path_template/file.nc',
            'measurements': {
                '1': {'dtype': 'int16',
                      'fill_value': -999,
                      'resampling_method': 'cubic',
                      'varname': 'band_1'},
                '2': {'dtype': 'int16',
                      'fill_value': -999,
                      'resampling_method': 'cubic',
                      'varname': 'band_2'},
                '3': {'dtype': 'int16',
                      'fill_value': -999,
                      'resampling_method': 'cubic',
                      'varname': 'band_3'},
            }
        }
    ]
}

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


def test_add_storage_type(index, local_config):
    """
    :type local_config: datacube.config.LocalConfig
    :type index: datacube.index._api.Index
    """
    dataset = Dataset('eo', _DATASET_METADATA, '/tmp/somepath.yaml')

    storage_mappings = index.mappings.get_for_dataset(dataset)
    assert len(storage_mappings) == 0

    index.storage_types.add(_STORAGE_TYPE)
    index.mappings.add(_STORAGE_MAPPING)

    # The properties of the dataset should match.
    storage_mappings = index.mappings.get_for_dataset(dataset)
    assert len(storage_mappings) == 1

    mapping = storage_mappings[0]
    assert mapping.name == 'LS5 NBAR'

    assert mapping.storage_pattern == local_config.location_mappings['eotiles'] + '/file_path_template/file.nc'
    assert mapping.match.metadata == _STORAGE_MAPPING['match']['metadata']
    assert mapping.measurements == _STORAGE_MAPPING['storage'][0]['measurements']

    storage_type = mapping.storage_type
    assert storage_type.name == '30m_bands'
    assert storage_type.driver == 'NetCDF CF'

    expected_descriptor = copy.deepcopy(_STORAGE_TYPE)
    expected_descriptor.pop('name')
    expected_descriptor.pop('driver')
    assert storage_type.descriptor == expected_descriptor

    # A different dataset should not match our storage types
    dataset = Dataset('eo', {
        'instrument': {'name': 'OLI'},
        'platform': {'code': 'LANDSAT_8'},
        'product_type': 'NBAR'
    }, '/tmp/other.yaml')
    storage_mappings = index.mappings.get_for_dataset(dataset)
    assert len(storage_mappings) == 0


def test_idempotent_add_type(index, local_config):
    """
    :type local_config: datacube.config.LocalConfig
    :type index: datacube.index._api.Index
    """
    index.storage_types.add(_STORAGE_TYPE)
    # Second time, no effect, because it's equal.
    index.storage_types.add(_STORAGE_TYPE)

    # But if we add the same type (name) with differing properties we should get an error:
    different_storage_type = copy.deepcopy(_STORAGE_TYPE)
    different_storage_type['base_path'] = '/tmp/new_base_path'
    with pytest.raises(ValueError):
        index.storage_types.add(different_storage_type)


def test_idempotent_add_mapping(index, local_config):
    """
    :type local_config: datacube.config.LocalConfig
    :type index: datacube.index._api.Index
    """
    index.storage_types.add(_STORAGE_TYPE)

    index.mappings.add(_STORAGE_MAPPING)
    # Second time, no effect, because it's equal.
    index.mappings.add(_STORAGE_MAPPING)

    # We can add new type mappings without issue.
    index.storage_types.add(_15M_STORAGE_TYPE)
    different_storage_mapping = copy.deepcopy(_STORAGE_MAPPING)
    different_storage_mapping['storage'].append(
        {
            'name': _15M_STORAGE_TYPE['name'],
            'location_name': 'eotiles',
            'file_path_template': '/file_path_template/file2.nc',
            'measurements': {},
        }
    )
    index.mappings.add(different_storage_mapping)
    mapping = index.mappings.get_by_name(_15M_STORAGE_TYPE['name'], _STORAGE_MAPPING['name'])
    assert str(mapping.filename_pattern) == '/file_path_template/file2.nc'
    assert mapping.measurements == {}

    # But if we add the same mapping with differing properties we should get an error:
    different_storage_mapping = copy.deepcopy(_STORAGE_MAPPING)
    different_storage_mapping['storage'][0]['location_name'] = 'new_location'
    with pytest.raises(ValueError):
        index.mappings.add(different_storage_mapping)


def test_collection_indexes_views_exist(db, telemetry_collection):
    """
    :type db: datacube.index.postgres._api.PostgresDb
    :type telemetry_collection: datacube.model.Collection
    """
    # Ensure indexes were created for the telemetry collection (following the naming conventions):
    val = db._connection.execute("SELECT to_regclass('agdc.ix_field_landsat_telemetry_dataset_satellite')").scalar()
    assert val == 'agdc.ix_field_landsat_telemetry_dataset_satellite'

    # Ensure view was created (following naming conventions)
    val = db._connection.execute("SELECT to_regclass('agdc.landsat_telemetry_dataset')").scalar()
    assert val == 'agdc.landsat_telemetry_dataset'
