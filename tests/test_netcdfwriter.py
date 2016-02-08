from __future__ import print_function, absolute_import

from datetime import datetime

from affine import Affine
import numpy as np
import numpy.testing as npt
import netCDF4
import pytest

from osgeo import osr

from datacube.model import GeoBox
from datacube.storage.netcdf_writer import create_netcdf, create_grid_mapping_variable

GEO_PROJ = 'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],' \
           'AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],' \
           'AUTHORITY["EPSG","4326"]]'

ALBERS_PROJ = """PROJCS["GDA94 / Australian Albers",
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

GLOBAL_ATTRS = {'test_attribute': 'test_value'}

DATA_VARIABLES = ('B1', 'B2')
LAT_LON_COORDINATES = ('latitude', 'longitude')
PROJECTED_COORDINATES = ('x', 'y')
COMMON_VARIABLES = ('crs', 'time')

DATA_WIDTH = 400
DATA_HEIGHT = 200


@pytest.fixture
def tmpnetcdf_filename(tmpdir):
    filename = str(tmpdir.join('testfile_np.nc'))

    return filename


def test_create_albers_projection_netcdf(tmpnetcdf_filename):
    nco = create_netcdf(tmpnetcdf_filename)
    crs = osr.SpatialReference(ALBERS_PROJ)
    create_grid_mapping_variable(nco, crs)
    nco.close()

    # Perform some basic checks
    with netCDF4.Dataset(tmpnetcdf_filename) as nco:
        assert 'crs' in nco.variables
        assert nco['crs'].grid_mapping_name == 'albers_conic_equal_area'


def test_create_epsg4326_netcdf(tmpnetcdf_filename):
    nco = create_netcdf(tmpnetcdf_filename)
    crs = osr.SpatialReference(GEO_PROJ)
    create_grid_mapping_variable(nco, crs)
    nco.close()

    # Perform some basic checks
    with netCDF4.Dataset(tmpnetcdf_filename) as nco:
        assert 'crs' in nco.variables
        assert nco['crs'].grid_mapping_name == 'latitude_longitude'
