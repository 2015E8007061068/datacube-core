# coding=utf-8
"""
Ingest data from the command-line.
"""
from __future__ import absolute_import

import uuid
import logging
import re
from pathlib import Path
import yaml
import netCDF4
import rasterio.warp
import click


def get_projection(proj, extent):
    left, bottom, right, top = [int(x) for x in
                                rasterio.warp.transform_bounds({'init': 'EPSG:4326'}, proj, *extent)]

    return {
        'spatial_reference': proj,
        'geo_ref_points': {
            'ul': {'x': left, 'y': top},
            'ur': {'x': right, 'y': top},
            'll': {'x': left, 'y': bottom},
            'lr': {'x': right, 'y': bottom},
            }
        }


def get_coords(left, bottom, right, top):
    return {
        'ul': {'lon': left, 'lat': top},
        'ur': {'lon': right, 'lat': top},
        'll': {'lon': left, 'lat': bottom},
        'lr': {'lon': right, 'lat': bottom},
    }


def prepare_dataset(path):
    extent = 110, -40, 155, 3
    band_re = re.compile('.*ABOM_BRF_B([0-9][0-9]).*')
    images = {band_re.match(str(image)).groups()[0]: str(image)
              for image in path.glob('*-ABOM_BRF_*1000-HIMAWARI8-AHI.nc')}
    first = netCDF4.Dataset(str(images['01']))
    times = first['time']
    sensing_time = str(netCDF4.num2date(times[0], units=times.units, calendar=times.calendar))
    return [{
        'id': str(uuid.uuid4()),
        'ga_label': str(first.id),
        'ga_level': str(first.processing_level),
        'product_type': 'BRF',
        'creation_dt': str(first.date_created),
        'platform': {'code': 'HIMAWARI_8'},
        'instrument': {'name': str(first.instrument)},
        # 'acquisition': {'groundstation': {'code': station}},
        'extent': {
            'coords': get_coords(*extent),
            'from_dt': sensing_time,
            'to_dt': sensing_time,
            'center_dt': sensing_time
        },
        'format': {'name': 'NetCDF4'},
        'grid_spatial': {
            'projection': get_projection(str(first['geostationary'].spatial_ref), extent)
        },
        'image': {
            'bands': {
                name: {
                    'path': image,
                    'layer': 'channel_00' + name + '_brf',
                } for name, image in images.items()
            }
        },
        'lineage': {'source_datasets': {}},
    }]


@click.command(help="Prepare Himawari 8 dataset for ingestion into the Data Cube.")
@click.argument('datasets',
                type=click.Path(exists=True, readable=True, writable=True),
                nargs=-1)
def main(datasets):
    logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logging.INFO)

    for dataset in datasets:
        path = Path(dataset)

        logging.info("Processing %s", path)
        documents = prepare_dataset(path)

        yaml_path = str(path.joinpath('agdc-metadata.yaml'))
        logging.info("Writing %s datasets into %s", len(documents), yaml_path)
        with open(yaml_path, 'w') as stream:
            yaml.dump_all(documents, stream)


if __name__ == "__main__":
    main()
