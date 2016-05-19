from __future__ import absolute_import

import logging
import math
import uuid

import click
import numpy
from pathlib import Path
from rasterio.coords import BoundingBox

from datacube.api.core import Datacube
from datacube.model import DatasetType, Dataset, GeoBox, GeoPolygon, CRS
from datacube.storage.storage import write_dataset_to_netcdf
from datacube.ui import click as ui
from datacube.ui import read_documents

from datacube.ui.click import cli
import yaml
try:
    from yaml import CSafeDumper as SafeDumper
except ImportError:
    from yaml import SafeDumper

_LOG = logging.getLogger('agdc-ingest')


def set_geobox_info(doc, crs, extent):
    bb = extent.boundingbox
    gp = GeoPolygon([(bb.left, bb.top), (bb.right, bb.top), (bb.right, bb.bottom), (bb.left, bb.bottom)],
                    crs).to_crs(CRS('EPSG:4326'))
    doc.update({
        'extent': {
            'coord': {
                'ul': {'lon': gp.points[0][0], 'lat': gp.points[0][1]},
                'ur': {'lon': gp.points[1][0], 'lat': gp.points[1][1]},
                'lr': {'lon': gp.points[2][0], 'lat': gp.points[2][1]},
                'll': {'lon': gp.points[3][0], 'lat': gp.points[3][1]},
            }
        },
        'grid_spatial': {
            'projection': {
                'spatial_reference': str(crs),
                'geo_ref_points': {
                    'ul': {'x': bb.left, 'y': bb.top},
                    'ur': {'x': bb.right, 'y': bb.top},
                    'll': {'x': bb.left, 'y': bb.bottom},
                    'lr': {'x': bb.right, 'y': bb.bottom},
                }
            }
        }
    })


def grid_range(lower, upper, step):
    """
    Return indexes of a grid.

    >>> list(grid_range(-4.0, -1.0, 3.0))
    [-2, -1]
    >>> list(grid_range(-3.0, 0.0, 3.0))
    [-1]
    >>> list(grid_range(-2.0, 1.0, 3.0))
    [-1, 0]
    >>> list(grid_range(-1.0, 2.0, 3.0))
    [-1, 0]
    >>> list(grid_range(0.0, 3.0, 3.0))
    [0]
    >>> list(grid_range(1.0, 4.0, 3.0))
    [0, 1]
    """
    return range(int(math.floor(lower/step)), int(math.ceil(upper/step)))


def generate_grid(grid_spec, bounds):
    """
    Return an iterator of GeoBox tiles across a grid.

    :param grid_spec: GridSpec like object (must include tile_size, resolution and crs)
    :param bounds: Boundary coordinates of the required grid
    :return: iterator across geoboxes of tiles in a grid
    """
    grid_size = grid_spec.tile_size
    for y in grid_range(bounds.bottom, bounds.top, grid_size[1]):
        for x in grid_range(bounds.left, bounds.right, grid_size[0]):
            tile_index = (x, y)
            yield tile_index, GeoBox.from_grid_spec(grid_spec, tile_index)


def generate_dataset(data, prod_info, uri):
    nudata = data.copy()
    del nudata['sources']

    datasets = []
    for idx, (time, sources) in enumerate(zip(data['time'].values, data['sources'].values)):
        document = {
            'id': str(uuid.uuid4()),
            'image': {
                'bands': {name: {'path': '', 'layer': name} for name in nudata.data_vars}
            },
            'lineage': {'source_datasets': {str(idx): dataset.metadata_doc for idx, dataset in enumerate(sources)}}
        }
        # TODO: extent is a bad thing to store - it duplicates coordinates
        set_geobox_info(document, data.crs, data.extent)
        document['extent']['from_dt'] = str(time)
        document['extent']['to_dt'] = str(time)
        document['extent']['center_dt'] = str(time)
        document.update(prod_info.metadata)
        dataset = Dataset(prod_info,
                          document,
                          local_uri=uri,
                          sources={str(idx): dataset for idx, dataset in enumerate(sources)},
                          managed=True)
        datasets.append(dataset)
    nudata['dataset'] = (['time'],
                         numpy.array([yaml.dump(dataset.metadata_doc, Dumper=SafeDumper, encoding='utf-8')
                                      for dataset in datasets], dtype=str))
    return nudata, datasets


def write_product(data, output_prod_info, var_params, path):
    nudata, nudatasets = generate_dataset(data, output_prod_info, path.absolute().as_uri())
    write_dataset_to_netcdf(nudata, var_params, path)
    return nudatasets


def sorted_diff(a, b, key_func=lambda x: x):
    """
    >>> list(sorted_diff([1,2,3], []))
    [1, 2, 3]
    >>> list(sorted_diff([1,2,3], [1]))
    [2, 3]
    >>> list(sorted_diff([1,2,2,2,3], [2]))
    [1, 3]
    >>> list(sorted_diff([1,2,3], [-1,2,4,5,6]))
    [1, 3]
    """
    aiter = iter(a)
    biter = iter(b)

    try:
        val_b = next(biter)
    except StopIteration:
        for val_a in aiter:
            yield val_a
        return
    val_a = next(aiter)

    while True:
        if key_func(val_a) < key_func(val_b):
            yield val_a
            val_a = next(aiter)
        elif key_func(val_a) > key_func(val_b):
            try:
                val_b = next(biter)
            except StopIteration:
                break
        else:
            val_a = next(aiter)

    yield val_a
    for val_a in aiter:
        yield val_a


def find_diff(input_type, output_type, bbox, datacube):
    tasks = []
    for tile_index, geobox in generate_grid(output_type.grid_spec, bbox):
        observations = datacube.product_observations(input_type.name, geobox.extent, lambda ds: ds.time)
        if observations:
            created_obs = datacube.product_observations(output_type.name, geobox.extent, lambda ds: ds.time)
            observations = list(sorted_diff(observations, created_obs, lambda x: x[0]))
            tasks += [(tile_index, [obs]) for obs in observations]
    return tasks


def do_work(tasks, work_func, index, executor):
    results = []
    for tile_index, groups in tasks:
        results.append(executor.submit(work_func, tile_index, groups))

    for result in results:
        # TODO: try/catch
        datasets = executor.result(result)

        for dataset in datasets:
            index.datasets.add(dataset)


def morph_dataset_type(source_type, config):
    output_type = DatasetType(source_type.metadata_type, source_type.definition.copy())
    output_type.definition['metadata'] = source_type.metadata.copy()
    output_type.definition['name'] = config['output_type']
    output_type.definition['description'] = config['description']
    output_type.definition['storage'] = config['storage']
    output_type.metadata['format'] = {'name': 'NetCDF'}

    def merge_measurement(measurement, spec):
        measurement.update({k: spec.get(k, measurement[k]) for k in ('nodata', 'dtype')})
        return measurement

    output_type.definition['measurements'] = {
        name: merge_measurement(output_type.definition['measurements'][spec['src_varname']], spec)
        for name, spec in config['measurements'].items()
    }
    return output_type


def get_variable_params(config):
    chunking = config['storage']['chunking']
    chunking = [chunking[dim] for dim in config['storage']['dimension_order']]

    variable_params = {}
    for varname, mapping in config['measurements'].items():
        variable_params[varname] = {k: v for k, v in mapping.items() if k in {'zlib',
                                                                              'complevel',
                                                                              'shuffle',
                                                                              'fletcher32',
                                                                              'contiguous'}}
        variable_params[varname]['chunksizes'] = chunking

    return variable_params


def get_namemap(config):
    return {spec['src_varname']: name for name, spec in config['measurements'].items()}


@cli.command('ingest', help="Ingest datasets")
@click.option('--config', '-c',
              type=click.Path(exists=True, readable=True, writable=False, dir_okay=False),
              required=True,
              help='Ingest configuration file')
@ui.executor_cli_options
@click.option('--dry-run', '-d', is_flag=True, default=False, help='Check if everything is ok')
@ui.pass_index(app_name='agdc-ingest')
def ingest_cmd(index, config, dry_run, executor):
    _, config = next(read_documents(Path(config)))
    source_type = index.datasets.types.get_by_name(config['source_type'])
    if not source_type:
        _LOG.error("Source DatasetType %s does not exist", config['source_type'])

    output_type = morph_dataset_type(source_type, config)
    _LOG.info('Created DatasetType %s', output_type.name)
    output_type = index.datasets.types.add(output_type)

    datacube = Datacube(index=index)

    bbox = BoundingBox(**config['ingestion_bounds'])
    # bbox = BoundingBox(1400000, -4000000, 1600000, -3800000)
    tasks = find_diff(source_type, output_type, bbox, datacube)

    grid_spec = output_type.grid_spec
    namemap = get_namemap(config)
    measurements = source_type.measurements
    variable_params = get_variable_params(config)
    file_path_template = str(Path(config['location'], config['file_path_template']))

    def ingest_work(tile_index, groups):
        geobox = GeoBox.from_grid_spec(grid_spec, tile_index)
        data = Datacube.product_data(groups, geobox, measurements)

        nudata = data.rename(namemap)

        file_path = file_path_template.format(tile_index=tile_index,
                                              start_time=groups[0][0].strftime('%Y%m%d%H%M%S%f'),
                                              end_time=groups[-1][0].strftime('%Y%m%d%H%M%S%f'))
        nudatasets = write_product(nudata, output_type, variable_params, Path(file_path))  # TODO: algirthm params
        return nudatasets

    do_work(tasks, ingest_work, index, executor)
