from __future__ import print_function, absolute_import

from datetime import datetime

from affine import Affine
import numpy as np
import numpy.testing as npt
import netCDF4
import rasterio

from datacube.storage.netcdf_writer import NetCDFWriter
from datacube.model import TileSpec, StorageType
from datacube.storage.utils import tilespec_from_riodataset

GEO_PROJ = 'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],' \
           'AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],' \
           'AUTHORITY["EPSG","4326"]]'


class SimpleObject(dict):
    def __getattr__(self, name):
        if name in self:
            return self[name]
        else:
            raise AttributeError("No such attribute: " + name)


def test_albers_goo(tmpdir):
    filename = str(tmpdir.join('testfile_np.nc'))

    affine = Affine(25.0, 0.0, 100000, 0.0, -25, 100000)
    projection = """PROJCS["GDA94 / Australian Albers",
                        GEOGCS["GDA94",
                            DATUM["Geocentric_Datum_of_Australia_1994",
                                SPHEROID["GRS 1980",6378137,298.257222101,
                                    AUTHORITY["EPSG","7019"]],
                                TOWGS84[0,0,0,0,0,0,0],
                                AUTHORITY["EPSG","6283"]],
                            PRIMEM["Greenwich",0,
                                AUTHORITY["EPSG","8901"]],
                            UNIT["degree",0.01745329251994328,
                                AUTHORITY["EPSG","9122"]],
                            AUTHORITY["EPSG","4283"]],
                        UNIT["metre",1,
                            AUTHORITY["EPSG","9001"]],
                        PROJECTION["Albers_Conic_Equal_Area"],
                        PARAMETER["standard_parallel_1",-18],
                        PARAMETER["standard_parallel_2",-36],
                        PARAMETER["latitude_of_center",0],
                        PARAMETER["longitude_of_center",132],
                        PARAMETER["false_easting",0],
                        PARAMETER["false_northing",0],
                        AUTHORITY["EPSG","3577"],
                        AXIS["Easting",EAST],
                        AXIS["Northing",NORTH]]"""

    global_attrs = {'test_attribute': 'test_value'}
    tile_spec = TileSpec(projection, affine, 2000, 4000, global_attrs=global_attrs)

    chunking = [('time', 1), ('y', 100), ('x', 100)]
    date = datetime(2008, 1, 1)
    ops = [(date, band) for band in [1, 2]]

    ncfile = NetCDFWriter(filename, tile_spec)

    for date, band in ops:
        data = np.empty([2000, 4000])
        data[:] = band
        bandname = 'B%s' % band
        measurement_descriptor = SimpleObject(varname=bandname, dtype='int16', nodata=-999)

        ncfile.append_np_array(date, data, measurement_descriptor, chunking, '1')
    ncfile.close()

    # Perform some basic checks
    nco = netCDF4.Dataset(filename)
    for var in ('albers_conic_equal_area', 'time', 'x', 'y', 'B1', 'B2', 'time'):
        assert var in nco.variables
    for k, v in global_attrs.items():
        assert getattr(nco, k) == v

    assert len(nco.variables['time']) == 1
    assert len(nco.variables['x']) == 4000
    assert len(nco.variables['y']) == 2000
    # assert nco.variables['latitude'][0] == -29
    # assert abs(nco.variables['latitude'][-1] - -29.9995) < 0.0000001
    # assert nco.variables['longitude'][0] == 151
    # assert nco.variables['longitude'][-1] == 151.99975


def test_create_single_time_netcdf_from_numpy_arrays(tmpdir):
    filename = str(tmpdir.join('testfile_np.nc'))

    global_attrs = {'test_attribute': 'test_value'}
    affine = Affine(0.00025, 0.0, 151.0, 0.0, -0.0005, -29.0)
    tile_spec = TileSpec(GEO_PROJ, affine, 2000, 4000, global_attrs=global_attrs)

    chunking = [('time', 1), ('latitude', 100), ('longitude', 100)]
    date = datetime(2008, 1, 1)
    ops = [(date, band) for band in [1, 2]]

    ncfile = NetCDFWriter(filename, tile_spec)

    for date, band in ops:
        data = np.empty([2000, 4000])
        data[:] = band
        bandname = 'B%s' % band

        measurement_descriptor = SimpleObject(varname=bandname, dtype='int16', nodata=-999)

        ncfile.append_np_array(date, data, measurement_descriptor, chunking, '1')
    ncfile.close()

    # Perform some basic checks
    nco = netCDF4.Dataset(filename)
    for var in ('latitude_longitude', 'time', 'longitude', 'latitude', 'B1', 'B2', 'time'):
        assert var in nco.variables
    for k, v in global_attrs.items():
        assert getattr(nco, k) == v

    assert len(nco.variables['time']) == 1
    assert len(nco.variables['longitude']) == 4000
    assert len(nco.variables['latitude']) == 2000
    npt.assert_almost_equal(nco.variables['latitude'][0], -29.00025)
    npt.assert_almost_equal(nco.variables['latitude'][-1], -29.99975)
    npt.assert_almost_equal(nco.variables['longitude'][0], 151.000125)
    npt.assert_almost_equal(nco.variables['longitude'][-1], 151.999875)


def test_create_sample_netcdf_from_gdalds(tmpdir, example_gdal_path):
    filename = str(tmpdir.join('testfile_gdal.nc'))

    dataset = rasterio.open(example_gdal_path)

    measurement_descriptor = SimpleObject(varname='B10', dtype='int16', nodata=-999)
    storage_spec = {'chunking': {'longitude': 100, 'latitude': 100, 'time': 1},
                    'dimension_order': ['time', 'latitude', 'longitude'],
                    'crs': GEO_PROJ}
    storage_type = StorageType(storage_spec)

    tile_spec = tilespec_from_riodataset(dataset)
    tile_spec.data = dataset.read(1)

    ncfile = NetCDFWriter(filename, tile_spec)
    ncfile.append_slice(dataset.read(1), storage_type, measurement_descriptor, datetime(2008, 5, 5, 0, 24), input_filename="")
    ncfile.close()

    # Perform some basic checks
    nco = netCDF4.Dataset(filename)
    for var in ('latitude_longitude', 'time', 'longitude', 'latitude', 'B10', 'time'):
        assert var in nco.variables

    assert len(nco.variables['time']) == 1
    assert len(nco.variables['longitude']) == 4000
    assert len(nco.variables['latitude']) == 4000
    assert len(nco.variables['B10']) == 1
    npt.assert_almost_equal(nco.variables['latitude'][0], -29.000125)
    npt.assert_almost_equal(nco.variables['latitude'][-1], -29.999875)
    npt.assert_almost_equal(nco.variables['longitude'][0], 151.000125)
    npt.assert_almost_equal(nco.variables['longitude'][-1], 151.999875)

    assert nco.variables['B10'].shape == (1, 4000, 4000)

    nco.close()
