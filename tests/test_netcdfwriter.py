from __future__ import print_function, absolute_import

from datetime import datetime

from affine import Affine
import numpy as np
import numpy.testing as npt
import netCDF4

from datacube.storage.netcdf_writer import NetCDFWriter
from datacube.model import TileSpec, StorageType

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

        var = ncfile.ensure_variable(measurement_descriptor, chunking)
        var[0] = data
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


def test_create_netcdf(tmpdir):
    filename = str(tmpdir.join('testfile_np.nc'))

    global_attrs = {'test_attribute': 'test_value'}
    affine = Affine(0.00025, 0.0, 151.0, 0.0, -0.0005, -29.0)
    tile_spec = TileSpec(GEO_PROJ, affine, 2000, 4000, global_attrs=global_attrs)

    chunking = [('time', 1), ('latitude', 100), ('longitude', 100)]
    date = datetime(2008, 1, 1)
    ops = [(date, band) for band in [1, 2]]

    ncfile = NetCDFWriter(filename, tile_spec)

    for index, (date, band) in enumerate(ops):
        data = np.empty([2000, 4000])
        data[:] = band
        bandname = 'B%s' % band

        measurement_descriptor = SimpleObject(varname=bandname, dtype='int16', nodata=-999)

        var = ncfile.ensure_variable(measurement_descriptor, chunking)
        var[index] = data

    ncfile.close()

    # Perform some basic checks
    with netCDF4.Dataset(filename) as nco:
        for var in ('latitude_longitude', 'time', 'longitude', 'latitude', 'B1', 'B2', 'time'):
            assert var in nco.variables
        for k, v in global_attrs.items():
            assert getattr(nco, k) == v

        assert len(nco.variables['time']) == 2
        assert len(nco.variables['longitude']) == 4000
        assert len(nco.variables['latitude']) == 2000
        npt.assert_almost_equal(nco.variables['latitude'][0], -29.00025)
        npt.assert_almost_equal(nco.variables['latitude'][-1], -29.99975)
        npt.assert_almost_equal(nco.variables['longitude'][0], 151.000125)
        npt.assert_almost_equal(nco.variables['longitude'][-1], 151.999875)

        assert nco.variables['B1'].shape == (2, 2000, 4000)



        # Check GDAL Attributes
        assert np.allclose(nco.variables['latitude_longitude'].GeoTransform, affine.to_gdal())
        assert nco.variables['latitude_longitude'].spatial_ref == GEO_PROJ

