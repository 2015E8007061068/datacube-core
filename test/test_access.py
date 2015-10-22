#    Copyright 2015 Geoscience Australia
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.


from __future__ import absolute_import, division, print_function
from builtins import *

import numpy

from cubeaccess.core import Coordinate, Variable, StorageUnitDimensionProxy, StorageUnitStack
from cubeaccess.storage import NetCDF4StorageUnit, GeoTifStorageUnit, FauxStorageUnit
from cubeaccess.indexing import Range


ds1 = FauxStorageUnit({
    't': Coordinate(numpy.int, 100, 400, 4),
    'y': Coordinate(numpy.float32, 0, 9.5, 20),
    'x': Coordinate(numpy.float32, 9, 0, 10)
}, {
    'B10': Variable(numpy.float32, numpy.nan, ('t', 'y', 'x'))
})
ds2 = FauxStorageUnit({
    't': Coordinate(numpy.int, 500, 600, 3),
    'y': Coordinate(numpy.float32, 0, 9.5, 20),
    'x': Coordinate(numpy.float32, 9, 0, 10)
}, {
    'B10': Variable(numpy.float32, numpy.nan, ('t', 'y', 'x'))
})


def test_common_storage_unit():
    data = ds1.get('B10')
    assert (data.values.shape == (4, 20, 10))
    assert (data.dims == ('t', 'y', 'x'))
    assert ((data.values.ravel() == numpy.arange(data.values.size)).all())

    expected = numpy.array([
        [
            [223, 224, 225, 226],
            [233, 234, 235, 236],
            [243, 244, 245, 246]
        ],
        [
            [423, 424, 425, 426],
            [433, 434, 435, 436],
            [443, 444, 445, 446]
        ]
    ])

    data = ds1.get('B10', t=slice(1, 3), y=slice(2, 5), x=slice(3, 7))
    assert (data.values.shape == (2, 3, 4))
    assert ((data.values == expected).all())

    dest = numpy.zeros((3, 4, 5))
    data = ds1.get('B10', dest=dest, t=slice(1, 3), y=slice(2, 5), x=slice(3, 7))
    assert (data.values.shape == (2, 3, 4))
    assert ((data.values == expected).all())
    assert ((dest[:2, :3, :4] == expected).all())


def test_storage_unit_dimension_proxy():
    su = StorageUnitDimensionProxy(ds1, ('greg', 12.0))
    data = su._get_coord('greg')
    assert(data == numpy.array([12.0]))

    data1 = su.get('B10')
    data2 = ds1.get('B10')
    assert (data1.values.shape == (1,) + data2.values.shape)
    assert (data1.dims == ('greg',) + data2.dims)
    assert ((data1.values.ravel() == data2.values.ravel()).all())

    data = su.get('B10', greg=Range(13, 14))
    assert (data.values.size == 0)


def test_storage_unit_stack():
    stack = StorageUnitStack([ds1, ds2], 't')
    expected = numpy.array([
        [
            [624, 625, 626],
            [634, 635, 636]
        ],
        [
            [24, 25, 26],
            [34, 35, 36]
        ]
    ])

    data = stack.get('B10', t=Range(400, 500), x=Range(3, 5), y=Range(1, 1.5))
    assert (len(data.coords['t']) == 2)
    assert (len(data.coords['x']) == 3)
    assert (len(data.coords['y']) == 2)
    assert ((data.values == expected).all())

    data = stack.get('B10', t=slice(3, 5), x=slice(4, 7), y=slice(2, 4))
    assert (len(data.coords['t']) == 2)
    assert (len(data.coords['x']) == 3)
    assert (len(data.coords['y']) == 2)
    assert ((data.values == expected).all())


def test_geotif_storage_unit():
    files = [
        # "/mnt/data/tiles/EPSG4326_1deg_0.00025pixel/LS7_ETM/142_-033/2010/LS7_ETM_NBAR_142_-033_2010-01-16T00-12-07.682499.tif",
        # "/mnt/data/tiles/EPSG4326_1deg_0.00025pixel/LS7_ETM/142_-033/2010/LS7_ETM_FC_142_-033_2010-01-16T00-12-07.682499.tif",
        # "/mnt/data/tiles/EPSG4326_1deg_0.00025pixel/LS7_ETM/142_-033/2010/LS7_ETM_NBAR_142_-033_2010-01-16T00-11-43.729979.tif",
        # "/mnt/data/tiles/EPSG4326_1deg_0.00025pixel/LS7_ETM/142_-033/2010/LS7_ETM_FC_142_-033_2010-01-16T00-11-43.729979.tif",
        # "/mnt/data/tiles/EPSG4326_1deg_0.00025pixel/LS7_ETM/142_-033/2010/LS7_ETM_NBAR_142_-033_2010-01-07T00-17-46.208174.tif",
        "/g/data/rs0/tiles/EPSG4326_1deg_0.00025pixel/LS5_TM/142_-033/2004/LS5_TM_NBAR_142_-033_2004-01-07T23-59-21.879044.tif",
        "/g/data/rs0/tiles/EPSG4326_1deg_0.00025pixel/LS5_TM/142_-033/2004/LS5_TM_NBAR_142_-033_2004-11-07T00-05-33.311000.tif",
        "/g/data/rs0/tiles/EPSG4326_1deg_0.00025pixel/LS5_TM/142_-033/2004/LS5_TM_NBAR_142_-033_2004-12-25T00-06-26.534031.tif",
    ]

    su = GeoTifStorageUnit(files[0])
    assert (set(su.coordinates.keys()) == ({'x', 'y'}))

    data = su.get('2', x=Range(142.5, 142.7), y=Range(-32.5, -32.2))
    assert (len(data.coords['x']) == 801)
    assert (len(data.coords['y']) == 1201)
    assert (numpy.any(data.values != -999))

    data = su.get('2', x=slice(500), y=slice(3400, None))
    assert (len(data.coords['x']) == 500)
    assert (len(data.coords['y']) == 600)
    assert (numpy.any(data.values != -999))


def test_netcdf_storage_unit():
    files = [
        "/short/v10/dra547/injest_examples/multiple_band_variables/LS7_ETM_NBAR_P54_GANBAR01-002_089_078_2015_152_-26.nc",
        "/short/v10/dra547/injest_examples/multiple_band_variables/LS7_ETM_NBAR_P54_GANBAR01-002_089_078_2015_152_-27.nc",
        "/short/v10/dra547/injest_examples/multiple_band_variables/LS7_ETM_NBAR_P54_GANBAR01-002_089_078_2015_153_-26.nc",
        "/short/v10/dra547/injest_examples/multiple_band_variables/LS7_ETM_NBAR_P54_GANBAR01-002_089_078_2015_153_-27.nc",
        "/short/v10/dra547/injest_examples/multiple_band_variables/LS7_ETM_NBAR_P54_GANBAR01-002_089_078_2015_154_-26.nc",
        "/short/v10/dra547/injest_examples/multiple_band_variables/LS7_ETM_NBAR_P54_GANBAR01-002_089_078_2015_154_-27.nc"
    ]

    su = NetCDF4StorageUnit(files[2])
    assert (set(su.coordinates.keys()) == ({'longitude', 'latitude', 'time'}))

    data = su.get('band2', longitude=Range(153.5, 153.7), latitude=Range(-25.5, -25.2))
    assert (len(data.coords['longitude']) == 801)
    assert (len(data.coords['latitude']) == 1201)
    assert (numpy.any(data.values != -999))
