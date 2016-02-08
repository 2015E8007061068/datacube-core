# coding=utf-8
"""
Create netCDF4 Storage Units and write data to them
"""
from __future__ import absolute_import

import logging
from datetime import datetime

import netCDF4

from datacube import __version__

_LOG = logging.getLogger(__name__)

_STANDARD_COORDINATES = {
    'longitude': {
        'standard_name': 'longitude',
        'long_name': 'longitude',
        'axis': 'X'
    },
    'latitude': {
        'standard_name': 'latitude',
        'long_name': 'latitude',
        'axis': 'Y'
    },
    'x': {
        'standard_name': 'projection_x_coordinate',
        'long_name': 'x coordinate of projection',
        'axis': 'X'
    },
    'y': {
        'standard_name': 'projection_y_coordinate',
        'long_name': 'y coordinate of projection',
        'axis': 'Y'
    },
    'time': {
        'standard_name': 'time',
        'long_name': 'Time, unix time-stamp',
        'axis': 'T',
        'calendar': 'standard'
    }
}


def create_netcdf(netcdf_path):
    nco = netCDF4.Dataset(netcdf_path, 'w')
    nco.date_created = datetime.today().isoformat()
    nco.Conventions = 'CF-1.6, ACDD-1.3'
    nco.history = ("NetCDF-CF file created by "
                   "datacube version '{}' at {:%Y%m%d}."
                   .format(__version__, datetime.utcnow()))
    return nco


def create_coordinate(nco, name, coord):
    """
    :type nco: netCDF4.Dataset
    :type name: str
    :type coord: datacube.model.Coordinate
    :return:
    """
    nco.createDimension(name, coord.length)
    var = nco.createVariable(name, coord.dtype, name)
    var.units = coord.units
    for key, value in _STANDARD_COORDINATES.get(name, {}).items():
        setattr(var, key, value)
    return var


def create_variable(nco, name, var, **kwargs):
    """
    :param nco:
    :param name:
    :type var: datacube.model.Variable
    :param kwargs:
    :return:
    """
    if var.dtype.kind == 'S' and var.dtype.itemsize > 1:
        nco.createDimension(name+'_nchar', size=var.dtype.itemsize)
        data_var = nco.createVariable(varname=name,
                                      datatype='S1',
                                      dimensions=tuple(var.dimensions)+(name+'_nchar',),
                                      fill_value=var.nodata,
                                      **kwargs)
    else:
        data_var = nco.createVariable(varname=name,
                                      datatype=var.dtype,
                                      dimensions=var.dimensions,
                                      fill_value=var.nodata,
                                      **kwargs)
    if var.units is not None:
        data_var.units = var.units
    data_var.set_auto_maskandscale(False)
    return data_var


def _create_latlon_grid_mapping_variable(nco, crs):
    crs_var = nco.createVariable('crs', 'i4')
    crs_var.long_name = crs.GetAttrValue('GEOGCS')  # "Lon/Lat Coords in WGS84"
    crs_var.grid_mapping_name = 'latitude_longitude'
    crs_var.longitude_of_prime_meridian = 0.0
    crs_var.semi_major_axis = crs.GetSemiMajor()
    crs_var.inverse_flattening = crs.GetInvFlattening()

    return crs_var


def _create_projected_grid_mapping_variable(nco, crs):
    grid_mapping_name = crs.GetAttrValue('PROJECTION').lower()

    if grid_mapping_name != 'albers_conic_equal_area':
        raise ValueError('{} CRS is not supported'.format(grid_mapping_name))

    # http://spatialreference.org/ref/epsg/gda94-australian-albers/html/
    # http://cfconventions.org/Data/cf-conventions/cf-conventions-1.7/build/cf-conventions.html#appendix-grid-mappings
    crs_var = nco.createVariable('crs', 'i4')
    crs_var.standard_parallel = (crs.GetProjParm('standard_parallel_1'),
                                 crs.GetProjParm('standard_parallel_2'))
    crs_var.longitude_of_central_meridian = crs.GetProjParm('longitude_of_center')
    crs_var.latitude_of_projection_origin = crs.GetProjParm('latitude_of_center')
    crs_var.false_easting = crs.GetProjParm('false_easting')
    crs_var.false_northing = crs.GetProjParm('false_northing')
    crs_var.grid_mapping_name = grid_mapping_name
    crs_var.long_name = crs.GetAttrValue('PROJCS')

    return crs_var


def write_gdal_geobox_attributes(nco, geobox):
    crs_var = nco['crs']
    crs_var.spatial_ref = geobox.crs.ExportToWkt()
    crs_var.GeoTransform = geobox.affine.to_gdal()


def write_geographical_extents_attributes(nco, geobox):
    geo_extents = geobox.geographic_extent
    geo_extents.append(geo_extents[0])
    nco.geospatial_bounds = "POLYGON((" + ", ".join("{0} {1}".format(*p) for p in geo_extents) + "))"
    nco.geospatial_bounds_crs = "EPSG:4326"

    geo_aabb = geobox.geographic_boundingbox
    nco.geospatial_lat_min = geo_aabb.bottom
    nco.geospatial_lat_max = geo_aabb.top
    nco.geospatial_lat_units = "degrees_north"
    nco.geospatial_lat_resolution = "{} degrees".format(abs(geobox.affine.e))
    nco.geospatial_lon_min = geo_aabb.left
    nco.geospatial_lon_max = geo_aabb.right
    nco.geospatial_lon_units = "degrees_east"
    nco.geospatial_lon_resolution = "{} degrees".format(abs(geobox.affine.a))


def create_grid_mapping_variable(nco, crs):
    if crs.IsGeographic():
        crs_var = _create_latlon_grid_mapping_variable(nco, crs)
    elif crs.IsProjected():
        crs_var = _create_projected_grid_mapping_variable(nco, crs)
    else:
        raise ValueError('Unknown CRS')
    crs_var.crs_wkt = crs.ExportToWkt()
    return crs_var


def netcdfy_data(data):
    if data.dtype.kind == 'S' and data.dtype.itemsize > 1:
        return data.view('S1').reshape(data.shape + (-1,))
    else:
        return data
