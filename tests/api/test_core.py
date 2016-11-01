from datacube.api.query import GroupBy

from datacube import Datacube
import datetime


def test_grouping_datasets():
    def group_func(d):
        return d['time']
    dimension = 'time'
    units = None
    datasets = [
        {'time': datetime.datetime(2016, 1, 1), 'value': 'foo'},
        {'time': datetime.datetime(2016, 1, 1), 'value': 'flim'},
        {'time': datetime.datetime(2016, 2, 1), 'value': 'bar'}
    ]

    group_by = GroupBy(dimension, group_func, units)
    grouped = Datacube.product_sources(datasets, group_by)

    assert str(grouped.time.dtype) == 'datetime64[ns]'
    assert grouped.loc['2016-01-01':'2016-01-15']
    assert len(grouped.time) == 2
    assert grouped.time[0] < grouped.time[1]

    # Ensure that grouping order doesn't affect output order.
    group_by = GroupBy(dimension, group_func, units, group_func, reversed=True)
    grouped = Datacube.product_sources(datasets, group_by)

    assert str(grouped.time.dtype) == 'datetime64[ns]'
    assert len(grouped.time) == 2
    assert grouped.time[0] < grouped.time[1]
