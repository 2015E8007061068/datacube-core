"""
Calculates stats for small spatial area of time series LANDSAT data. It supports multiple sensors,
pq, interpolation methods, epoch and seasons

__author__ = 'u81051'
"""

from __future__ import print_function
from __future__ import absolute_import
from __future__ import division
import click
import functools
import numpy as np
import logging
from datacube import Datacube
from datacube.ui.expression import parse_expressions

from dateutil.relativedelta import relativedelta
from datacube.api.geo_xarray import append_solar_day
from datacube.storage.masking import make_mask
from dateutil.rrule import rrule, YEARLY, MONTHLY
from datacube.ui import click as ui
from enum import Enum
import xarray as xr

_log = logging.getLogger()


class Ls57Arg25Bands(Enum):
    BLUE = 1
    GREEN = 2
    RED = 3
    NEAR_INFRARED = 4
    SHORT_WAVE_INFRARED_1 = 5
    SHORT_WAVE_INFRARED_2 = 6


def initialise_odata(dtype, y, x, ndv):
    odata = np.empty(shape=(y, x), dtype=dtype)
    odata.fill(ndv)
    return odata


AVAILABLE_STATS = ['MIN', 'MAX', 'MEAN', 'GEOMEDIAN', 'MEDIAN', 'VARIANCE', 'STANDARD_DEVIATION',
                   'COUNT_OBSERVED', 'PERCENTILE']


def do_compute(dataset, stat, reduction_dim='solar_day'):
    dataset.load()
    if stat == "MIN":
        return dataset.min(dim=reduction_dim, keep_attrs=True)
    elif stat == "MAX":
        return dataset.max(dim=reduction_dim, keep_attrs=True)
    elif stat == "MEAN":
        return dataset.mean(dim=reduction_dim, keep_attrs=True)
    elif stat == "GEOMEDIAN":  # Not implemented
        # tran_data = np.transpose(stack)
        # _log.info("\t shape of data array to pass %s", np.shape(tran_data))
        # stack_stat = geomedian(tran_data, 1e-3, maxiters=20)
        raise ValueError('GeoMedian statistics are not yet implemented')
    elif stat == "MEDIAN":
        return dataset.median(dim=reduction_dim, keep_attrs=True)
    elif stat == "VARIANCE":
        return dataset.var(dim=reduction_dim, keep_attrs=True)
    elif stat == "STANDARD_DEVIATION":
        return dataset.std(dim=reduction_dim, keep_attrs=True)
    elif stat == "COUNT_OBSERVED":
        return dataset.count(dim=reduction_dim, keep_attrs=True)
    elif 'PERCENTILE' in stat.split('_'):
        percent = int(str(stat).split('_')[1])
        _log.info("\tcalculating percentile %d", percent)
        return dataset.reduce(np.nanpercentile, dim=reduction_dim, q=percent, interpolation='nearest')


#: pylint: disable=invalid-name
required_option = functools.partial(click.option, required=True)


@click.command(name='stats')
@ui.global_cli_options
@ui.executor_cli_options
@click.argument('expressions', nargs=-1)
@required_option('--product', 'products', multiple=True)
@click.option('--measurement')
@click.option('--computed-measurement')
@click.option('--crs')
@required_option('--interval', help="int[y|m] eg. 1y, 6m, 3m")
@required_option('--duration', help="int[y|m] eg. 2y, 1y, 6m, 3m")
@required_option('--stat', 'stat', type=click.Choice(AVAILABLE_STATS))
@click.option('--mask', 'masks', multiple=True)
@ui.pass_index(app_name='agdc-stats-app')
def main(index, products, measurement, computed_measurement, interval, duration, masks, crs, stat,
         expressions, executor):
    """
    Compute Statistical Summaries

    Select data using [EXPRESSIONS] to limit by date and spatial extent.
    eg. 1996-01-01<time<1996-12-31


    May select a single measurement, or a single computed measurement

    Tassel Cap Index is a problem

    Interval: Eg. 1 year, 6 months, 3 months, 1 month, 1 week.


    """
    tasks = create_stats_tasks(products, measurement, computed_measurement, interval, duration, masks, stat,
                               crs, expressions)

    results = execute_tasks(executor, index, tasks)

    process_results(executor, results)


def create_stats_tasks(products, measurement, computed_measurement, interval, duration, masks, stat,
                       crs, expressions):
    tasks = []
    start_date, end_date = get_start_end_dates(expressions)
    for acq_range in get_epochs(interval, duration, start_date, end_date):
        task = dict(products=products, acq_range=acq_range, measurement=measurement, crs=crs,
                    stat=stat, masks=masks, expressions=expressions,
                    computed_measurement=computed_measurement)
        tasks.append(task)
    return tasks


def get_start_end_dates(expressions):
    parsed = parse_expressions(*expressions)
    time_range = parsed['time']
    return time_range.begin, time_range.end


def execute_tasks(executor, index, tasks):
    results = []
    dc = Datacube(index=index)
    for task in tasks:
        result_future = executor.submit(load_data, dc=dc, **task)
        results.append(result_future)
    return results


def process_results(executor, results):
    for result in executor.as_completed(results):
        epoch_start_date, dataset = executor.result(result)
        print(epoch_start_date, dataset)


# def old_main(argv):
#     season = 'WINTER'
#     sat = 'LANDSAT_5'
#     band = 'NDVI'
#     epoch = 1
#     start_str = '2009-01-01'
#     end_str = '2011-01-01'
#     masks = 'PQ_MASK_CLEAR_ELB'
#     stats = 'PERCENTILE_25'
#     dataset = 'nbar'
#     interpolation = 'nearest'
#     opts, args = getopt.getopt(argv, "hn:l:d:b:i:m:p:s:e:work_queue:z:o:x",
#                                ["lon=", "lat=", "dataset=", "band=", "stats=", "masks=", "epoch=", "start=", "end=",
#                                 "season=", "sat=", "odir=", "interpolation="])
#     for opt, arg in opts:
#         if opt == '-h':
#             print('pass lon lat min max value like 130.378239-130.7823 -30.78276/-30.238')
#             print(' For ex. python stats_jupyter.py -n 146.002/146.202 -l -34.970/-34.999 -i PERCENTILE_10 -s '
#                   '2009-01-01 -e 2010-12-03 -z LANDSAT_5,LANDSAT_7 -work_queue CALENDAR_YEAR -m PQ_MASK_CLEAR '
#                   '-b NDVI -p 2 -d nbar')
#             print('python stats_jupyter.py -o <output_dir> -n <lon> -l <lat> -d <dataset> -i <stats> '
#                   '-m <masks> -p <epoch> -s <start_date> -e <end_date> '
#                   '-z <sat> -work_queue <season> -x <interpolation>')
#             sys.exit()


def get_epochs(interval, duration, start, end):
    freq, interval = parse_interval(interval)
    duration = parse_duration(duration)
    for start_dt in rrule(freq, interval=interval, dtstart=start, until=end):
        acq_min = start_dt
        acq_max = acq_min + duration
        acq_min = max(start, acq_min)
        acq_max = min(end, acq_max)
        yield acq_min, acq_max


def parse_interval(interval):
    if interval[-1:] == 'y':
        freq = YEARLY
    elif interval[-1:] == 'm':
        freq = MONTHLY
    else:
        raise ValueError('Interval "{}" not in months or years'.format(interval))
    interval = int(interval[:-1])
    return freq, interval


def parse_duration(duration):
    if duration[-1:] == 'y':
        delta = {'years': int(duration[:-1])}
    elif duration[-1:] == 'm':
        delta = {'months': int(duration[:-1])}
    else:
        raise ValueError('Duration "{}" not in months or years'.format(duration))

    return relativedelta(days=-1, **delta)


def compute_measurement(measurement, data, prodname=None):
    # Return a Dataset instead of a DataArray

    blue = data.blue.where(data.blue != data.blue.nodata)
    green = data.green.where(data.green != data.green.nodata)
    red = data.red.where(data.red != data.red.nodata)
    nir = data.nir.where(data.nir != data.nir.nodata)
    sw1 = data.swir1.where(data.swir1 != data.swir1.nodata)
    sw2 = data.swir2.where(data.swir2 != data.swir2.nodata)
    if measurement == "NDFI":
        return (sw1 - nir) / (sw1 + nir)
    if measurement == "NDVI":
        return (nir - red) / (nir + red)
    if measurement == "NDWI":
        return (green - nir) / (green + nir)
    if measurement == "MNDWI":
        return (green - sw1) / (green + sw1)
    if measurement == "NBR":
        return (nir - sw2) / (nir + sw2)
    if measurement == "TCI":
        return calculate_tci(prodname, blue=blue, green=green, red=red, nir=nir, sw1=sw1, sw2=sw2)

COMPUTED_MEASUREMENT_REQS = {
    'NDFI': {'sw1', 'nir'},
    'NDVI': {'nir', 'red'},
    'NDWI': {'green', 'nir'},
    'MNDWI': {'green', 'sw1'},
    'NBR': {'nir', 'sw2'}
}


def get_band_data(data, measurement):
    data[measurement] = data[measurement].where(data[measurement] != data[measurement].nodata)
    return data

VALID_MASKS = {"PQ_MASK_CONTIGUITY", "PQ_MASK_CLOUD_FMASK", "PQ_MASK_CLOUD_ACCA", "PQ_MASK_CLOUD_SHADOW_ACCA",
               "PQ_MASK_SATURATION", "PQ_MASK_SATURATION_OPTICAL", "PQ_MASK_SATURATION_THERMAL"}


def create_mask_def(masks):
    ga_pqa_mask_def = {name: True for name in
                       ('swir2_saturated',
                        'red_saturated',
                        'blue_saturated',
                        'nir_saturated',
                        'green_saturated',
                        'tir_saturated',
                        'swir1_saturated')}
    ga_pqa_mask_def.update(dict(contiguous=False, land_sea='land', cloud_shadow_acca='no_cloud_shadow',
                                cloud_acca='no_cloud', cloud_fmask='no_cloud',
                                cloud_shadow_fmask='no_cloud_shadow'))

    for mask in masks:
        if mask == "PQ_MASK_CONTIGUITY":
            ga_pqa_mask_def['contiguous'] = True
        if mask == "PQ_MASK_CLOUD_FMASK":
            ga_pqa_mask_def['cloud_fmask'] = 'no_cloud'
        if mask == "PQ_MASK_CLOUD_ACCA":
            ga_pqa_mask_def['cloud_acca'] = 'no_cloud_shadow'
        if mask == "PQ_MASK_CLOUD_SHADOW_ACCA":
            ga_pqa_mask_def['cloud_shadow_acca'] = 'no_cloud_shadow'
        if mask == "PQ_MASK_SATURATION":
            ga_pqa_mask_def.update(dict(blue_saturated=False, green_saturated=False, red_saturated=False,
                                        nir_saturated=False, swir1_saturated=False, tir_saturated=False,
                                        swir2_saturated=False))
        if mask == "PQ_MASK_SATURATION_OPTICAL":
            ga_pqa_mask_def.update(dict(blue_saturated=False, green_saturated=False, red_saturated=False,
                                        nir_saturated=False, swir1_saturated=False, swir2_saturated=False))
        if mask == "PQ_MASK_SATURATION_THERMAL":
            ga_pqa_mask_def['tir_saturated'] = False

    return ga_pqa_mask_def


def load_data(dc, products, measurement, computed_measurement, acq_range, stat, masks,
              expressions, crs=None):
    datasets = []
    epoch_start_date, _ = acq_range

    search_filters = parse_expressions(*expressions)

    search_filters['time'] = acq_range
    if crs:
        search_filters['crs'] = crs

    required_measurements = calc_required_measurements(measurement, computed_measurement)

    for prodname in products:
        _log.debug("Loading data found for product %s the date range %s expressions %s", prodname,
                   acq_range, expressions)

        dataset = dc.load(product=prodname,
                          measurements=required_measurements,
                          **search_filters)
        dataset.attrs['product'] = prodname

        if len(dataset) == 0:
            _log.info("No data found for {} matching {}", prodname, search_filters)
            continue
        if masks:
            dataset = mask_data_with_pq(dc, dataset, prodname, search_filters, masks)

        dataset = group_by_solar_day(dataset)

        import ipdb; ipdb.set_trace()
        if measurement:
            dataset = get_band_data(dataset, measurement)
        elif computed_measurement:
            dataset = compute_measurement(dataset, computed_measurement, prodname)
        # These aren't actually datasets here at the moment, they're DataArrays
        # Lets make them datasets, so that we can compute stat on multiple measurements at once
        datasets.append(dataset)

    datasets = xr.concat(datasets, dim='solar_day')

    if datasets.nbytes > 0:
        output_dataset = do_compute(datasets, stat)
        return epoch_start_date, output_dataset
    else:
        return None


def calc_required_measurements(measurement, computed_measurement):
    if measurement:
        return [measurement]
    else:
        return list(COMPUTED_MEASUREMENT_REQS[computed_measurement])


def group_by_solar_day(dataset):
    append_solar_day(dataset)
    return dataset.groupby('solar_day').max(dim='time', keep_attrs=True)


def output_dtype(stat, measurement):
    if stat == "COUNT_OBSERVED" or measurement in [t.name for t in Ls57Arg25Bands]:
        return np.int16
    else:
        return np.float32


def mask_data_with_pq(dc, data, prodname, parsed_expressions, masks):
    mask_clear = None
    mask_product_name = find_product_mask_name(prodname)
    pq = dc.load(product=mask_product_name,
                 **parsed_expressions)
    if len(pq) > 0:
        for mask in masks:
            if mask == "PQ_MASK_CLEAR_ELB":
                mask_clear = pq['pixelquality'] & 15871 == 15871
            elif mask == "PQ_MASK_CLEAR":
                mask_clear = pq['pixelquality'] & 16383 == 16383
            else:
                mask_clear = make_mask(pq, **create_mask_def(masks))
        data = data.where(mask_clear)
    else:
        _log.info("\t No PQ data exists")
    return data


def find_product_mask_name(datavar_name):
    if 'nbart' in datavar_name:
        return datavar_name.replace('nbart', 'pq')
    else:
        return datavar_name.replace('nbar', 'pq')


class TasselCapIndex(Enum):
    BRIGHTNESS = 1
    GREENNESS = 2
    WETNESS = 3
    FOURTH = 4
    FIFTH = 5
    SIXTH = 6


class Landsats(Enum):
    LANDSAT_5 = "ls5_nbar_albers"
    LANDSAT_7 = "ls7_nbar_albers"
    LANDSAT_8 = "ls8_nbar_albers"


class SixUniBands(Enum):
    BLUE = 'blue'
    GREEN = 'green'
    RED = 'red'
    NEAR_INFRARED = 'nir'
    SHORT_WAVE_INFRARED_1 = 'sw1'
    SHORT_WAVE_INFRARED_2 = 'sw2'


TCI_COEFF = {
    Landsats.LANDSAT_5:
        {
            TasselCapIndex.BRIGHTNESS: {
                SixUniBands.BLUE: 0.3037,
                SixUniBands.GREEN: 0.2793,
                SixUniBands.RED: 0.4743,
                SixUniBands.NEAR_INFRARED: 0.5585,
                SixUniBands.SHORT_WAVE_INFRARED_1: 0.5082,
                SixUniBands.SHORT_WAVE_INFRARED_2: 0.1863},

            TasselCapIndex.GREENNESS: {
                SixUniBands.BLUE: -0.2848,
                SixUniBands.GREEN: -0.2435,
                SixUniBands.RED: -0.5436,
                SixUniBands.NEAR_INFRARED: 0.7243,
                SixUniBands.SHORT_WAVE_INFRARED_1: 0.0840,
                SixUniBands.SHORT_WAVE_INFRARED_2: -0.1800},

            TasselCapIndex.WETNESS: {
                SixUniBands.BLUE: 0.1509,
                SixUniBands.GREEN: 0.1973,
                SixUniBands.RED: 0.3279,
                SixUniBands.NEAR_INFRARED: 0.3406,
                SixUniBands.SHORT_WAVE_INFRARED_1: -0.7112,
                SixUniBands.SHORT_WAVE_INFRARED_2: -0.4572},

            TasselCapIndex.FOURTH: {
                SixUniBands.BLUE: -0.8242,
                SixUniBands.GREEN: 0.0849,
                SixUniBands.RED: 0.4392,
                SixUniBands.NEAR_INFRARED: -0.0580,
                SixUniBands.SHORT_WAVE_INFRARED_1: 0.2012,
                SixUniBands.SHORT_WAVE_INFRARED_2: -0.2768},

            TasselCapIndex.FIFTH: {
                SixUniBands.BLUE: -0.3280,
                SixUniBands.GREEN: 0.0549,
                SixUniBands.RED: 0.1075,
                SixUniBands.NEAR_INFRARED: 0.1855,
                SixUniBands.SHORT_WAVE_INFRARED_1: -0.4357,
                SixUniBands.SHORT_WAVE_INFRARED_2: 0.8085},

            TasselCapIndex.SIXTH: {
                SixUniBands.BLUE: 0.1084,
                SixUniBands.GREEN: -0.9022,
                SixUniBands.RED: 0.4120,
                SixUniBands.NEAR_INFRARED: 0.0573,
                SixUniBands.SHORT_WAVE_INFRARED_1: -0.0251,
                SixUniBands.SHORT_WAVE_INFRARED_2: 0.0238}
        },
    Landsats.LANDSAT_8:
        {
            TasselCapIndex.BRIGHTNESS: {
                SixUniBands.BLUE: 0.3029,
                SixUniBands.GREEN: 0.2786,
                SixUniBands.RED: 0.4733,
                SixUniBands.NEAR_INFRARED: 0.5599,
                SixUniBands.SHORT_WAVE_INFRARED_1: 0.508,
                SixUniBands.SHORT_WAVE_INFRARED_2: 0.1872},

            TasselCapIndex.GREENNESS: {
                SixUniBands.BLUE: -0.2941,
                SixUniBands.GREEN: -0.2430,
                SixUniBands.RED: -0.5424,
                SixUniBands.NEAR_INFRARED: 0.7276,
                SixUniBands.SHORT_WAVE_INFRARED_1: 0.0713,
                SixUniBands.SHORT_WAVE_INFRARED_2: -0.1608},

            TasselCapIndex.WETNESS: {
                SixUniBands.BLUE: 0.1511,
                SixUniBands.GREEN: 0.1973,
                SixUniBands.RED: 0.3283,
                SixUniBands.NEAR_INFRARED: 0.3407,
                SixUniBands.SHORT_WAVE_INFRARED_1: -0.7117,
                SixUniBands.SHORT_WAVE_INFRARED_2: -0.4559},

            TasselCapIndex.FOURTH: {
                SixUniBands.BLUE: -0.8239,
                SixUniBands.GREEN: 0.0849,
                SixUniBands.RED: 0.4396,
                SixUniBands.NEAR_INFRARED: -0.058,
                SixUniBands.SHORT_WAVE_INFRARED_1: 0.2013,
                SixUniBands.SHORT_WAVE_INFRARED_2: -0.2773},

            TasselCapIndex.FIFTH: {
                SixUniBands.BLUE: -0.3294,
                SixUniBands.GREEN: 0.0557,
                SixUniBands.RED: 0.1056,
                SixUniBands.NEAR_INFRARED: 0.1855,
                SixUniBands.SHORT_WAVE_INFRARED_1: -0.4349,
                SixUniBands.SHORT_WAVE_INFRARED_2: 0.8085},

            TasselCapIndex.SIXTH: {
                SixUniBands.BLUE: 0.1079,
                SixUniBands.GREEN: -0.9023,
                SixUniBands.RED: 0.4119,
                SixUniBands.NEAR_INFRARED: 0.0575,
                SixUniBands.SHORT_WAVE_INFRARED_1: -0.0259,
                SixUniBands.SHORT_WAVE_INFRARED_2: 0.0252}
        }
}

TCI_COEFF[Landsats.LANDSAT_7] = TCI_COEFF[Landsats.LANDSAT_5]


def calculate_tci(prodname, **bands):
    bands_masked = {SixUniBands(colour): data.astype(np.float16) for colour, data in bands.items()}

    coefficients = TCI_COEFF[Landsats(prodname)]

    tci = 0

    for b in SixUniBands:
        if b in coefficients:
            tci += bands_masked[b] * coefficients[b]

    tci = tci.filled(np.nan)
    return tci


# https://gist.github.com/andrewdhicks/57c0503c0117695cdf136540bfae0749
# from datacube.api.masking import get_flags_def
# fd = get_flags_def(pq.pixelquality)
# valid_bit = fd['contiguous']['bits']
#
#
# def pq_fuser(dest, src):
#     valid_val = (1 << valid_bit)
#
#     no_data_dest_mask = ~(dest & valid_val).astype(bool)
#     np.copyto(dest, src, where=no_data_dest_mask)
#
#     both_data_mask = (valid_val & dest & src).astype(bool)
#     np.copyto(dest, src & dest, where=both_data_mask)

if __name__ == '__main__':
    main()
