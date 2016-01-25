# coding=utf-8
"""
Create/store dataset data into storage units based on the provided storage mappings
"""
from __future__ import absolute_import, division, print_function

import logging
from contextlib import contextmanager
from itertools import groupby
from functools import partial
import os.path
import tempfile

import dateutil.parser
import numpy

from osgeo import ogr, osr
import rasterio.warp

from rasterio.warp import RESAMPLING, transform_bounds

from rasterio.coords import BoundingBox

from affine import Affine

from datacube import compat
from datacube.model import StorageUnit, TileSpec
from datacube.storage.netcdf_indexer import read_netcdf_structure
from datacube.storage.netcdf_writer import create_netcdf_writer

_LOG = logging.getLogger(__name__)

RESAMPLING_METHODS = {
    'nearest': RESAMPLING.nearest,
    'cubic': RESAMPLING.cubic,
    'bilinear': RESAMPLING.bilinear,
    'cubic_spline': RESAMPLING.cubic_spline,
    'lanczos': RESAMPLING.lanczos,
    'average': RESAMPLING.average,
}


def tile_datasets_with_storage_type(datasets, storage_type):
    """
    compute indexes of tiles covering the datasets, as well as
    which datasets comprise which tiles

    :type datasets:  list[datacube.model.Dataset]
    :type storage_type:  datacube.model.StorageType
    :rtype: dict[tuple[int, int], list[datacube.model.Dataset]]
    """
    datasets = sort_datasets_by_time(datasets)
    bounds_override = storage_type.roi and _roi_to_bounds(storage_type.roi, storage_type.spatial_dimensions)
    return _grid_datasets(datasets, bounds_override, storage_type.projection, storage_type.tile_size)


def sort_datasets_by_time(datasets):
    datasets.sort(key=_dataset_time)
    return datasets


def _dataset_time(dataset):
    center_dt = dataset.metadata_doc['extent']['center_dt']
    if isinstance(center_dt, compat.string_types):
        center_dt = dateutil.parser.parse(center_dt)
    return center_dt


def _roi_to_bounds(roi, dims):
    return BoundingBox(roi[dims[0]][0], roi[dims[1]][0], roi[dims[0]][1], roi[dims[1]][1])


def _grid_datasets(datasets, bounds_override, grid_proj, grid_size):
    tiles = {}
    for dataset in datasets:
        dataset_proj = _dataset_projection_to_epsg_ref(dataset)
        dataset_bounds = _dataset_bounds(dataset)
        bounds = bounds_override or BoundingBox(*transform_bounds(dataset_proj, grid_proj, *dataset_bounds))

        for y in range(int(bounds.bottom // grid_size[1]), int(bounds.top // grid_size[1]) + 1):
            for x in range(int(bounds.left // grid_size[0]), int(bounds.right // grid_size[0]) + 1):
                tile_index = (x, y)
                if _check_intersect(tile_index, grid_size, grid_proj, dataset_bounds, dataset_proj):
                    tiles.setdefault(tile_index, []).append(dataset)

    return tiles


def _dataset_projection_to_epsg_ref(dataset):
    projection = dataset.metadata_doc['grid_spatial']['projection']

    crs = projection.get('spatial_reference', None)
    if crs:
        return str(crs)

    # TODO: really need CRS specified properly in agdc-metadata.yaml
    if projection['datum'] == 'GDA94':
        return 'EPSG:283' + str(abs(projection['zone']))

    if projection['datum'] == 'WGS84':
        if projection['zone'][-1] == 'S':
            return 'EPSG:327' + str(abs(int(projection['zone'][:-1])))
        else:
            return 'EPSG:326' + str(abs(int(projection['zone'][:-1])))

    raise RuntimeError('Cant figure out the projection: %s %s' % (projection['datum'], projection['zone']))


def _dataset_bounds(dataset):
    geo_ref_points = dataset.metadata_doc['grid_spatial']['projection']['geo_ref_points']
    return BoundingBox(geo_ref_points['ll']['x'], geo_ref_points['ll']['y'],
                       geo_ref_points['ur']['x'], geo_ref_points['ur']['y'])


def _check_intersect(tile_index, tile_size, tile_crs, dataset_bounds, dataset_crs):
    tile_sr = osr.SpatialReference()
    tile_sr.SetFromUserInput(tile_crs)
    dataset_sr = osr.SpatialReference()
    dataset_sr.SetFromUserInput(dataset_crs)
    transform = osr.CoordinateTransformation(tile_sr, dataset_sr)

    tile_poly = _poly_from_bounds(tile_index[0] * tile_size[0],
                                  tile_index[1] * tile_size[1],
                                  (tile_index[0] + 1) * tile_size[0],
                                  (tile_index[1] + 1) * tile_size[1],
                                  32)
    tile_poly.Transform(transform)

    return tile_poly.Intersects(_poly_from_bounds(*dataset_bounds))


def _poly_from_bounds(left, bottom, right, top, segments=None):
    ring = ogr.Geometry(ogr.wkbLinearRing)
    ring.AddPoint(left, bottom)
    ring.AddPoint(left, top)
    ring.AddPoint(right, top)
    ring.AddPoint(right, bottom)
    ring.AddPoint(left, bottom)
    if segments:
        ring.Segmentize(2 * (right + top - left - bottom) / segments)
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(ring)
    return poly


def create_storage_unit_from_datasets(tile_index, datasets, storage_type, output_uri):
    """
    Create storage unit at `tile_index` for datasets using mapping


    :param tile_index: X,Y index of the storage unit
    :type tile_index: tuple[int, int]
    :type datasets:  list[datacube.model.Dataset]
    :type storage_type:  datacube.model.StorageType
    :param output_uri: URI specifying filename, must be file:// (for now)
    :type output_filename:  str
    :rtype: datacube.model.StorageUnit
    """
    if not datasets:
        raise ValueError('Shall not create empty StorageUnit%s %s' % (tile_index, output_uri))

    if storage_type.driver != 'NetCDF CF':
        raise ValueError('Storage driver is not supported (yet): %s' % storage_type.driver)

    output_filename = _uri_to_filename(output_uri)

    if os.path.isfile(output_filename):
        raise RuntimeError('file already exists: %s' % output_filename)

    _LOG.info("Creating Storage Unit %s", output_filename)
    tmpfile, tmpfilename = tempfile.mkstemp(dir=os.path.dirname(output_filename))
    try:
        datasets_grouped_by_time = _group_datasets_by_time(datasets)
        _warn_if_mosaiced_datasets(datasets_grouped_by_time, tile_index)
        tile_spec = _make_tile_spec(storage_type, tile_index)

        data_writer = partial(_fill_storage_unit_from_grouped_datasets,
                              datasets_grouped_by_time=datasets_grouped_by_time,
                              tile_spec=tile_spec,
                              storage_type=storage_type)

        write_storage_unit_to_disk(tmpfilename, tile_spec, datasets_grouped_by_time, data_writer)
        os.close(tmpfile)
        os.rename(tmpfilename, output_filename)
    finally:
        try:
            os.unlink(tmpfilename)
        except OSError:
            pass

            # TODO: move 'hardcoded' coordinate specs (name, units, etc) into tile_spec
            # TODO: then we can pull the descriptor out of the tile_spec
            # TODO: and netcdf writer will be more generic


def _uri_to_filename(uri):
    if not uri.startswith('file://'):
        raise ValueError('Full URI protocol is not supported (yet): %s' % uri)
    return uri[7:]


def _make_tile_spec(storage_type, tile_index):
    tile_size = storage_type.tile_size
    tile_res = storage_type.resolution
    return TileSpec(storage_type.projection,
                    _get_tile_transform(tile_index, tile_size, tile_res),
                    width=int(tile_size[0] / abs(tile_res[0])),
                    height=int(tile_size[1] / abs(tile_res[1])))


def _get_tile_transform(tile_index, tile_size, tile_res):
    x = (tile_index[0] + (1 if tile_res[0] < 0 else 0)) * tile_size[0]
    y = (tile_index[1] + (1 if tile_res[1] < 0 else 0)) * tile_size[1]
    return Affine(tile_res[0], 0.0, x, 0.0, tile_res[1], y)


def _group_datasets_by_time(datasets):
    return [(time, list(group)) for time, group in groupby(datasets, _dataset_time)]


def _warn_if_mosaiced_datasets(datasets_grouped_by_time, tile_index):
    for time, group in datasets_grouped_by_time:
        if len(group) > 1:
            _LOG.warning("Mosaicing multiple datasets %s@%s: %s", tile_index, time, group)


def write_storage_unit_to_disk(filename, tile_spec, datasets_grouped_by_time, data_writer):
    with create_netcdf_writer(filename, tile_spec, len(datasets_grouped_by_time)) as su_writer:
        su_writer.create_time_values(time for time, _ in datasets_grouped_by_time)

        for time_index, (_, group) in enumerate(datasets_grouped_by_time):
            su_writer.add_source_metadata(time_index, (dataset.metadata_doc for dataset in group))

        data_writer(su_writer)
        

def _fill_storage_unit_from_grouped_datasets(su_writer, datasets_grouped_by_time, tile_spec, storage_type):
    measurements = storage_type.measurements
    chunking = storage_type.chunking
    for measurement_id, measurement_descriptor in measurements.items():
        output_var = su_writer.ensure_variable(measurement_descriptor, chunking)

        buffer_ = numpy.empty(output_var.shape[1:], dtype=output_var.dtype)
        for time_index, (_, time_group) in enumerate(datasets_grouped_by_time):
            buffer_ = fuse_sources([DatasetSource(dataset, measurement_id) for dataset in time_group],
                                   buffer_,
                                   tile_spec.affine,
                                   tile_spec.projection,
                                   getattr(output_var, '_FillValue', None),
                                   resampling=_rasterio_resampling_method(measurement_descriptor))
            output_var[time_index] = buffer_


def _rasterio_resampling_method(measurement_descriptor):
    return RESAMPLING_METHODS[measurement_descriptor['resampling_method'].lower()]


def in_memory_storage_unit_from_file(uri, datasets, storage_type):
    filename = _uri_to_filename(uri)
    su_descriptor = read_netcdf_structure(filename)
    dataset_ids = [dataset.id for dataset in datasets]
    return StorageUnit(dataset_ids,
                       storage_type,
                       su_descriptor,
                       storage_type.local_path_to_location_offset('file://' + filename))


def generate_filename(tile_index, datasets, mapping):
    merged = {
        'tile_index': tile_index,
        'mapping_id': mapping.id_,
        'start_time': _parse_time(datasets[0].metadata_doc['extent']['from_dt']),
        'end_time': _parse_time(datasets[-1].metadata_doc['extent']['to_dt']),
    }
    merged.update(mapping.match.metadata)

    return mapping.storage_pattern.format(**merged)


def _parse_time(time):
    if isinstance(time, compat.string_types):
        return dateutil.parser.parse(time)
    return time


def fuse_sources(sources, destination, dst_transform, dst_projection, dst_nodata,
                 resampling=RESAMPLING.nearest, fuse_func=None):
    def reproject(source, dest):
        with source.open() as src:
            rasterio.warp.reproject(src,
                                    dest,
                                    src_transform=source.transform,
                                    src_crs=source.projection,
                                    src_nodata=source.nodata,
                                    dst_transform=dst_transform,
                                    dst_crs=dst_projection,
                                    dst_nodata=dst_nodata,
                                    resampling=resampling,
                                    NUM_THREADS=4)

    def copyto_fuser(dest, src):
        numpy.copyto(dest, src, where=(src != dst_nodata))

    fuse_func = fuse_func or copyto_fuser

    if len(sources) == 1:
        reproject(sources[0], destination)
        return destination

    destination.fill(dst_nodata)
    if len(sources) == 0:
        return destination

    buffer_ = numpy.empty(destination.shape, dtype=destination.dtype)
    for source in sources:
        reproject(source, buffer_)
        fuse_func(destination, buffer_)

    return destination


class DatasetSource(object):
    def __init__(self, dataset, measurement_id):
        dataset_measurement_descriptor = dataset.metadata.measurements_dict[measurement_id]
        self._filename = str(dataset.local_path.parent.joinpath(dataset_measurement_descriptor['path']))
        self._band_id = dataset_measurement_descriptor.get('layer', 1)
        self.transform = None
        self.projection = None
        self.nodata = None
        self.format = dataset.format

    @contextmanager
    def open(self):
        for nasty_format in ('netcdf', 'hdf'):
            if nasty_format in self.format.lower():
                filename = '%s:"%s":%s' % (self.format, self._filename, self._band_id)
                bandnumber = 1
                break
        else:
            filename = self._filename
            bandnumber = self._band_id

        try:
            _LOG.debug("openening %s, band %s", filename, bandnumber)
            with rasterio.open(filename) as src:
                self.transform = src.affine
                self.projection = src.crs
                self.nodata = src.nodatavals[0] or (0 if self.format == 'JPEG2000' else None)  # TODO: sentinel 2 hack
                yield rasterio.band(src, bandnumber)
        finally:
            src.close()
