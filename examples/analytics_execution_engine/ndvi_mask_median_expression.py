# ------------------------------------------------------------------------------
# Name:       ndvi_mask_median_expression.py
# Purpose:    ndvi mask median expression example for Analytics Engine & Execution Engine.
#             post-integration with NDExpr.
#             post-integration with Data Access API.
#
# Author:     Peter Wang
#
# Created:    20 November 2015
# Copyright:  2015 Commonwealth Scientific and Industrial Research Organisation
#             (CSIRO)
# License:    This software is open source under the Apache v2.0 License
#             as provided in the accompanying LICENSE file or available from
#             https://github.com/data-cube/agdc-v2/blob/master/LICENSE
#             By continuing, you acknowledge that you have read and you accept
#             and will abide by the terms of the License.
#
# ------------------------------------------------------------------------------

from __future__ import absolute_import
from __future__ import print_function

if __name__ == '__main__' and __package__ is None:
    from os import sys, path
    sys.path.append(path.dirname(path.dirname(path.dirname(path.abspath(__file__)))))

from pprint import pprint
from datetime import datetime
from datacube.analytics.analytics_engine import AnalyticsEngine
from datacube.execution.execution_engine import ExecutionEngine
from datacube.analytics.utils.analytics_utils import plot


def main():
    a = AnalyticsEngine()
    e = ExecutionEngine()

    # Lake Burley Griffin
    dimensions = {'longitude': {'range': (149.07, 149.18)},
                  'latitude':  {'range': (-35.32, -35.28)},
                  'time':      {'range': (datetime(1990, 1, 1), datetime(1990, 12, 31))}}

    b40 = a.create_array(('LANDSAT 5', 'NBAR'), ['band_40'], dimensions, 'b40')
    b30 = a.create_array(('LANDSAT 5', 'NBAR'), ['band_30'], dimensions, 'b30')
    PQ = a.create_array(('LANDSAT 5', 'PQ'), ['band_pixelquality'], dimensions, 'pq')

    ndvi = a.apply_expression([b40, b30], '((array1 - array2) / (array1 + array2))', 'ndvi')
    adjusted_ndvi = a.apply_expression(ndvi, '(ndvi*0.5)', 'adjusted_ndvi')
    mask = a.apply_expression([adjusted_ndvi, PQ], 'array1{array2}', 'mask')
    median_t = a.apply_expression(mask, 'median(array1, 0)', 'medianT')

    result = e.execute_plan(a.plan)

    plot(e.cache['medianT'])

if __name__ == '__main__':
    main()
