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

import numpy as np
from cubeaccess.core import Coordinate, Variable, ConcatDataset
from cubeaccess.storage import NetCDF4Datatset


class TestDataset(object):
    def __init__(self, coords, vars):
        self.coordinates = coords
        self.variables = vars

    def get(self, name, **kwargs):
        if name in self.variables:
            var = self.variables[name]
            shape = [self.coordinates[dim].shape[0] for dim in var.coordinates]
            result = np.empty(shape, var.dtype)
            return result

        if name in self.coordinates:
            coord = self.coordinates[name]
            return np.linspace(coord.begin, coord.end, coord.length, dtype=coord.dtype)

        raise RuntimeError("unknown variable")


def test_netcdf():
    files = [
        "/short/v10/dra547/injest_examples/multiple_band_variables/LS7_ETM_NBAR_P54_GANBAR01-002_089_078_2015_152_-26.nc",
        "/short/v10/dra547/injest_examples/multiple_band_variables/LS7_ETM_NBAR_P54_GANBAR01-002_089_078_2015_152_-27.nc",
        "/short/v10/dra547/injest_examples/multiple_band_variables/LS7_ETM_NBAR_P54_GANBAR01-002_089_078_2015_153_-26.nc",
        "/short/v10/dra547/injest_examples/multiple_band_variables/LS7_ETM_NBAR_P54_GANBAR01-002_089_078_2015_153_-27.nc",
        "/short/v10/dra547/injest_examples/multiple_band_variables/LS7_ETM_NBAR_P54_GANBAR01-002_089_078_2015_154_-26.nc",
        "/short/v10/dra547/injest_examples/multiple_band_variables/LS7_ETM_NBAR_P54_GANBAR01-002_089_078_2015_154_-27.nc"
    ]

    mds = ConcatDataset([NetCDF4Datatset(filename) for filename in files])

    print(mds.coordinates)
    print(mds.variables)


def test_concat_dataset():
    ds1 = TestDataset({
        't': Coordinate(np.int, 100, 400, 4),
        'y': Coordinate(np.float32, 0, 9.5, 20),
        'x': Coordinate(np.float32, 9, 0, 10)
    }, {
        'B10': Variable(np.float32, np.nan, ('t', 'y', 'x'))
    })
    ds2 = TestDataset({
        't': Coordinate(np.int, 500, 600, 3),
        'y': Coordinate(np.float32, 5, 14.5, 20),
        'x': Coordinate(np.float32, 4, -5, 10)
    }, {
        'B10': Variable(np.float32, np.nan, ('t', 'y', 'x'))
    })

    mds = ConcatDataset([ds1, ds2])

    assert(mds.coordinates['t'].begin == 100)
    assert(mds.coordinates['t'].end == 600)
    assert(mds.coordinates['t'].length == 11)

    assert(mds.coordinates['x'].begin == 9)
    assert(mds.coordinates['x'].end == -5)
    assert(mds.coordinates['x'].length == 15)

    assert(mds.coordinates['y'].begin == 0)
    assert(mds.coordinates['y'].end == 14.5)
    assert(mds.coordinates['y'].length == 30)


def main():
    test_concat_dataset()
    test_netcdf()


if __name__ == '__main__':
    main()
