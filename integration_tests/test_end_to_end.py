from __future__ import absolute_import

import sys
import warnings
from past.builtins import basestring
from datetime import datetime
from pathlib import Path
from subprocess import call, check_output, PIPE, CalledProcessError

import six
import netCDF4
import numpy as np
import pytest

import yaml
from click.testing import CliRunner

import datacube.scripts.run_ingest
import datacube.scripts.config_tool
from .conftest import LS5_NBAR_NAME, LS5_NBAR_ALBERS_NAME, EXAMPLE_LS5_DATASET_ID


PROJECT_ROOT = Path(__file__).parents[1]
CONFIG_SAMPLES = PROJECT_ROOT / 'docs/config_samples/'
LS5_SAMPLES = CONFIG_SAMPLES / 'ga_landsat_5/'
LS5_NBAR_ALBERS_STORAGE_TYPE = LS5_SAMPLES / 'ls5_albers.yaml'

UTILS = PROJECT_ROOT / 'utils'
GA_LS_PREPARE_SCRIPT = UTILS / 'galsprepare.py'

TEST_DATA = PROJECT_ROOT / 'tests' / 'data'
LBG_SCENES = TEST_DATA / 'lbg'
LBG_NBAR = LBG_SCENES / 'LS5_TM_NBAR_P54_GANBAR01-002_090_084_19920323'
LBG_PQ = LBG_SCENES / 'LS5_TM_PQ_P55_GAPQ01-002_090_084_19920323'

ALBERS_ELEMENT_SIZE = 25

LBG_CELL_X = 15
LBG_CELL_Y = -40
LBG_CELL = (LBG_CELL_X, LBG_CELL_Y)


@pytest.mark.usefixtures('default_collection')
def test_end_to_end(global_integration_cli_args, index, example_ls5_dataset):
    """
    Loads two storage mapping configurations, then ingests a sample Landsat 5 scene

    One storage configuration specifies Australian Albers Equal Area Projection,
    the other is simply latitude/longitude.

    The input dataset should be recorded in the index, and two sets of netcdf storage units
    should be created on disk and recorded in the index.
    """

    # Copy scenes to a temp dir?
    # Run galsprepare.py on the NBAR and PQ scenes

    retcode = call(
        [
            'python',
            str(GA_LS_PREPARE_SCRIPT),
            str(LBG_NBAR)
        ],
        stderr=PIPE
    )
    assert retcode == 0

    # Add the LS5 Albers Example
    opts = list(global_integration_cli_args)
    opts.extend(
        [
            '-vv',
            'storage',
            'add',
            str(LS5_NBAR_ALBERS_STORAGE_TYPE)
        ]
    )
    result = CliRunner().invoke(
        datacube.scripts.config_tool.cli,
        opts,
        catch_exceptions=False
    )
    print(result.output)
    assert not result.exception
    assert result.exit_code == 0

    # Run Ingest script on a dataset
    opts = list(global_integration_cli_args)
    opts.extend(
        [
            '-vv',
            'ingest',
            str(LBG_NBAR)
        ]
    )
    result = CliRunner().invoke(
        datacube.scripts.run_ingest.cli,
        opts,
        catch_exceptions=False
    )
    print(result.output)
    assert not result.exception
    assert result.exit_code == 0

    # Run Ingest script on a dataset
    opts = list(global_integration_cli_args)
    opts.extend(
        [
            '-vv',
            'ingest',
            str(LBG_PQ)
        ]
    )
    result = CliRunner().invoke(
        datacube.scripts.run_ingest.cli,
        opts,
        catch_exceptions=False
    )
    print(result.output)
    assert not result.exception
    assert result.exit_code == 0

    check_open_with_api(index)
    check_analytics_list_searchables(index)
    check_get_descriptor(index)
    check_get_data(index)
    check_get_descriptor_data(index)
    check_analytics_create_array(index)
    check_analytics_ndvi_mask_median_expression(index)


def check_open_with_api(index):
    import datacube.api
    api = datacube.api.API(index=index)
    fields = api.list_fields()
    assert 'product' in fields
    descriptor = api.get_descriptor()
    assert 'ls5_nbar_albers' in descriptor
    storage_units = descriptor['ls5_nbar_albers']['storage_units']
    query = {
        'variables': ['blue'],
        'dimensions': {
            'latitude': {'range': (-34, -35)},
            'longitude': {'range': (149, 150)}}
    }
    data = api.get_data(query, storage_units=storage_units)
    assert abs(data['element_sizes'][1] - ALBERS_ELEMENT_SIZE) < .0000001
    assert abs(data['element_sizes'][2] - ALBERS_ELEMENT_SIZE) < .0000001

    data_array = api.get_data_array(storage_type='ls5_nbar_albers', variables=['blue'],
                                    latitude=(-34, -35), longitude=(149, 150))
    assert data_array.size

    dataset = api.get_dataset(storage_type='ls5_nbar_albers', variables=['blue'],
                              latitude=(-34, -35), longitude=(149, 150))
    assert dataset['blue'].size

    data_array_cell = api.get_data_array_by_cell(LBG_CELL, storage_type='ls5_nbar_albers', variables=['blue'])
    assert data_array_cell.size

    data_array_cell = api.get_data_array_by_cell(x_index=LBG_CELL_X, y_index=LBG_CELL_Y,
                                                 storage_type='ls5_nbar_albers', variables=['blue'])
    assert data_array_cell.size

    dataset_cell = api.get_dataset_by_cell(LBG_CELL, storage_type='ls5_nbar_albers', variables=['blue'])
    assert dataset_cell['blue'].size

    dataset_cell = api.get_dataset_by_cell([LBG_CELL], storage_type='ls5_nbar_albers', variables=['blue'])
    assert dataset_cell['blue'].size

    dataset_cell = api.get_dataset_by_cell(x_index=LBG_CELL_X, y_index=LBG_CELL_Y, storage_type='ls5_nbar_albers',
                                           variables=['blue'])
    assert dataset_cell['blue'].size

    tiles = api.list_tiles(x_index=LBG_CELL_X, y_index=LBG_CELL_Y, storage_type='ls5_nbar_albers')
    for tile_query, tile_attrs in tiles:
        dataset = api.get_dataset_by_cell(**tile_query)
        assert dataset['blue'].size


def check_analytics_list_searchables(index):
    from datacube.analytics.analytics_engine import AnalyticsEngine

    a = AnalyticsEngine(index=index)
    result = a.list_searchables()

    assert len(result) > 0
    for storage_type in result:
        assert len(result[storage_type]['bands']) > 0
        assert len(list(result[storage_type]['dimensions'])) > 0
        assert result[storage_type]['instrument']
        assert result[storage_type]['platform']
        assert result[storage_type]['product_type']
        assert result[storage_type]['storage_type']


def check_get_descriptor(index):
    from datetime import datetime
    from datacube.api import API

    g = API(index=index)

    platform = 'LANDSAT_5'
    product = 'nbar'
    var1 = 'red'
    var2 = 'nir'

    data_request_descriptor = {
        'platform': platform,
        'product': product,
        'variables': (var1, var2),
        'dimensions': {
            'longitude': {
                'range': (149.07, 149.18)
            },
            'latitude': {
                'range': (-35.32, -35.28)
            },
            'time': {
                'range': (datetime(1992, 1, 1), datetime(1992, 12, 31))
            }
        }
    }

    d = g.get_descriptor(data_request_descriptor)
    assert 'storage_units' in list(d.values())[0].keys()
    assert 'dimensions' in list(d.values())[0].keys()
    assert 'result_max' in list(d.values())[0].keys()
    assert 'irregular_indices' in list(d.values())[0].keys()
    assert 'variables' in list(d.values())[0].keys()
    assert 'result_min' in list(d.values())[0].keys()
    assert 'result_shape' in list(d.values())[0].keys()

    assert isinstance(list(d.values())[0]['storage_units'], dict)
    assert isinstance(list(d.values())[0]['dimensions'], list)
    assert isinstance(list(d.values())[0]['result_max'], tuple)
    assert isinstance(list(d.values())[0]['irregular_indices'], dict)
    assert isinstance(list(d.values())[0]['result_min'], tuple)
    assert isinstance(list(d.values())[0]['variables'], dict)
    assert isinstance(list(d.values())[0]['result_shape'], tuple)

    assert len(list(d.values())[0]['dimensions']) == \
        len(list(d.values())[0]['dimensions']) == \
        len(list(d.values())[0]['result_shape']) == \
        len(list(d.values())[0]['result_max']) == \
        len(list(d.values())[0]['result_min'])

    for key in list(d.values())[0]['irregular_indices'].keys():
        assert key in list(d.values())[0]['dimensions']

    assert var1 in list(d.values())[0]['variables']
    assert var2 in list(d.values())[0]['variables']

    assert 'datatype_name' in list(d.values())[0]['variables'][var1].keys()
    assert 'nodata_value' in list(d.values())[0]['variables'][var1].keys()

    assert 'datatype_name' in list(d.values())[0]['variables'][var2].keys()
    assert 'nodata_value' in list(d.values())[0]['variables'][var2].keys()

    for su in list(d.values())[0]['storage_units'].values():
        assert 'irregular_indicies' in su
        assert 'storage_max' in su
        assert 'storage_min' in su
        assert 'storage_path' in su
        assert 'storage_shape' in su
        assert isinstance(su['irregular_indicies'], dict)
        assert isinstance(su['storage_max'], tuple)
        assert isinstance(su['storage_min'], tuple)
        assert isinstance(su['storage_path'], basestring)
        assert isinstance(su['storage_shape'], tuple)


def check_get_data(index):
    import numpy as np
    import xarray as xr
    from datetime import datetime
    from datacube.api import API

    g = API(index=index)

    platform = 'LANDSAT_5'
    product = 'nbar'
    var1 = 'red'
    var2 = 'nir'

    data_request_descriptor = {
        'platform': platform,
        'product': product,
        'variables': (var1, var2),
        'dimensions': {
            'longitude': {
                'range': (149.07, 149.18)
            },
            'latitude': {
                'range': (-35.32, -35.28)
            },
            'time': {
                'range': (datetime(1992, 1, 1), datetime(1992, 12, 31))
            }
        }
    }

    d = g.get_data(data_request_descriptor)
    assert 'dimensions' in list(d.keys())
    assert 'arrays' in list(d.keys())
    assert 'element_sizes' in list(d.keys())
    assert 'indices' in list(d.keys())
    assert 'coordinate_reference_systems' in list(d.keys())
    assert 'size' in list(d.keys())

    assert isinstance(d['dimensions'], list)
    assert isinstance(d['arrays'], dict)
    assert isinstance(d['element_sizes'], list)
    assert isinstance(d['indices'], dict)
    assert isinstance(d['coordinate_reference_systems'], list)
    assert isinstance(d['size'], tuple)

    assert len(list(d['dimensions'])) == \
        len(list(d['coordinate_reference_systems'])) == \
        len(list(d['element_sizes'])) == \
        len(list(d['indices'])) == \
        len(list(d['size']))

    for key in list(d['indices'].keys()):
        assert key in list(d['dimensions'])

    assert var1 in list(d['arrays'].keys())
    assert var2 in list(d['arrays'].keys())

    for crs in d['coordinate_reference_systems']:
        assert 'reference_system_definition' in crs
        assert 'reference_system_unit' in crs
        assert isinstance(crs['reference_system_definition'], basestring)
        assert isinstance(crs['reference_system_unit'], basestring)

    for dim in d['indices']:
        assert isinstance(d['indices'][dim], np.ndarray)

    assert isinstance(d['arrays'][var1], xr.DataArray)
    assert isinstance(d['arrays'][var2], xr.DataArray)

    assert d['arrays'][var1].shape == d['size']
    assert d['arrays'][var2].shape == d['size']

    assert d['arrays'][var1].name == var1
    assert d['arrays'][var2].name == var2

    assert len(list(d['arrays'][var1].dims)) == len(list(d['dimensions']))
    assert len(list(d['arrays'][var2].dims)) == len(list(d['dimensions']))

    for dim in list(d['dimensions']):
        assert dim in list(d['arrays'][var1].dims)
        assert dim in list(d['arrays'][var2].dims)


def check_get_descriptor_data(index):
    import numpy as np
    import xarray as xr
    from datetime import datetime
    from datacube.api import API

    g = API(index=index)

    platform = 'LANDSAT_5'
    product = 'nbar'
    var1 = 'red'
    var2 = 'nir'

    data_request_descriptor = {
        'platform': platform,
        'product': product,
        'variables': (var1, var2),
        'dimensions': {
            'longitude': {
                'range': (149.07, 149.18)
            },
            'latitude': {
                'range': (-35.32, -35.28)
            },
            'time': {
                'range': (datetime(1992, 1, 1), datetime(1992, 12, 31))
            }
        }
    }

    d1 = g.get_descriptor(data_request_descriptor)
    d2 = g.get_data(data_request_descriptor)

    assert list(d1.values())[0]['result_shape'] == \
        d2['size'] == \
        d2['arrays'][var1].shape == \
        d2['arrays'][var2].shape


def check_analytics_create_array(index):
    from datetime import datetime
    from datacube.analytics.analytics_engine import AnalyticsEngine
    from datacube.execution.execution_engine import ExecutionEngine

    a = AnalyticsEngine(index=index)
    e = ExecutionEngine(index=index)

    platform = 'LANDSAT_5'
    product = 'nbar'
    var1 = 'red'
    var2 = 'nir'

    # Lake Burley Griffin
    dimensions = {'x':    {'range': (149.07, 149.18)},
                  'y':    {'range': (-35.32, -35.28)},
                  'time': {'range': (datetime(1992, 1, 1), datetime(1992, 12, 31))}}

    arrays = a.create_array((platform, product), [var1, var2], dimensions, 'get_data')

    e.execute_plan(a.plan)

    assert e.cache['get_data']


def check_analytics_ndvi_mask_median_expression(index):
    from datetime import datetime
    from datacube.analytics.analytics_engine import AnalyticsEngine
    from datacube.execution.execution_engine import ExecutionEngine

    a = AnalyticsEngine(index=index)
    e = ExecutionEngine(index=index)

    platform = 'LANDSAT_5'
    product = 'nbar'
    var1 = 'nir'
    var2 = 'red'
    pq_product = 'pqa'
    pq_var = 'pixelquality'

    # Lake Burley Griffin
    dimensions = {'x':    {'range': (149.07, 149.18)},
                  'y':    {'range': (-35.32, -35.28)},
                  'time': {'range': (datetime(1992, 1, 1), datetime(1992, 12, 31))}}

    b40 = a.create_array((platform, product), [var1], dimensions, 'b40')
    b30 = a.create_array((platform, product), [var2], dimensions, 'b30')
    pq = a.create_array((platform, pq_product), [pq_var], dimensions, 'pq')

    ndvi = a.apply_expression([b40, b30], '((array1 - array2) / (array1 + array2))', 'ndvi')
    mask = a.apply_expression([ndvi, pq], 'array1{(array2 == 32767) | (array2 == 16383) | (array2 == 2457)}', 'mask')
    median_t = a.apply_expression(mask, 'median(array1, 0)', 'medianT')

    result = e.execute_plan(a.plan)
    assert e.cache['ndvi']
    assert e.cache['mask']
    assert e.cache['medianT']
