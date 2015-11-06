#    Copyright 2015 Geoscience Australia
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

from __future__ import absolute_import, print_function
from datetime import datetime

import numpy
from osgeo import gdal

from cubeaccess.core import StorageUnitDimensionProxy, StorageUnitStack
from cubeaccess.storage import GeoTifStorageUnit
from cubeaccess.indexing import make_index


def argpercentile(a, q, axis=0):
    # TODO: pass ndv?
    # TODO: keepdim?
    q = numpy.array(q, dtype=numpy.float64, copy=True)/100.0
    nans = numpy.isnan(a).sum(axis=axis)
    q = q.reshape(q.shape+(1,)*nans.ndim)
    index = (q*(a.shape[axis]-1-nans) + 0.5).astype(numpy.int32)
    indices = numpy.indices(a.shape[:axis] + a.shape[axis+1:])
    index = tuple(indices[:axis]) + (index,) + tuple(indices[axis:])
    return numpy.argsort(a, axis=axis)[index], nans == a.shape[axis]


def _time_from_filename(f):
    dtstr = f.split('/')[-1].split('_')[-1][:-4]
    # 2004-11-07T00-05-33.311000
    dt = datetime.strptime(dtstr, "%Y-%m-%dT%H-%M-%S.%f")
    return numpy.datetime64(dt, 's')


def _get_dataset(lat, lon, dataset='NBAR', sat='LS5_TM'):
    import glob
    lat_lon_str = '{:03d}_-{:03d}'.format(lat, abs(lon))
    pattern = '/g/data/rs0/tiles/EPSG4326_1deg_0.00025pixel/{sat}/{ll}/*/{sat}_{ds}_{ll}_*.tif'.format(sat=sat,
                                                                                                       ll=lat_lon_str,
                                                                                                       ds=dataset)
    files = glob.glob(pattern)
    template = GeoTifStorageUnit(files[0])
    input = [(GeoTifStorageUnit(f, template), _time_from_filename(f)) for f in files]
    input.sort(key=lambda p: p[1])
    stack = StorageUnitStack([StorageUnitDimensionProxy(su, ('t', t)) for su, t in input], 't')
    return stack


def write_files(name, data, qs, N, geotr, proj):
    driver = gdal.GetDriverByName("GTiff")
    nbands = len(data[0])
    for qidx, q in enumerate(qs):
        print('writing', name+'_'+str(q)+'.tif')
        raster = driver.Create(name+'_'+str(q)+'.tif', 4000, 4000, nbands, gdal.GDT_Int16,
                               options=["INTERLEAVE=BAND", "COMPRESS=LZW", "TILED=YES"])
        raster.SetProjection(proj)
        raster.SetGeoTransform(geotr)
        for band_num in range(nbands):
            band = raster.GetRasterBand(band_num+1)
            for idx, y in enumerate(range(0, 4000, N)):
                band.WriteArray(data[idx][band_num][qidx], 0, y)
            band.FlushCache()
        raster.FlushCache()
        del raster


def ndv_to_nan(a, ndv=-999):
    a = a.astype(numpy.float32)
    a[a == ndv] = numpy.nan
    return a


def do_work(stack, pq, qs, **kwargs):
    print('starting', datetime.now(), kwargs)
    pqa = pq.get('1', **kwargs).values
    red = ndv_to_nan(stack.get('3', **kwargs).values)
    nir = ndv_to_nan(stack.get('4', **kwargs).values)

    masked = 255 | 256 | 15360
    pqa_idx = ((pqa & masked) != masked)
    del pqa

    nir[pqa_idx] = numpy.nan
    red[pqa_idx] = numpy.nan

    ndvi = (nir-red)/(nir+red)
    index, mask = argpercentile(ndvi, qs, axis=0)

    # TODO: make slicing coordinates nicer
    tcoord = stack._get_coord('t')
    slice_ = make_index(tcoord, kwargs['t'])
    tcoord = tcoord[slice_]
    tcoord = tcoord[index]
    months = tcoord.astype('datetime64[M]').astype(int) % 12 + 1
    months[..., mask] = 0

    index = (index,) + tuple(numpy.indices(ndvi.shape[1:]))

    def index_data(data):
        data = ndv_to_nan(data[index])
        data[..., mask] = numpy.nan
        return data

    nir = index_data(nir)
    red = index_data(red)
    blue = index_data(stack.get('1', **kwargs).values)
    green = index_data(stack.get('2', **kwargs).values)
    ir1 = index_data(stack.get('5', **kwargs).values)
    ir2 = index_data(stack.get('6', **kwargs).values)

    print('done', datetime.now(), kwargs)
    return blue, green, red, nir, ir1, ir2, months
