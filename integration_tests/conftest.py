# coding=utf-8
"""
Common methods for index integration tests.
"""
from __future__ import absolute_import

import os
import shutil
from pathlib import Path

import pytest
import rasterio

from datacube import ui
from datacube.config import LocalConfig
from datacube.index._api import Index, _DEFAULT_COLLECTIONS_FILE
from datacube.index.postgres import PostgresDb
from datacube.index.postgres.tables._core import ensure_db, SCHEMA_NAME

_TELEMETRY_COLLECTION_DESCRIPTOR = Path(__file__).parent.joinpath('telemetry-collection.yaml')
_EXAMPLE_LS5_NBAR = Path(__file__).parent.joinpath('example-ls5-nbar.yaml')


@pytest.fixture
def local_config(tmpdir):
    default = os.path.join(os.path.split(os.path.realpath(__file__))[0], 'agdcintegration.conf')
    user = os.path.expanduser('~/.datacube_integration.conf')
    config = LocalConfig.find([default, user])
    config._config.set('locations', u'testdata', 'file://' + str(tmpdir.mkdir('testdata')))
    return config


@pytest.fixture
def db(local_config):
    db = PostgresDb.from_config(local_config)
    # Drop and recreate tables so our tests have a clean db.
    db._connection.execute('drop schema if exists %s cascade;' % SCHEMA_NAME)
    ensure_db(db._connection, db._engine)
    return db


@pytest.fixture
def index(db, local_config):
    """
    :type db: datacube.index.postgres._api.PostgresDb
    """
    return Index(db, local_config)


def create_empty_geotiff(path):
    metadata = {'count': 1,
                'crs': 'EPSG:28355',
                'driver': 'GTiff',
                'dtype': 'int16',
                'height': 8521,
                'nodata': -999.0,
                'transform': [25.0, 0.0, 638000.0, 0.0, -25.0, 6276000.0],
                'width': 9721}
    with rasterio.open(path, 'w', **metadata) as dst:
        pass


@pytest.fixture
def example_ls5_dataset(tmpdir):
    # Based on LS5_TM_NBAR_P54_GANBAR01-002_090_084_19900302
    dataset_dir = tmpdir.mkdir('ls5_dataset')
    shutil.copy(str(_EXAMPLE_LS5_NBAR), str(dataset_dir.join('agdc-metadata.yaml')))

    # Write geotiffs
    geotiff_name = "LS5_TM_NBAR_P54_GANBAR01-002_090_084_19900302_B{}0.tif"
    scene_dir = dataset_dir.mkdir('product').mkdir('scene01')
    scene_dir.join('report.txt').write('Example')
    for num in (1, 2, 3):
        path = scene_dir.join(geotiff_name.format(num))
        create_empty_geotiff(str(path))

    return Path(str(dataset_dir))


@pytest.fixture
def default_collection_doc():
    return list(ui.read_documents(_DEFAULT_COLLECTIONS_FILE))[0][1]


@pytest.fixture
def default_collection(index, default_collection_doc):
    """
    :type index: datacube.index._api.Index
    """
    return index.collections.add(default_collection_doc)


@pytest.fixture
def telemetry_collection_doc():
    return list(ui.read_documents(_TELEMETRY_COLLECTION_DESCRIPTOR))[0][1]


@pytest.fixture
def telemetry_collection(index, telemetry_collection_doc):
    """
    :type index: datacube.index._api.Index
    :type telemetry_collection_doc: dict
    """
    return index.collections.add(telemetry_collection_doc)


@pytest.fixture
def ls5_nbar_mapping(db, index):
    """
    :type db: datacube.index.postgres._api.PostgresDb
    :type index: datacube.index._api.Index
    :type storage_type_30m: datacube.model.StorageType
    :rtype: datacube.model.StorageMapping
    """
    id_ = db.ensure_storage_mapping(
        storage_type={
            'driver': 'NetCDF CF',
            'chunking': {'time': 1, 'latitude': 400, 'longitude': 400},
            'dimension_order': ['time', 'latitude', 'longitude'],
            'crs': 'GEOGCS["WGS 84",\n'
                   '    DATUM["WGS_1984",\n'
                   '        SPHEROID["WGS 84",6378137,298.257223563,\n'
                   '            AUTHORITY["EPSG","7030"]],\n'
                   '        AUTHORITY["EPSG","6326"]],\n'
                   '    PRIMEM["Greenwich",0,\n'
                   '        AUTHORITY["EPSG","8901"]],\n'
                   '    UNIT["degree",0.0174532925199433,\n'
                   '        AUTHORITY["EPSG","9122"]],\n'
                   '    AUTHORITY["EPSG","4326"]]\n',
            'resolution': {'longitude': 0.00025, 'latitude': -0.00025},
            'tile_size': {'longitude': 1.0, 'latitude': 1.0}
        },
        name='ls5_nbar',
        description='Test LS5 Nbar 30m bands',
        location_name='eotiles',
        file_path_template='/file_path_template/file.nc',
        dataset_metadata={},
        measurements={
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
        },
    )
    return index.mappings.get(id_)
