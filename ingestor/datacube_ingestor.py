import click
import os
import pathlib
import logging
from create_tiles import calc_output_filenames, create_tiles, list_tile_files
from netcdf_writer import append_to_netcdf, MultiVariableNetCDF, SingleVariableNetCDF
import eodatasets.drivers
import eodatasets.type
from eodatasets.serialise import read_yaml_metadata


_LOG = logging.getLogger(__name__)


DEFAULT_TILE_OPTIONS = {
    'output_format': 'GTiff',
    'create_options': ['COMPRESS=DEFLATE', 'ZLEVEL=1']
}


def get_input_filenames(input_path, eodataset):
    """
    Extract absolute filenames from a DatasetMetadata object

    :type input_path: pathlib.Path
    :type eodataset: eodatasets.type.DatasetMetadata
    :return: list of filenames
    """
    assert input_path.is_dir()
    bands = sorted([band for band_num, band in eodataset.image.bands.items()], key=lambda band: band.number)
    input_files = [input_path / band.path for band in bands]

    return input_files


def is_yaml_file(path):
    """
    Is this a path to a yaml file

    :type path: pathlib.Path
    :rtype: boolean
    """
    return path.is_file() and path.suffix == '.yaml'


def load_dataset(input_path):
    """

    :param input_path:
    :rtype: (pathlib.Path, eodataset.DatasetMetadata)
    """
    input_path = pathlib.Path(input_path)

    if is_yaml_file(input_path):
        eodataset = read_yaml_metadata(input_path)
        input_path = input_path.parent

    elif input_path.is_dir():
        eodriver = eodatasets.drivers.EODSDriver()
        eodataset = eodatasets.type.DatasetMetadata()
        eodriver.fill_metadata(eodataset, input_path)
    else:
        raise Exception("Unknown dataset type at: {}" % input_path)

    return input_path, eodataset


def merge_tiles_to_netcdf(eodataset, filename_format, netcdf_class):
    created_tiles = list_tile_files('test.csv')
    tile_mappings = calc_output_filenames(created_tiles, filename_format, eodataset)
    for geotiff, netcdf in tile_mappings:
        append_to_netcdf(geotiff, netcdf, eodataset, netcdf_class=netcdf_class)

    return [netcdf_path for _, netcdf_path in tile_mappings]


def setup_logging(verbosity):
    """
    Setup logging, defaults to WARN

    :param verbosity: 1 for INFO, 2 for DEBUG
    :return:
    """
    logging_level = logging.WARN - 10 * verbosity
    logging.basicConfig(level=logging_level)


@click.command(help="Example output filename format: combined_{x}_{y}.nc ")
@click.option('--output-dir', '-o', default='.')
@click.option('--multi-variable', 'netcdf_class', flag_value=MultiVariableNetCDF, default=True)
@click.option('--single-variable', 'netcdf_class', flag_value=SingleVariableNetCDF)
@click.option('--tile/--no-tile', default=True, help="Allow partial processing")
@click.option('--merge/--no-merge', default=True, help="Allow partial processing")
@click.option('--verbose', '-v', count=True, help="Use multiple times for more verbosity")
@click.argument('input_path', type=click.Path(exists=True, readable=True))
@click.argument('filename-format')
def ingest(input_path, output_dir, filename_format, netcdf_class=MultiVariableNetCDF, tile=True, merge=True, verbose=0):
    os.chdir(output_dir)
    setup_logging(verbose)

    input_path, eodataset = load_dataset(input_path)

    input_files = get_input_filenames(input_path, eodataset)
    basename = eodataset.ga_label

    if tile:
        created_tiles = create_tiles(input_files, basename, DEFAULT_TILE_OPTIONS)
        _LOG.info("Created tiles: {}".format(created_tiles))

    # Import tiles into NetCDF files
    if merge:
        netcdf_paths = merge_tiles_to_netcdf(eodataset, filename_format, netcdf_class)
        _LOG.info("Created/alterated storage units: {}".format(netcdf_paths))


if __name__ == '__main__':
    try:
        from ipdb import launch_ipdb_on_exception
        with launch_ipdb_on_exception():
            ingest()
    except ImportError:
        ingest()
