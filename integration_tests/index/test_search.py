# coding=utf-8
"""
Module
"""
from __future__ import absolute_import

import copy
import csv
import datetime
import io
import uuid

import pytest
from click.testing import CliRunner
from pathlib import Path

import datacube.scripts.run_ingest
import datacube.scripts.search_tool

_EXAMPLE_LS7_NBAR_DATASET_FILE = Path(__file__).parent.joinpath('ls7-nbar-example.yaml')


@pytest.fixture
def indexed_ls7_nbar(global_integration_cli_args, index):
    """
    :type index: datacube.index._api.Index
    """
    opts = list(global_integration_cli_args)
    opts.extend(
        [
            '-vv',
            'ingest',
            str(_EXAMPLE_LS7_NBAR_DATASET_FILE)
        ]
    )
    result = CliRunner().invoke(
        datacube.scripts.run_ingest.cli,
        opts,
        catch_exceptions=False
    )
    print(result.output)
    assert not result.exception
    assert result.exit_code == 0

    return index.datasets.get('79a4f76c-e6d7-11e5-8fa1-a0000100fe80')


@pytest.fixture
def pseudo_telemetry_type(index, db):
    index.datasets.types.add({
        'name': 'ls8_telemetry',
        'match': {
            'metadata': {
                'product_type': 'pseudo_telemetry_data',
                'platform': {
                    'code': 'LANDSAT_8'
                },
                'format': {
                    'name': 'PSEUDOMD'
                }
            }
        },
        'metadata_type': 'eo'
    })
    return index.datasets.types.get_by_name('ls8_telemetry')


@pytest.fixture
def pseudo_telemetry_dataset(index, db, default_metadata_type, pseudo_telemetry_type):
    id_ = str(uuid.uuid4())
    was_inserted = db.insert_dataset(
        {
            'id': id_,
            'product_type': 'pseudo_telemetry_data',
            'checksum_path': 'package.sha1',
            'ga_label': 'LS8_OLITIRS_STD-MD_P00_LC81160740742015089ASA00_'
                        '116_074_20150330T022553Z20150330T022657',

            'ga_level': 'P00',
            'size_bytes': 637660782,
            'platform': {
                'code': 'LANDSAT_8'
            },
            # We're unlikely to have extent info for a raw dataset, we'll use it for search tests.
            'extent': {
                'from_dt': datetime.datetime(2014, 7, 26, 23, 48, 0, 343853),
                'to_dt': datetime.datetime(2014, 7, 26, 23, 52, 0, 343853),
                'coord': {
                    'll': {'lat': -31.33333, 'lon': 149.78434},
                    'lr': {'lat': -31.37116, 'lon': 152.20094},
                    'ul': {'lat': -29.23394, 'lon': 149.85216},
                    'ur': {'lat': -29.26873, 'lon': 152.21782}
                }
            },
            'creation_dt': datetime.datetime(2015, 4, 22, 6, 32, 4),
            'instrument': {'name': 'OLI_TIRS'},
            'format': {
                'name': 'PSEUDOMD'
            },
            'lineage': {
                'source_datasets': {}
            }
        },
        id_
    )
    assert was_inserted
    d = index.datasets.get(id_)

    # The dataset should have been matched to the telemetry type.
    assert d.type_.id == pseudo_telemetry_type.id

    return d


def test_search_dataset_equals(index, pseudo_telemetry_dataset):
    """
    :type index: datacube.index._api.Index
    :type pseudo_telemetry_dataset: datacube.model.Dataset
    """
    field = index.datasets.get_field

    datasets = index.datasets.search_eager(
        field('platform') == 'LANDSAT_8',
    )
    assert len(datasets) == 1
    assert datasets[0].id == pseudo_telemetry_dataset.id

    datasets = index.datasets.search_eager(
        field('platform') == 'LANDSAT_8',
        field('instrument') == 'OLI_TIRS',
    )
    assert len(datasets) == 1
    assert datasets[0].id == pseudo_telemetry_dataset.id

    # Wrong sensor name
    datasets = index.datasets.search_eager(
        field('platform') == 'LANDSAT-8',
        field('instrument') == 'TM',
    )
    assert len(datasets) == 0


def test_search_dataset_by_metadata(index, pseudo_telemetry_dataset):
    """
    :type index: datacube.index._api.Index
    :type pseudo_telemetry_dataset: datacube.model.Dataset
    """
    datasets = index.datasets.search_by_metadata(
        {"platform": {"code": "LANDSAT_8"}, "instrument": {"name": "OLI_TIRS"}}
    )
    datasets = list(datasets)
    assert len(datasets) == 1
    assert datasets[0].id == pseudo_telemetry_dataset.id

    datasets = index.datasets.search_by_metadata(
        {"platform": {"code": "LANDSAT_5"}, "instrument": {"name": "TM"}}
    )
    datasets = list(datasets)
    assert len(datasets) == 0


def test_search_dataset_ranges(index, pseudo_telemetry_dataset):
    """
    :type index: datacube.index._api.Index
    :type pseudo_telemetry_dataset: datacube.model.Dataset
    """

    field = index.datasets.get_field

    # In the lat bounds.
    datasets = index.datasets.search_eager(
        field('lat').between(-30.5, -29.5),
        field('time').between(
            datetime.datetime(2014, 7, 26, 23, 0, 0),
            datetime.datetime(2014, 7, 26, 23, 59, 0)
        )
    )
    assert len(datasets) == 1
    assert datasets[0].id == pseudo_telemetry_dataset.id

    # Out of the lat bounds.
    datasets = index.datasets.search_eager(
        field('lat').between(28, 32),
        field('time').between(
            datetime.datetime(2014, 7, 26, 23, 48, 0),
            datetime.datetime(2014, 7, 26, 23, 50, 0)
        )
    )
    assert len(datasets) == 0

    # Out of the time bounds
    datasets = index.datasets.search_eager(
        field('lat').between(-30.5, -29.5),
        field('time').between(
            datetime.datetime(2014, 7, 26, 21, 48, 0),
            datetime.datetime(2014, 7, 26, 21, 50, 0)
        )
    )
    assert len(datasets) == 0

    # A dataset that overlaps but is not fully contained by the search bounds.
    # TODO: Do we want overlap as the default behaviour?
    # Should we distinguish between 'contains' and 'overlaps'?
    datasets = index.datasets.search_eager(
        field('lat').between(-40, -30)
    )
    assert len(datasets) == 1
    assert datasets[0].id == pseudo_telemetry_dataset.id


def test_search_globally(index, pseudo_telemetry_dataset):
    """
    :type index: datacube.index._api.Index
    :type pseudo_telemetry_dataset: datacube.model.Dataset
    """
    # Insert dataset. It should be matched to the telemetry collection.
    # No expressions means get all.
    results = list(index.datasets.search())
    assert len(results) == 1


def test_searches_only_type(index, pseudo_telemetry_type, pseudo_telemetry_dataset):
    """
    :type index: datacube.index._api.Index
    :type pseudo_telemetry_type: datacube.model.DatasetType
    :type pseudo_telemetry_dataset: datacube.model.Dataset
    """
    # The dataset should have been matched to the telemetry type.
    assert pseudo_telemetry_dataset.type_.id == pseudo_telemetry_type.id

    metadata_type = pseudo_telemetry_type.metadata_type
    assert index.datasets.search_eager()
    # No results on the default collection.
    f = metadata_type.dataset_fields.get
    datasets = index.datasets.search_eager(
        type=pseudo_telemetry_type.name,
        platform='LANDSAT_8',
        instrument='OLI_TIRS'
    )
    assert len(datasets) == 0

    # One result in the telemetry collection.
    datasets = index.datasets.search_eager(
        type=pseudo_telemetry_type.name,
        platform='LANDSAT_8',
        instrument='OLI_TIRS',
    )
    assert len(datasets) == 1
    assert datasets[0].id == pseudo_telemetry_dataset.id

    # One result when no collection specified.
    datasets = index.datasets.search_eager(
        platform='LANDSAT_8',
        instrument='OLI_TIRS',
    )
    assert len(datasets) == 1
    assert datasets[0].id == pseudo_telemetry_dataset.id


def test_cannot_search_multiple_metadata_types(index, default_metadata_type, ancillary_collection):
    f = default_metadata_type.metadata_type.dataset_fields.get
    ancillary_f = ancillary_collection.metadata_type.dataset_fields.get

    # An error if you mix metadata types (although we may support this in the future):
    with pytest.raises(ValueError):
        index.datasets.search_eager(
            f('platform') == 'LANDSAT_8',
            ancillary_f('name') == 'LO8BPF2014',
        )


def test_fetch_all_of_md_type(index, pseudo_telemetry_dataset):
    """
    :type index: datacube.index._api.Index
    :type pseudo_telemetry_dataset: datacube.model.Dataset
    """
    # Get every dataset in the collection
    results = index.datasets.search_eager(
        metadata_type='eo'
    )
    assert len(results) == 1
    assert results[0] == pseudo_telemetry_dataset.id

    results = index.datasets.search_eager(
        metadata_type='storage_unit'
    )
    assert len(results) == 0


# Storage searching:

def test_search_storage_star(index, db, indexed_ls5_nbar_storage_type, pseudo_telemetry_dataset):
    """
    :type db: datacube.index.postgres._api.PostgresDb
    :type index: datacube.index._api.Index
    :type indexed_ls5_nbar_storage_type: datacube.model.StorageType
    """
    assert len(index.storage.search_eager()) == 0

    db.add_storage_unit(
        path='/tmp/something.tif',
        dataset_ids=[pseudo_telemetry_dataset],
        descriptor={'test': 'test'},
        storage_type_id=indexed_ls5_nbar_storage_type.id,
        size_bytes=1234
    )

    results = index.storage.search_eager()
    assert len(results) == 1
    assert results[0].dataset_ids == [uuid.UUID(pseudo_telemetry_dataset)]


def test_search_storage_by_dataset(index, db, default_metadata_type, indexed_ls5_nbar_storage_type,
                                   pseudo_telemetry_dataset):
    """
    :type db: datacube.index.postgres._api.PostgresDb
    :type index: datacube.index._api.Index
    :type indexed_ls5_nbar_storage_type: datacube.model.StorageType
    :type default_metadata_type: datacube.model.Collection
    """
    metadata_type = default_metadata_type.metadata_type

    unit_id = db.add_storage_unit(
        '/tmp/something.tif',
        [pseudo_telemetry_dataset.id],
        {'test': 'test'},
        indexed_ls5_nbar_storage_type.id,
        size_bytes=1234
    )
    dfield = metadata_type.dataset_fields.get

    # Search by the linked dataset properties.
    storages = index.storage.search_eager(
        dfield('platform') == 'LANDSAT_8',
        dfield('instrument') == 'OLI_TIRS'
    )
    assert len(storages) == 1
    assert storages[0].id == unit_id

    # When fields don't match the dataset it shouldn't be returned.
    storages = index.storage.search_eager(
        dfield('platform') == 'LANDSAT_7'
    )
    assert len(storages) == 0


def test_search_storage_multi_dataset(index, db, default_metadata_type, indexed_ls5_nbar_storage_type,
                                      pseudo_telemetry_dataset):
    """
    When a storage unit is linked to multiple datasets, it should only be returned once.

    :type db: datacube.index.postgres._api.PostgresDb
    :type index: datacube.index._api.Index
    :type indexed_ls5_nbar_storage_type: datacube.model.StorageType
    :type pseudo_telemetry_dataset: datacube.model.Dataset
    """
    metadata_type = default_metadata_type.metadata_type
    # Add a second
    id2 = str(uuid.uuid4())
    doc2 = copy.deepcopy(pseudo_telemetry_dataset.metadata_doc)
    doc2['id'] = id2
    was_inserted = db.insert_dataset(doc2, id2)
    assert was_inserted

    unit_id = db.add_storage_unit(
        '/tmp/something.tif',
        [pseudo_telemetry_dataset.id, id2],
        {'test': 'test'},
        indexed_ls5_nbar_storage_type.id,
        size_bytes=1234
    )
    dfield = metadata_type.dataset_fields.get
    # Search by the linked dataset properties.
    storages = index.storage.search_eager(
        dfield('platform') == 'LANDSAT_8',
        dfield('instrument') == 'OLI_TIRS'
    )

    assert len(storages) == 1
    assert storages[0].id == unit_id
    assert set(storages[0].dataset_ids) == {uuid.UUID(pseudo_telemetry_dataset), uuid.UUID(id2)}


def test_search_cli_basic(global_integration_cli_args, default_metadata_type, pseudo_telemetry_dataset):
    """
    Search datasets using the cli.
    :type global_integration_cli_args: tuple[str]
    :type default_metadata_type: datacube.model.Collection
    :type pseudo_telemetry_dataset: datacube.model.Dataset
    """
    opts = list(global_integration_cli_args)
    opts.extend(
        [
            # No search arguments: return all datasets.
            'datasets'
        ]
    )

    runner = CliRunner()
    result = runner.invoke(
        datacube.scripts.search_tool.cli,
        opts
    )
    assert str(pseudo_telemetry_dataset.id) in result.output
    assert str(default_metadata_type.name) in result.output

    assert result.exit_code == 0


def test_search_storage_by_both_fields(global_integration_cli_args, db, indexed_ls5_nbar_storage_type,
                                       pseudo_telemetry_dataset):
    """
    Search storage using both storage and dataset fields.
    :type db: datacube.index.postgres._api.PostgresDb
    :type global_integration_cli_args: tuple[str]
    :type indexed_ls5_nbar_storage_type: datacube.model.StorageType
    :type pseudo_telemetry_dataset: datacube.model.Dataset
    """

    unit_id = db.add_storage_unit(
        '/tmp/something.tif',
        [pseudo_telemetry_dataset.id],
        descriptor={
            'extents': {
                'geospatial_lat_min': 120,
                'geospatial_lat_max': 140
            }
        },
        storage_type_id=indexed_ls5_nbar_storage_type.id,
        size_bytes=1234
    )

    rows = _cli_csv_search(['units', '100<lat<150'], global_integration_cli_args)
    assert len(rows) == 1
    assert rows[0]['id'] == str(unit_id)

    # Don't return on a mismatch
    rows = _cli_csv_search(['units', '150<lat<160'], global_integration_cli_args)
    assert len(rows) == 0

    # Search by both dataset and storage fields.
    rows = _cli_csv_search(['units', 'platform=LANDSAT_8', '100<lat<150'], global_integration_cli_args)
    assert len(rows) == 1
    assert rows[0]['id'] == str(unit_id)


def _cli_csv_search(args, global_integration_cli_args):
    global_opts = list(global_integration_cli_args)
    global_opts.extend(['-f', 'csv'])
    result = _cli_search(args, global_opts)
    assert result.exit_code == 0
    return list(csv.DictReader(io.StringIO(result.output)))


def _cli_search(args, global_integration_cli_args):
    opts = list(global_integration_cli_args)
    opts.extend(args)
    runner = CliRunner()
    result = runner.invoke(
        datacube.scripts.search_tool.cli,
        opts,
        catch_exceptions=False
    )
    return result
