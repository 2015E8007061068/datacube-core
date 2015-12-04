# coding=utf-8
"""
Create netCDF4 Storage Units and write data to them
"""
from __future__ import absolute_import

import logging
import os.path
from datetime import datetime

import netCDF4
from osgeo import osr

from datacube.model import VariableAlreadyExists

_LOG = logging.getLogger(__name__)

EPOCH = datetime(1970, 1, 1, 0, 0, 0)


class NetCDFWriter(object):
    """
    Base class for creating a NetCDF file based upon GeoTIFF data.

    Sub-classes will create the NetCDF in different structures.
    """

    def __init__(self, netcdf_path, tile_spec):
        netcdf_path = str(netcdf_path)
        if not os.path.isfile(netcdf_path):
            self.nco = netCDF4.Dataset(netcdf_path, 'w')

            self._create_spatial_variables(tile_spec)
            self._set_global_attributes(tile_spec)
            self._create_variables()
        else:
            self.nco = netCDF4.Dataset(netcdf_path, 'a')
            # TODO assert the tile_spec actually matches this netcdf file
        self._tile_spec = tile_spec
        self.netcdf_path = netcdf_path

    def close(self):
        self.nco.close()

    def _create_time_dimension(self):
        """
        Create time dimension

        Time is unlimited
        """
        self.nco.createDimension('time', None)
        timeo = self.nco.createVariable('time', 'double', 'time')
        timeo.units = 'seconds since 1970-01-01 00:00:00'
        timeo.standard_name = 'time'
        timeo.long_name = 'Time, unix time-stamp'
        timeo.calendar = 'standard'
        timeo.axis = "T"

    def _create_spatial_variables(self, tile_spec):
        projection = osr.SpatialReference(str(tile_spec.projection))
        if projection.IsGeographic():
            crs = self._create_geocrs(projection)
            self.nco.createDimension('longitude', len(tile_spec.lons))
            self.nco.createDimension('latitude', len(tile_spec.lats))

            lon = self.nco.createVariable('longitude', 'double', 'longitude')
            lon.units = 'degrees_east'
            lon.standard_name = 'longitude'
            lon.long_name = 'longitude'
            lon.axis = "X"

            lat = self.nco.createVariable('latitude', 'double', 'latitude')
            lat.units = 'degrees_north'
            lat.standard_name = 'latitude'
            lat.long_name = 'latitude'
            lat.axis = "Y"

            lon[:] = tile_spec.lons
            lat[:] = tile_spec.lats
            return crs
        elif projection.IsProjected():
            crs = self._create_crs_albers(projection, tile_spec)
            return crs
        else:
            raise Exception("Unknown projection")

    def _create_geocrs(self, projection):
        crs = self.nco.createVariable('crs', 'i4')
        crs.long_name = projection.GetAttrValue('GEOGCS')  # "Lon/Lat Coords in WGS84"
        crs.grid_mapping_name = "latitude_longitude"
        crs.longitude_of_prime_meridian = 0.0
        crs.semi_major_axis = projection.GetSemiMajor()
        crs.inverse_flattening = projection.GetInvFlattening()
        return crs

    def _create_crs_albers(self, projection, tile_spec):
        # http://spatialreference.org/ref/epsg/gda94-australian-albers/html/
        # http://cfconventions.org/Data/cf-conventions/cf-conventions-1.7/build/cf-conventions.html#appendix-grid-mappings
        assert projection.GetAttrValue('PROJECTION') == 'Albers_Conic_Equal_Area'
        crs = self.nco.createVariable('albers_conical_equal_area')
        crs.standard_parallel_1 = projection.GetProjParm('standard_parallel_1')
        crs.standard_parallel_2 = projection.GetProjParm('standard_parallel_2')
        crs.longitude_of_central_meridian = projection.GetProjParm('longitude_of_center')
        crs.latitude_of_projection_origin = projection.GetProjParm('latitude_of_center')
        crs.false_easting = projection.GetProjParm('false_easting')
        crs.false_northing = projection.GetProjParm('false_northing')
        crs.grid_mapping_name = "albers_conical_equal_area"
        crs.long_name = projection.GetAttrValue('PROJCS')

        wgs84 = osr.SpatialReference()
        wgs84.ImportFromEPSG(4326)

        to_wgs84 = osr.CoordinateTransformation(projection, wgs84)
        lats, lons, _ = zip(*[to_wgs84.TransformPoint(x, y) for y in tile_spec.ys for x in tile_spec.xs])

        lats_var = self.nco.createVariable('lat', 'double', ('y', 'x'))
        lats_var.long_name = 'latitude coordinate'
        lats_var.standard_name = 'latitude'
        lats_var.units = 'degrees north'
        lats_var[:] = lats_var

        lons_var = self.nco.createVariable('lon', 'double', ('y', 'x'))
        lons_var.long_name = 'longitude coordinate'
        lons_var.standard_name = 'longitude'
        lons_var.units = 'degrees east'
        lons_var[:] = lons_var

        xvar = self.nco.createVariable('x', 'double')
        xvar.long_name = 'x coordinate of projection'
        xvar.units = projection.GetAttrValue('UNIT')
        xvar.standard_name = 'projection_x_coordinate'
        xvar[:] = tile_spec.xs

        return crs

    def _set_global_attributes(self, tile_spec):
        """

        :type tile_spec: datacube.model.TileSpec
        """
        # ACDD Metadata (Recommended)
        self.nco.geospatial_bounds = "POLYGON(({0} {2},{0} {3},{1} {3},{1} {2},{0} {2})".format(tile_spec.lon_min,
                                                                                                tile_spec.lon_max,
                                                                                                tile_spec.lat_min,
                                                                                                tile_spec.lat_max)
        self.nco.geospatial_bounds_crs = "EPSG:4326"
        self.nco.geospatial_lat_min = tile_spec.lat_min
        self.nco.geospatial_lat_max = tile_spec.lat_max
        self.nco.geospatial_lat_units = "degrees_north"
        self.nco.geospatial_lat_resolution = "{} degrees".format(abs(tile_spec.lat_res))
        self.nco.geospatial_lon_min = tile_spec.lon_min
        self.nco.geospatial_lon_max = tile_spec.lon_max
        self.nco.geospatial_lon_units = "degrees_east"
        self.nco.geospatial_lon_resolution = "{} degrees".format(abs(tile_spec.lon_res))
        self.nco.date_created = datetime.today().isoformat()
        self.nco.history = "NetCDF-CF file created by agdc-v2 at {:%Y%m%d}.".format(datetime.utcnow())

        # Follow ACDD and CF Conventions
        self.nco.Conventions = 'CF-1.6, ACDD-1.3'

        # Attributes from Dataset. For NCI Reqs MUST contain at least title, summary, source, product_version
        for name, value in tile_spec.global_attrs.items():
            self.nco.setncattr(name, value)

    def find_or_create_time_index(self, insertion_time):
        """
        Only allow a single time index at the moment
        :param insertion_time:
        :return:
        """
        times = self.nco.variables['time']

        if len(times) == 0:
            _LOG.debug('Inserting time %s', insertion_time)
            start_datetime_delta = insertion_time - EPOCH
            _LOG.debug('stored time value %s', start_datetime_delta.total_seconds())
            index = len(times)
            # Save as next coordinate in file
            times[index] = start_datetime_delta.total_seconds()
        else:
            index = netCDF4.date2index(insertion_time, times)  # Blow up for a different time

        return index

    def append_np_array(self, time, nparray, varname, dtype, ndv, chunking, units):
        if varname in self.nco.variables:
            out_band = self.nco.variables[varname]
            src_filename = self.nco.variables[varname + "_src_filenames"]
        else:
            chunksizes = [chunking[dim] for dim in ['t', 'y', 'x']]
            out_band, src_filename = self._create_data_variable(varname, dtype, chunksizes, ndv, units)

        time_index = self.find_or_create_time_index(time)

        out_band[time_index, :, :] = nparray
        src_filename[time_index] = "Raw Array"

    def append_slice(self, np_array, storage_type, measurement_descriptor, time_value, input_filename):
        varname = measurement_descriptor.varname
        if varname in self.nco.variables:
            raise VariableAlreadyExists('Error writing to {}: variable {} already exists and will not be '
                                        'overwritten.'.format(self.netcdf_path, varname))

        chunking = storage_type.chunking
        chunksizes = [chunking[dim] for dim in ['t', 'y', 'x']]
        dtype = measurement_descriptor.dtype
        nodata = getattr(measurement_descriptor, 'nodata', None)
        units = getattr(measurement_descriptor, 'units', None)
        out_band, src_filename = self._create_data_variable(varname, dtype, chunksizes, nodata, units)

        time_index = self.find_or_create_time_index(time_value)

        out_band[time_index, :, :] = np_array
        src_filename[time_index] = input_filename

    def _create_variables(self):
        self._create_time_dimension()

        # Create Variable Length Variable to store extra metadata
        extra_meta = self.nco.createVariable('extra_metadata', str, 'time')
        extra_meta.long_name = 'Extra source metadata'

    def _create_data_variable(self, varname, dtype, chunksizes, ndv, units):
        newvar = self.nco.createVariable(varname, dtype, ('time', 'latitude', 'longitude'),
                                         zlib=True, chunksizes=chunksizes,
                                         fill_value=ndv)
        newvar.grid_mapping = 'crs'
        newvar.set_auto_maskandscale(False)

        if units:
            newvar.units = units

        src_filename = self.nco.createVariable(varname + "_src_filenames", str, 'time')
        src_filename.long_name = 'Source filename from data import'
        return newvar, src_filename
