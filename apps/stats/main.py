from __future__ import absolute_import, print_function

import click
import numpy
from datetime import datetime
from itertools import product

from pandas import to_datetime
from pathlib import Path

from datacube.api import make_mask
from datacube.model import GridSpec, CRS, Coordinate, Variable
from datacube.model.utils import make_dataset, datasets_to_doc
from datacube.api.grid_workflow import GridWorkflow
from datacube.ui import click as ui
from datacube.ui.click import to_pathlib
from datacube.utils import read_documents, unsqueeze_data_array
from datacube.storage.storage import create_netcdf_storage_unit


STANDARD_VARIABLE_PARAM_NAMES = {'zlib',
                                 'complevel',
                                 'shuffle',
                                 'fletcher32',
                                 'contiguous',
                                 'attrs'}


def nco_from_sources(sources, geobox, measurements, variable_params, filename):
    coordinates = {name: Coordinate(coord.values, coord.units)
                   for name, coord in sources.coords.items()}
    coordinates.update(geobox.coordinates)

    variables = {variable['name']: Variable(dtype=numpy.dtype(variable['dtype']),
                                            nodata=variable['nodata'],
                                            dims=sources.dims + geobox.dimensions,
                                            units=variable['units'])
                 for variable in measurements}

    return create_netcdf_storage_unit(filename, geobox.crs, coordinates, variables, variable_params)


def _tuplify(keys, values, defaults):
    assert not set(values.keys()) - set(keys), 'bad keys'
    return tuple(values.get(key, default) for key, default in zip(keys, defaults))


def _slicify(step, size):
    return (slice(i, min(i + step, size)) for i in range(0, size, step))


def block_iter(steps, shape):
    return product(*(_slicify(step, size) for step, size in zip(steps, shape)))


def tile_dims(tile):
    sources = tile['sources']
    geobox = tile['geobox']
    return sources.dims + geobox.dimensions


def tile_shape(tile):
    sources = tile['sources']
    geobox = tile['geobox']
    return sources.shape + geobox.shape


def slice_tile(tile, chunk):
    sources = tile['sources']
    geobox = tile['geobox']
    tile_cpy = tile.copy()
    tile_cpy['sources'] = sources[chunk[:len(sources.shape)]]
    tile_cpy['geobox'] = geobox[chunk[len(sources.shape):]]
    return tile_cpy


def tile_iter(tile, chunk):
    steps = _tuplify(tile_dims(tile), chunk, tile_shape(tile))
    return block_iter(steps, tile_shape(tile))


def get_variable_params(config):
    chunking = config['storage']['chunking']
    chunking = [chunking[dim] for dim in config['storage']['dimension_order']]

    variable_params = {}
    for mapping in config['stats']:
        varname = mapping['name']
        variable_params[varname] = {k: v for k, v in mapping.items() if k in STANDARD_VARIABLE_PARAM_NAMES}
        variable_params[varname]['chunksizes'] = chunking

    return variable_params


def get_filename(path_template, index, start_time):
    date_format = '%Y%m%d'
    return Path(str(path_template).format(tile_index=index,
                                          start_time=start_time.strftime(date_format)))


def fudge_sources(sources, start_time):
    fudge = sources.isel(time=slice(0, 1))
    fudge.time.values[0] = start_time  # HACK:
    return fudge


def do_stats(task, config):
    source = task['source']
    measurement_name = source['measurements'][0]
    var_params = get_variable_params(config)

    results = create_output_files(config['stats'], config['location'], measurement_name, task, var_params)

    for tile_index in tile_iter(task['data'], {'x': 1000, 'y': 1000}):
        data = GridWorkflow.load(slice_tile(task['data'], tile_index),
                                 measurements=[measurement_name])[measurement_name]
        data = data.where(data != data.attrs['nodata'])

        for spec, mask_tile in zip(source['masks'], task['masks']):
            mask = GridWorkflow.load(slice_tile(mask_tile, tile_index),
                                     measurements=[spec['measurement']])[spec['measurement']]
            mask = make_mask(mask, **spec['flags'])
            data = data.where(mask)
            del mask

        for stat in config['stats']:
            data_stats = getattr(data, stat['name'])(dim='time')
            results[stat['name']][measurement_name][tile_index][0] = data_stats

    sources = task['data']['sources'].sum()
    for spec, mask_tile in zip(source['masks'], task['masks']):
        sources += mask_tile['sources'].sum()
    # sources = unsqueeze_data_array(sources, 'time', 0, task['start_time'])

    for stat, nco in results.items():
        dataset = make_dataset(dataset_type=config['products'][stat],
                               sources=sources.item(),
                               extent=task['data']['geobox'].extent,
                               center_time=task['start_time'],
                               uri=None,  # TODO:
                               app_info=None,
                               valid_data=None)
        nco.close()


def create_output_files(stats, output_dir, measurement, task, var_params):
    """
    Create output files and return a map of statistic name to writable NetCDF Dataset
    """
    results = {}
    for stat in stats:
        measurements = [{'name': measurement,
                         'units': '1',  # TODO: where does this come from???
                         'dtype': stat['dtype'],
                         'nodata': stat['nodata']}]

        filename_template = str(Path(output_dir, stat['file_path_template']))
        output_filename = get_filename(filename_template,
                                       task['index'],
                                       task['start_time'])
        fudge = fudge_sources(task['data']['sources'], task['start_time'])
        results[stat['name']] = nco_from_sources(fudge,
                                                 task['data']['geobox'],
                                                 measurements,
                                                 {measurement: var_params[stat['name']]},
                                                 output_filename)
    return results


def get_grid_spec(config):
    storage = config['storage']
    crs = CRS(storage['crs'])
    return GridSpec(crs=crs,
                    tile_size=[storage['tile_size'][dim] for dim in crs.dimensions],
                    resolution=[storage['resolution'][dim] for dim in crs.dimensions])


def make_tasks(index, config):
    start_time = datetime(2011, 1, 1)
    end_time = datetime(2011, 2, 1)
    query = dict(time=(start_time, end_time))

    workflow = GridWorkflow(index, grid_spec=get_grid_spec(config))

    assert len(config['sources']) == 1  # TODO: merge multiple sources
    for source in config['sources']:
        data = workflow.list_cells(product=source['product'], cell_index=(15, -40), **query)
        masks = [workflow.list_cells(product=mask['product'], cell_index=(15, -40), **query)
                 for mask in source['masks']]

        for key in data.keys():
            yield {
                'source': source,
                'index': key,
                'data': data[key],
                'masks': [mask[key] for mask in masks],
                'start_time': start_time,
                'end_time': end_time
            }


def make_products(index, config):
    results = {}
    for stat in config['stats']:
        name = stat['name']
        definition = {
            'name': name,
            'description': name,
            'metadata_type': 'eo',
            'metadata': {
                'format': 'NetCDF',
                'product_type': name,
            },
            'storage': config['storage'],
            'measurements': [
                {
                    'name': measurement,
                    'dtype': stat['dtype'],
                    'nodata': stat['nodata'],
                    'units': '1'
                }
                for measurement in config['sources'][0]['measurements']
            ]
        }
        results[name] = index.products.from_doc(definition)
    return results


@click.command(name='stats')
@click.option('--app-config', '-c',
              type=click.Path(exists=True, readable=True, writable=False, dir_okay=False),
              help='configuration file location', callback=to_pathlib)
@click.option('--year', type=click.IntRange(1960, 2060))
@ui.global_cli_options
@ui.executor_cli_options
@ui.pass_index(app_name='agdc-stats')
def main(index, app_config, year, executor):
    _, config = next(read_documents(app_config))

    config['products'] = make_products(index, config)
    tasks = make_tasks(index, config)

    futures = [executor.submit(do_stats, task, config) for task in tasks]

    for future in executor.as_completed(futures):
        result = executor.result(future)
        print(result)


if __name__ == '__main__':
    main()
