
import numpy
from datacube.model import BoundingBox, GeoPolygon, GeoBox, CRS, GridSpec


def test_gridworkflow():
    """ Test GridWorkflow with padding option. """
    from mock import MagicMock
    import datetime

    # ----- fake a datacube -----
    # e.g. let there be a dataset that coincides with a grid cell

    fakecrs = MagicMock()

    grid = 100  # spatial frequency in crs units
    pixel = 10  # square pixel linear dimension in crs units
    gridcell = BoundingBox(left=grid, bottom=-grid, right=2*grid, top=-2*grid)
    # if cell(0,0) has lower left corner at grid origin,
    # and cell indices increase toward upper right,
    # then this will be cell(1,-2).
    gridspec = GridSpec(crs=fakecrs, tile_size=(grid, grid), resolution=(-pixel, pixel))  # e.g. product gridspec

    fakedataset = MagicMock()
    fakedataset.extent = GeoPolygon.from_boundingbox(gridcell, crs=fakecrs)
    fakedataset.center_time = t = datetime.datetime(2001, 2, 15)

    fakeindex = MagicMock()
    fakeindex.datasets.get_field_names.return_value = ['time']  # permit query on time
    fakeindex.datasets.search_eager.return_value = [fakedataset]

    # ------ test without padding ----

    from datacube.api.grid_workflow import GridWorkflow
    gw = GridWorkflow(fakeindex, gridspec)
    query = dict(product='fake_product_name', time=('2001-1-1 00:00:00', '2001-3-31 23:59:59'))

    # test backend : that it finds the expected cell/dataset
    assert list(gw.cell_observations(**query).keys()) == [(1, -2)]

    # test frontend
    assert len(gw.list_tiles(**query)) == 1

    # ------ introduce padding --------

    gw2 = gw
    assert len(gw2.list_tiles(padding=2, **query)) == 9

    # ------ add another dataset (to test grouping) -----

    # consider cell (2,-2)
    gridcell2 = BoundingBox(left=2*grid, bottom=-grid, right=3*grid, top=-2*grid)
    fakedataset2 = MagicMock()
    fakedataset2.extent = GeoPolygon.from_boundingbox(gridcell2, crs=fakecrs)
    fakedataset2.center_time = t
    fakeindex.datasets.search_eager.return_value.append(fakedataset2)

    # unpadded
    assert len(gw.list_tiles(**query)) == 2
    ti = numpy.datetime64(t, 'ns')
    assert set(gw.list_tiles(**query).keys()) == {(1, -2, ti), (2, -2, ti)}

    # padded
    assert len(gw2.list_tiles(padding=2, **query)) == 12  # not 18=2*9 because of grouping

    # -------- inspect particular returned tile objects --------

    # check the array shape

    tile = gw.list_tiles(**query)[1, -2, ti]  # unpadded example
    assert grid/pixel == 10
    assert tile.shape == (1, 10, 10)

    padded_tile = gw2.list_tiles(padding=2, **query)[1, -2, ti]  # padded example
    # assert grid/pixel + 2*gw2.grid_spec.padding == 14  # GREG: understand this
    assert padded_tile.shape == (1, 14, 14)

    # count the sources

    assert len(tile.sources.isel(time=0).item()) == 1
    assert len(padded_tile.sources.isel(time=0).item()) == 2

    # check the geocoding

    assert tile.geobox.alignment == padded_tile.geobox.alignment
    assert tile.geobox.affine * (0, 0) == padded_tile.geobox.affine * (2, 2)
    assert tile.geobox.affine * (10, 10) == padded_tile.geobox.affine * (10+2, 10+2)

    # ------- check loading --------
    # GridWorkflow accesses the product_data API
    # to ultimately convert geobox,sources,measurements to xarray,
    # so only thing to check here is the call interface.

    measurement = dict(nodata=0, dtype=numpy.int)
    fakedataset.type.lookup_measurements.return_value = {'dummy': measurement}
    fakedataset2.type = fakedataset.type

    from mock import patch
    with patch('datacube.api.core.Datacube.product_data') as loader:

        data = GridWorkflow.load(tile)
        data2 = GridWorkflow.load(padded_tile)
        # Note, could also test Datacube.load for consistency (but may require more patching)

    assert data is data2 is loader.return_value
    assert loader.call_count == 2

    # Note, use of positional arguments here is not robust, could spec mock etc.
    for (args, kwargs), loadable in zip(loader.call_args_list, [tile, padded_tile]):
        args = list(args)
        assert args[0] is loadable.sources
        assert args[1] is loadable.geobox
        assert list(args[2])[0] is measurement
