#!/usr/bin/env python

# ===============================================================================
# Copyright (c)  2016 Geoscience Australia
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither Geoscience Australia nor the names of its contributors may be
#       used to endorse or promote products derived from this software
#       without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
# ===============================================================================


"""
    Calculates stats for time series LANDSAT data
    __author__ = 'u81051'
"""

from __future__ import absolute_import
from __future__ import division
import argparse
import logging
import os
import sys
from collections import namedtuple
from itertools import product
import datetime
import abc
from enum import Enum
import dask
import numpy as np
import luigi
from luigi.task import flatten
from datacube.api.utils_v1 import parse_date_min, parse_date_max, PqaMask, Statistic, writeable_dir
from datacube.api.utils_v1 import pqa_mask_arg, statistic_arg, season_arg
from datacube.api.model_v1 import Ls57Arg25Bands, Ls8Arg25Bands, NdviBands, NdfiBands, TciBands, Pq25Bands, Fc25Bands
from datacube.api.model_v1 import Wofs25Bands, NdwiBands, MndwiBands, EviBands, NbrBands, DsmBands
from datacube.api.model_v1 import DATASET_TYPE_DATABASE, DATASET_TYPE_DERIVED_NBAR, DatasetType
from datacube.api.utils_v1 import PercentileInterpolation, SEASONS
from datacube.api.utils_v1 import Season, NDV, build_season_date_criteria

from datacube.index import index_connect
# from datacube.api import make_mask, list_flag_names
# from datacube.api.fast import geomedian
from datacube.api.tci_utils import calculate_tci
import datacube.api
import xarray as xr
import dateutil.relativedelta as relativedelta
from datacube.api.geo_xarray import _solar_day, _get_mean_longitude
from datacube.api import GridWorkflow
from datacube.storage.masking import list_flag_names, describe_variable_flags, make_mask
from datacube.api.app_utils import product_lookup, write_crs_attributes, write_global_attributes
from datacube.api.app_utils import do_compute, get_derive_data, get_band_data, apply_mask, config_loader
from datacube.api.app_utils import make_stats_config, stats_extra_metadata

dask.set_options(get=dask.async.get_sync)
# dask.set_options(get=dask.threaded.get)
_log = logging.getLogger()

_log.setLevel(logging.DEBUG)

EpochParameter = namedtuple('Epoch', ['increment', 'duration'])


class Satellite(Enum):
    """
       Order and satellite names
    """
    __order__ = "LANDSAT_5 LANDSAT_7 LANDSAT_8"

    LANDSAT_5 = "LANDSAT_5"
    LANDSAT_7 = "LANDSAT_7"
    LANDSAT_8 = "LANDSAT_8"


def satellite_arg(s):
    if s in [sat.name for sat in Satellite]:
        return Satellite[s]
    raise argparse.ArgumentTypeError("{0} is not a supported satellite".format(s))


def dataset_type_arg(s):
    if s in [t.name for t in DatasetType]:
        return DatasetType[s]
    raise argparse.ArgumentTypeError("{0} is not a supported dataset type".format(s))


# support all bands
def all_arg_band_arg(s):  # pylint: disable=too-many-branches
    bandclass = None
    if s in [t.name for t in Ls57Arg25Bands]:
        bandclass = Ls57Arg25Bands[s]
    elif s in [t.name for t in NdviBands]:
        bandclass = NdviBands[s]
    elif s in [t.name for t in TciBands]:
        bandclass = TciBands[s]
    elif s in [t.name for t in Ls8Arg25Bands]:
        bandclass = Ls8Arg25Bands[s]
    elif s in [t.name for t in Pq25Bands]:
        bandclass = Pq25Bands[s]
    elif s in [t.name for t in Fc25Bands]:
        bandclass = Fc25Bands[s]
    elif s in [t.name for t in Wofs25Bands]:
        bandclass = Wofs25Bands[s]
    elif s in [t.name for t in NdwiBands]:
        bandclass = NdwiBands[s]
    elif s in [t.name for t in NdfiBands]:
        bandclass = NdfiBands[s]
    elif s in [t.name for t in MndwiBands]:
        bandclass = MndwiBands[s]
    elif s in [t.name for t in EviBands]:
        bandclass = EviBands[s]
    elif s in [t.name for t in NbrBands]:
        bandclass = NbrBands[s]
    elif s in [t.name for t in DsmBands]:
        bandclass = DsmBands[s]
    else:
        raise argparse.ArgumentTypeError("{0} is not a supported band supported band"
                                         .format(s))
    return bandclass


def percentile_interpolation_arg(s):
    if s in [t.name for t in PercentileInterpolation]:
        return PercentileInterpolation[s]
    raise argparse.ArgumentTypeError("{0} is not a supported percentile interpolation"
                                     .format(s))


class Task(luigi.Task):         # pylint: disable=metaclass-assignment
    __metaclass__ = abc.ABCMeta

    def complete(self):

        for output in flatten(self.output()):
            if not output.exists():
                return False
        for dep in flatten(self.deps()):
            if not dep.complete():
                return False
        return True

    @abc.abstractmethod
    def output(self):
        return


class StatsTask(object):       # pylint: disable=too-many-instance-attributes
    def __init__(self, name="Band Statistics Workflow"):

        self.name = name
        self.parser = argparse.ArgumentParser(prog=sys.argv[0],
                                              description=self.name)
        self.x_min = None
        self.y_min = None
        self.acq_min = None
        self.acq_max = None
        self.epoch = None
        self.seasons = None
        self.satellites = None
        self.output_directory = None
        self.mask_pqa_apply = False
        self.mask_pqa_mask = None
        self.local_scheduler = None
        self.workers = None
        self.dataset_type = None
        self.bands = None
        self.chunk_size = None
        self.statistics = None
        self.interpolation = None
        self.evi_args = None

    def setup_arguments(self):
        # pylint: disable=range-builtin-not-iterating
        self.parser.add_argument("--x-min", help="X index for cells", action="store", dest="x_min", type=int,
                                 choices=range(-99, 98 + 1), required=True,
                                 metavar="-99 ... 99")

        self.parser.add_argument("--y-min", help="Y index for cells", action="store", dest="y_min", type=int,
                                 choices=range(-99, 98 + 1), required=True,
                                 metavar="-99 ... 99")

        self.parser.add_argument("--output-directory", help="output directory", action="store", dest="output_directory",
                                 type=writeable_dir, required=True)

        self.parser.add_argument("--acq-min", help="Acquisition Date", action="store", dest="acq_min", type=str,
                                 default="1985")

        self.parser.add_argument("--acq-max", help="Acquisition Date", action="store", dest="acq_max", type=str,
                                 default="2014")

        self.parser.add_argument("--epoch",
                                 help="Epoch increment and duration (e.g. 5 6 means 1985-1990, 1990-1995, etc)",
                                 action="store", dest="epoch", type=int, nargs=2, default=[5, 6])

        self.parser.add_argument("--satellite", help="The satellite(s) to include", action="store", dest="satellites",
                                 type=str, nargs="+",
                                 default=["LANDSAT_5", "LANDSAT_7", "LANDSAT_8"])

        self.parser.add_argument("--mask-pqa-apply", help="Apply PQA mask", action="store_true", dest="mask_pqa_apply",
                                 default=False)

        self.parser.add_argument("--mask-pqa-mask", help="The PQA mask to apply", action="store", dest="mask_pqa_mask",
                                 type=pqa_mask_arg, nargs="+", choices=PqaMask,
                                 default=[PqaMask.PQ_MASK_CLEAR_ELB,], 
                                 metavar=" ".join([ts.name for ts in PqaMask]))

        self.parser.add_argument("--local-scheduler", help="Use local luigi scheduler rather than MPI",
                                 action="store_true",
                                 dest="local_scheduler", default=False)

        self.parser.add_argument("--workers", help="Number of worker tasks", action="store", dest="workers", type=int,
                                 default=16)

        group = self.parser.add_mutually_exclusive_group()

        group.add_argument("--quiet", help="Less output", action="store_const", dest="log_level", const=logging.WARN)
        group.add_argument("--verbose", help="More output", action="store_const", dest="log_level", const=logging.DEBUG)

        self.parser.set_defaults(log_level=logging.INFO)
        self.parser.add_argument("--dataset-type", help="The type of dataset to process", action="store",
                                 dest="dataset_type", type=dataset_type_arg, choices=self.get_supported_dataset_types(),
                                 default=DatasetType.nbar,
                                 metavar=" ".join([dt.name for dt in self.get_supported_dataset_types()]))
        self.parser.add_argument("--band", help="The band(s) to process", action="store",
                                 default=Ls57Arg25Bands,  # required=True,
                                 dest="bands", type=all_arg_band_arg, nargs="+",
                                 metavar=" ".join([b.name for b in Ls57Arg25Bands]))
        self.parser.add_argument("--chunk-size", help="dask chunk size", action="store", dest="chunk_size", type=int,
                                 choices=range(1, 4000 + 1),
                                 default=1000,  # required=True
                                 metavar="0 ... 4000")
        self.parser.add_argument("--statistic", help="The statistic(s) to produce", action="store",
                                 default=[Statistic.PERCENTILE_10, Statistic.PERCENTILE_50, Statistic.PERCENTILE_90],
                                 dest="statistic", type=statistic_arg, nargs="+",
                                 metavar=" ".join([s.name for s in Statistic]))
        self.parser.add_argument("--interpolation", help="The interpolation method to use", action="store",
                                 default=PercentileInterpolation.NEAREST,  # required=True,
                                 dest="interpolation", type=percentile_interpolation_arg,
                                 metavar=" ".join([s.name for s in PercentileInterpolation]))
        self.parser.add_argument("--season", help="The seasons for which to produce statistics", action="store",
                                 default=Season,  # required=True,
                                 dest="season", type=season_arg,  nargs='+',
                                 metavar=" ".join([s.name for s in Season]))
        self.parser.add_argument("--evi-args", help="evi args(e.g. 2.5,1,6,7.5 for G,L,C1 and C2)",
                                 metavar="G,L,C1 and C2 2.5, 1, 6, 7.5",
                                 action="store", dest="evi_args", type=float, nargs=4, default=[2.5, 1, 6, 7.5])
        self.parser.add_argument("--period", help="day intervals", action="store", dest="period", type=str,
                                 default="1201-0204")
        self.parser.add_argument("--date-list", help="list of acq dates", action="store", dest="date_list", type=str,
                                 default="2016-01-01,2016-03-21")

    def process_arguments(self, args):

        # # Call method on super class
        # # super(self.__class__, self).process_arguments(args)
        # workflow.Workflow.process_arguments(self, args)

        self.x_min = args.x_min
        self.y_min = args.y_min
        self.output_directory = args.output_directory
        self.acq_min = parse_date_min(args.acq_min)
        self.acq_max = parse_date_max(args.acq_max)
        self.satellites = args.satellites
        if args.epoch:
            self.epoch = EpochParameter(int(args.epoch[0]), int(args.epoch[1]))
        self.seasons = args.season
        self.mask_pqa_apply = args.mask_pqa_apply
        self.mask_pqa_mask = args.mask_pqa_mask
        self.local_scheduler = args.local_scheduler
        self.workers = args.workers
        _log.setLevel(args.log_level)
        self.dataset_type = args.dataset_type
        self.bands = args.bands
        self.chunk_size = args.chunk_size
        self.statistics = args.statistic
        self.evi_args = args.evi_args
        self.period = args.period
        self.date_list = args.date_list

        if args.interpolation:
            self.interpolation = args.interpolation
        else:
            self.interpolation = [PercentileInterpolation.NEAREST]

    def log_arguments(self):

        _log.info("\t x = %03d, y = %03d acq = {%s} to {%s} epoch = {%d/%d} satellites = {%s} bands = %s ",
                  self.x_min, self.y_min, self.acq_min, self.acq_max, self.epoch.increment, self.epoch.duration,
                  " ".join(self.satellites), " ".join([b.name for b in self.bands]))
        _log.info("\t output directory = {%s} PQ apply = %s PQA mask = %s local scheduler = %s workers = %s",
                  self.output_directory, self.mask_pqa_apply, self.mask_pqa_apply and
                  " ".join([mask.name for mask in self.mask_pqa_mask]) or "", self.local_scheduler, self.workers)
        _log.info("\t dataset to retrieve %s dask chunk size = %d seasons = %s statistics = %s interpolation = %s Tidal dates are %s",
                  self.dataset_type, self.chunk_size, self.seasons,
                  " ".join([s.name for s in self.statistics]), self.interpolation.name, self.date_list)

    def get_epochs(self):

        from dateutil.rrule import rrule, YEARLY
        from dateutil.relativedelta import relativedelta

        for season in self.seasons:
            if season.name == "TIDAL":
                yield self.get_tidal_date_ranges()
        for dt in rrule(YEARLY, interval=self.epoch.increment, dtstart=self.acq_min, until=self.acq_max):
            acq_min = dt.date()
            acq_max = acq_min + relativedelta(years=self.epoch.duration, days=-1)
            acq_min = max(self.acq_min, acq_min)
            acq_max = min(self.acq_max, acq_max)
            yield acq_min, acq_max
         
    def get_tidal_date_ranges(self):
        self.date_list = self.date_list.split(',')
        self.date_list.sort(key=lambda date: datetime.datetime.strptime(date, '%Y-%m-%d'))
        self.date_list = [datetime.datetime.strptime(date, "%Y-%m-%d").date() for date in self.date_list] 
        acq_min = self.date_list[0]
        acq_max =  self.date_list[len(self.date_list)-1]
        return acq_min, acq_max

    @staticmethod
    def get_supported_dataset_types():
        return DATASET_TYPE_DATABASE + DATASET_TYPE_DERIVED_NBAR

    def get_seasons(self):
        for season in self.seasons:
            yield season

    def create_all_tasks(self):
        cells = (self.x_min, self.y_min)
        _log.info(" cell values  %s", cells)
        for ((acq_min, acq_max), season, band, statistic) in product(self.get_epochs(), self.get_seasons(),
                                                                     self.bands, self.statistics):
            _log.info("epoch returns date min %s max %s", acq_min, acq_max)
            acq_min_extended, acq_max_extended, criteria = build_season_date_criteria(acq_min, acq_max,
                                                                                      season,
                                                                                      extend=True)
            '''
            mindt = (int(criteria[0][0].strftime("%Y")), int(criteria[0][0].strftime("%m")),
                     int(criteria[0][0].strftime("%d")))
            maxdt = (int(criteria[0][1].strftime("%Y")), int(criteria[0][1].strftime("%m")),
                     int(criteria[0][1].strftime("%d")))
            '''
            mindt = (int(acq_min_extended.strftime("%Y")), int(acq_min_extended.strftime("%m")),
                     int(acq_min_extended.strftime("%d")))
            maxdt = (int(acq_max_extended.strftime("%Y")), int(acq_max_extended.strftime("%m")),
                     int(acq_max_extended.strftime("%d")))
            _log.info("Creating task at %s for epoch stats %s %s %s %s %s crit min date %s , crit max date %s",
                      str(datetime.datetime.now()),
                      self.x_min, self.y_min, acq_min_extended, acq_max_extended, season, mindt, maxdt)
            yield self.create_new_task(x=self.x_min, y=self.y_min, acq_min=acq_min_extended, acq_max=acq_max_extended,
                                       season=season, dataset_type=self.dataset_type, band=band,
                                       mask_pqa_apply=self.mask_pqa_apply, mask_pqa_mask=self.mask_pqa_mask,
                                       chunk_size=self.chunk_size, statistic=statistic, statistics=self.statistics,
                                       interpolation=self.interpolation, evi_args=self.evi_args, period=self.period,
                                       date_list=self.date_list)

    # pylint: disable=too-many-arguments
    def create_new_task(self, x, y, acq_min, acq_max, season, dataset_type, band, mask_pqa_apply,
                        mask_pqa_mask, chunk_size, statistic, statistics, interpolation,
                        evi_args, period, date_list):
        return EpochStatisticsTask(x_cell=x, y_cell=y, acq_min=acq_min, acq_max=acq_max,
                                   season=season, satellites=self.satellites,
                                   dataset_type=dataset_type, band=band,
                                   mask_pqa_apply=mask_pqa_apply, mask_pqa_mask=mask_pqa_mask,
                                   chunk_size=chunk_size, statistic=statistic,
                                   statistics=statistics, interpolation=interpolation,
                                   output_directory=self.output_directory, evi_args=evi_args, period=period,
                                   date_list=date_list)

    def run(self):

        self.setup_arguments()
        self.process_arguments(self.parser.parse_args())
        self.log_arguments()
        if self.local_scheduler:
            luigi.build(self.create_all_tasks(), local_scheduler=self.local_scheduler, workers=self.workers)
        else:
            import luigi.contrib.mpi as mpi
            mpi.run(self.create_all_tasks())


class EpochStatisticsTask(Task):     # pylint: disable=abstract-method
    x_cell = luigi.IntParameter()
    y_cell = luigi.IntParameter()
    acq_min = luigi.DateParameter()
    acq_max = luigi.DateParameter()
    season = luigi.Parameter()
    # epochs = luigi.Parameter(is_list=True, significant=False)
    satellites = luigi.Parameter()
    dataset_type = luigi.Parameter()
    band = luigi.Parameter()
    mask_pqa_apply = luigi.BoolParameter()
    mask_pqa_mask = luigi.Parameter()
    chunk_size = luigi.IntParameter()
    statistic = luigi.Parameter()
    statistics = luigi.Parameter()
    interpolation = luigi.Parameter()
    output_directory = luigi.Parameter()
    evi_args = luigi.FloatParameter()
    period = luigi.Parameter()
    date_list = luigi.Parameter()

    def output(self):

        season = SEASONS[self.season]
        sat = ",".join(self.satellites)
        acq_min = self.acq_min
        acq_max = self.acq_max
        season_start = "{month}{day:02d}".format(month=season[0][0].name[:3], day=season[0][1])
        season_start = season_start + "_"
        season_end = "{month}{day:02d}".format(month=season[1][0].name[:3], day=season[1][1])
        if self.season.name == "DUMMY":
            st, en = self.period.split("_")
            season_start = datetime.datetime.strptime(st, "%m%d").date().strftime("%b").upper() + \
                           datetime.datetime.strptime(st, "%m%d").date().strftime("%d") + '_' + \
            season_end = datetime.datetime.strptime(en, "%m%d").date().strftime("%b").upper() + \
                         datetime.datetime.strptime(en, "%m%d").date().strftime("%d")
        elif self.season.name == "TIDAL":
            season_start = 'TIDAL'
            season_end = ''
        
        sea = season_start + season_end    
        filename = "{sat}_{prod}_{x:03d}_{y:03d}_{acq_min}_{acq_max}_{sea}_{band}_{stat}.nc" \
                   .format(sat=sat, prod=str(self.dataset_type.name).upper(),
                           x=self.x_cell, y=self.y_cell, acq_min=acq_min, acq_max=acq_max, sea=sea,
                           band=self.band.name, stat=self.statistic.name)
        return luigi.LocalTarget(os.path.join
                                 (self.output_directory, filename))

    def initialise_odata(self, dtype):
        shape = (4000, 4000)
        nbar = np.empty(shape, dtype=dtype)
        nbar.fill(NDV)
        return nbar

    def get_stats(self, dc, dtype, prodname):        # pylint: disable=too-many-branches,too-many-statements
        # pylint: disable=too-many-boolean-expressions,too-many-locals

        mindt = (int(self.acq_min.strftime("%Y")), int(self.acq_min.strftime("%m")),
                     int(self.acq_min.strftime("%d")),0,0,0)
        maxdt = (int(self.acq_max.strftime("%Y")), int(self.acq_max.strftime("%m")),
                     int(self.acq_max.strftime("%d")),23,59,59)
        gw = GridWorkflow(index=dc.index, product=prodname)
        _log.info("\tcalling dataset for %3d %4d on band  %s stats  %s  in the date range  %s %s for satellite %s",
                  self.x_cell, self.y_cell, self.band.name, self.statistic.name, mindt, maxdt, self.satellites)
        pq = None
        my_cell = (self.x_cell, self.y_cell)
        data = gw.list_cells(my_cell, product=prodname, time=(mindt, maxdt), group_by='solar_day')
        cell_list_obj = data[my_cell]
        if data[my_cell]:
            data = gw.load(data[my_cell], dask_chunks={'time': len(data[my_cell]['sources']),
                                                       'y': self.chunk_size, 'x': self.chunk_size})
        else:
            _log.info("\t No data found for (%d %d) in the date range  %s %s", self.x_cell, self.y_cell,
                      mindt, maxdt)
            return
        _log.info("\tcalling dataset for %3d %4d on band  %s stats  %s  in the date range  %s %s for satellite %s data %s",
                  self.x_cell, self.y_cell, self.band.name, self.statistic.name, mindt, maxdt, self.satellites, data)
        origattr = data.attrs
        if self.mask_pqa_apply:
            prodname = product_lookup(self, 'pqa')
            pq = gw.list_cells(my_cell, product=prodname, time=(mindt, maxdt), group_by='solar_day')
            if pq:
                pq = gw.load(pq[my_cell], dask_chunks={'time': data.time.shape[0],
                                                       'y': self.chunk_size, 'x': self.chunk_size})
            else:
                _log.info("\t No PQ data exists")
            _log.info("\tpq dataset call completed for %3d %4d on band  %s stats  %s pqdata %s",
                      self.x_cell, self.y_cell, self.band.name, self.statistic.name, pq)


        season_dict = {'SUMMER': 'DJF', 'AUTUMN': 'MAM', 'WINTER': 'JJA', 'SPRING': 'SON',
                      'CALENDAR_YEAR': 'year', 'QTR_1': '1', 'QTR_2': '2',
                      'QTR_3': '3', 'QTR_4': '4'}
        #  _log.info("\t season name returned %s", season_dict[self.season.name])
        if "QTR" in self.season.name:
            data = data.isel(time=data.groupby('time.quarter').groups[int(season_dict[self.season.name])])
            pq = pq.isel(time=pq.groupby('time.quarter').groups[int(season_dict[self.season.name])])
        elif "CALENDAR" in self.season.name:
            year = int(str(data.groupby('time.year').groups.keys()).strip('[]'))
            data = data.isel(time=data.groupby('time.year').groups[year])
            pq = pq.isel(time=pq.groupby('time.year').groups[year])
        elif self.season.name == "TIDAL":
            # data = data.groupby('time.date').max(dim='time')
            #data = data.sel_points(date=self.date_list)
            data = data.sel_points(time=list(self.date_list))
            # pq = pq.groupby('time.date').max(dim='time')
            # pq = pq.groupby('time.date').max(dim='time')
            # pq = pq.sel_points(date=self.date_list)
            pq = pq.sel_points(time=list(self.date_list))
        else:
            data = data.isel(time=data.groupby('time.season').groups[season_dict[self.season.name]])
            pq = pq.isel(time=pq.groupby('time.season').groups[season_dict[self.season.name]])
        mask_clear = None
        tci_data = None
        if self.band.name in [t.name for t in Ls57Arg25Bands]:
            band_data = get_band_data(self, data)
        if pq and self.mask_pqa_apply:
            for mask in self.mask_pqa_mask:
                if mask.name == "PQ_MASK_CLEAR_ELB":
                    mask_clear = pq['pixelquality'] & 15871 == 15871
                elif mask.name == "PQ_MASK_CLEAR":
                    mask_clear = pq['pixelquality'] & 16383 == 16383
                else:
                    mask_clear = make_mask(pq, apply_mask())
            data = band_data.where(mask_clear)
        else:
            data = band_data
        _log.info("Received band %s data is %s ", self.band.name, band_data)
        data = data.chunk(chunks=(self.chunk_size, self.chunk_size))

        '''
        elif "DUMMY" in self.season.name:
            st, en = self.period.split("_")
            stdt = np.datetime64(self.acq_min.strftime("%Y") + '-' + st[:2] + '_' + st[2:])    
            endt = np.datetime64(self.acq_min.strftime("%Y") + '-' + en[:2] + '_' + en[2:])
            custom = np.array([dt for dt in data.time.values if dt >= stdt and 
                        dt <= endt]).astype('datetime64[D]')
            stdt = stdt + relativedelta(years=1)
            while stdt <= endt:
                custom = np.append(custom,np.array([dt for dt in data.time.values if dt >= stdt and
                                                   dt < (stdt + relativedelta(years=1))]).astype('datetime64[D]'))
                stdt = stdt + relativedelta(years=1)
            data['dummy_days'] = xr.DataArray(custom, coords={'time': data.time}, dims=['time'])
            data = data.groupby('dummy_days').max(dim='time')
        solar_days = np.array([_solar_day(dt, longitude) for dt in data.time.values]).astype('datetime64[D]')
        data['solar_day'] = xr.DataArray(solar_days, coords={'time': data.time}, dims=['time'])
        _log.info("\t checking duplicate dates  shape %s and data %s",
                  data.groupby('solar_day').max(dim='time').shape, data.groupby('solar_day').groups)

        if "DUMMY" in self.season.name:
            data = data.groupby('solar_day').max(dim='dummy_days')
        else:   
            data = data.groupby('solar_day').max(dim='time')
        '''

        # create a stats data variable
        stats_var = None
        odata = self.initialise_odata(dtype)
        if self.band.name in [t.name for t in Ls57Arg25Bands]:
            odata = do_compute(self, data, odata, dtype)
        else:
            ddata = get_derive_data(data)  # pylint: disable=redefined-variable-type
            odata = do_compute(self, ddata, odata, dtype)
        _log.info("Received band %s data is %s ", self.band.name, data)
        # variable name
        stats_var = str(self.statistic.name).lower()
        if stats_var == "standard_deviation":
            stats_var = "std_dev"
        if stats_var == "count_observed":
            stats_var = "count"
        stats_var = stats_var + "_" + self.acq_min.strftime("%Y")
        # data = data.isel(time=0).drop('time')
        if self.season.name == "TIDAL":
            data = data.isel(points=0).drop('time')
        else:
            data = data.isel(time=0).drop('time')
        data.data = odata
        stats_dataset = data.to_dataset(name=stats_var)
        stats_dataset.get(stats_var).attrs.clear()
        if self.band.name in [t.name for t in Ls57Arg25Bands]:
            stats_dataset.get(stats_var).attrs.update(dict(Comment1='Statistics calculated on ' +
                                                           self.band.name + 'for ' +
                                                                    self.dataset_type.name))
        else:
            stats_dataset.get(stats_var).attrs.update(dict(Comment1='Statistics calculated on ' +
                                                           self.dataset_type.name + ' datasets'))
            if (self.dataset_type.name).lower() == "evi":
                stats_dataset.get(stats_var).attrs.update(dict(Comment='Parameters ' +
                                                               str(self.evi_args) +
                                                               ' for G,L,C1,C2 are used respectively'))
            if (self.dataset_type.name).lower() == "tci":
                stats_dataset.get(stats_var).attrs.update(dict(Comment='This is based on  ' +
                                                               self.band.name + ' algorithm'))
        if self.season:
            stats_dataset.get(stats_var).attrs.update(dict(long_name=str(self.statistic.name).lower() +
                                                           ' seasonal statistics for ' +
                                                           str(self.season.name).lower() + ' of ' +
                                                           str("_".join(self.satellites)).lower()))
            stats_dataset.get(stats_var).attrs.update(dict(standard_name=str(self.statistic.name).lower() +
                                                           '_' + str(self.season.name).lower() + '_season_' +
                                                           str("_".join(self.satellites)).lower()))
        else:
            stats_dataset.get(stats_var).attrs.update(dict(long_name=str(self.statistic.name).lower() +
                                                           ' statistics for ' +
                                                           str("_".join(self.satellites)).lower() +
                                                           ' and duration  ' + self.acq_min.strftime("%Y%mm%dd") + '-' +
                                                           self.acq_max.strftime("%Y%mm%dd")))
            stats_dataset.get(stats_var).attrs.update(dict(standard_name=str(self.statistic.name).lower() +
                                                           '_' + self.acq_min.strftime("%Y%mm%dd") + '-' +
                                                           self.acq_max.strftime("%Y%mm%dd") + '_' +
                                                           str("_".join(self.satellites)).lower()))
        if 'PERCENTILE' in self.statistic.name:
            stats_dataset.get(stats_var).attrs.update(dict(Comment2='Percentile method used ' +
                                                           self.interpolation.name))
        # stats_dataset.get(stats_var).attrs.update(dict(units='metre', _FillValue='-999', grid_mapping="crs"))
        _log.info("stats is ready for %s (%d, %d) for %s %s", self.dataset_type.name, self.x_cell, self.y_cell,
                  self.band.name, self.statistic.name)
        return stats_dataset, stats_var, cell_list_obj, origattr 

    def coordinate_attr_update(self, stats_dataset):

        stats_dataset.get('x').attrs.update(dict(long_name="x coordinate of projection",
                                                 standard_name="projection_x_coordinate", axis="X"))
        stats_dataset.get('y').attrs.update(dict(long_name="y coordinate of projection",
                                                 standard_name="projection_y_coordinate", axis="Y"))

    def run(self):

        dc = datacube.Datacube(app="stats-app")
        prodname = product_lookup(self, self.dataset_type.value.lower())
        _log.info("Doing band [%s] statistic [%s] for product [%s] ", self.band.name, self.statistic.name, prodname)

        app_config_file = '../config/' + prodname + '.yaml'
        config = None
        if os.path.exists(app_config_file):
            config = config_loader(dc.index, app_config_file)

        filename = self.output().path
        dtype = np.float32
        stats_dataset = None
        if self.band.name in [t.name for t in Ls57Arg25Bands] or str(self.statistic.name) == "COUNT_OBSERVED":
            dtype = np.int16
        stats_dataset, stats_var, cell_list_obj, origattr = self.get_stats(dc, dtype, prodname)
        if stats_dataset:
        # update x and y coordinates axis/name attributes to silence gdal warning like "Longitude/X dimension"
            # self.coordinate_attr_update(stats_dataset)
            if config:
                # keep original attribute from data 
                stats_dataset.get(stats_var).attrs.update(dict(crs=origattr))
                stats_dataset.attrs = origattr
                # import pdb; pdb.set_trace()
                config = make_stats_config(dc.index, config)
                _,flname = filename.rsplit('/', 1)
                # write with extra metadata and index to the database
                stats_extra_metadata(config, stats_dataset, cell_list_obj, flname)
            else:
        # stats_dataset.to_netcdf(filename, mode='w', format='NETCDF4', engine='netcdf4',
        #       encoding={stats_var:{'dtype': dtype, 'scale_factor': 0.1, 'add_offset': 5, 'zlib': True,
        #  '_FillValue':-999}})
                # This can be used for internal testing without database ingestion
                self.coordinate_attr_update(stats_dataset)
                descriptor = write_global_attributes(self, cell_list_obj['geobox'])
                stats_dataset.attrs.update(dict(descriptor))
                # import pdb; pdb.set_trace()
         
                # stats_dataset.get(stats_var).attrs.update(dict(units='metre', _FillValue='-999', grid_mapping="crs"))
                stats_dataset.get(stats_var).attrs.update(dict(_FillValue='-999', grid_mapping="crs"))
                # crs_variable = {'crs': ('i8', 0)}
                crs_variable = {'crs':''}
                # create crs variable
                stats_dataset = stats_dataset.assign(**crs_variable) 
                crs_attr = write_crs_attributes(cell_list_obj['geobox'])
                stats_dataset.crs.attrs = crs_attr
                # global attributes
                # import pdb; pdb.set_trace()
                stats_dataset.to_netcdf(filename, mode='w', format='NETCDF4', engine='netcdf4',
                                encoding={stats_var: {'zlib': True}})

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    StatsTask().run()
