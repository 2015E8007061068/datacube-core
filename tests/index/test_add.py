# coding=utf-8

from __future__ import absolute_import

import datetime

from datacube.index._add import index_dataset




_nbar_uuid = 'f2f12372-8366-11e5-817e-1040f381a756'
_ortho_uuid = '5cf41d98-eda9-11e4-8a8e-1040f381a756'
_telemetry_uuid = '4ec8fe97-e8b9-11e4-87ff-1040f381a756'

# An NBAR with source datasets. Many fields have been removed to keep it semi-focused to our ingest test.
_EXAMPLE_NBAR = {
    'id': _nbar_uuid,
    'product_type': 'nbar_brdf',
    'checksum_path': 'package.sha1',
    'ga_label': 'LS8_OLITIRS_NBAR_P54_GALPGS01-002_112_079_20140126',
    'ga_level': 'P54',
    'size_bytes': 4550,
    'platform': {'code': 'LANDSAT_8'},
    'creation_dt': datetime.datetime(2014, 1, 26, 2, 5, 23, 126373),
    'instrument': {'name': 'OLI_TIRS'},
    'format': {'name': 'GeoTIFF'},
    'extent': {
        'center_dt': datetime.datetime(2014, 1, 26, 2, 5, 23, 126373),
        'coord': {
            'ul': {'lat': -26.37259, 'lon': 116.58914},
            'lr': {'lat': -28.48062, 'lon': 118.96145},
            'ur': {'lat': -26.36025, 'lon': 118.92432},
            'll': {'lat': -28.49412, 'lon': 116.58121}
        }
    },
    'lineage': {
        'machine': {},
        'source_datasets': {
            'ortho': {
                'product_level': 'L1T',
                'product_type': 'ortho',
                'id': _ortho_uuid,
                'usgs': {
                    'scene_id': 'LC81120792014026ASA00'
                },
                'extent': {
                    'center_dt': datetime.datetime(2014, 1, 26, 2, 5, 23, 126373),
                    'coord': {
                        'ul': {'lat': -26.37259, 'lon': 116.58914},
                        'lr': {'lat': -28.48062, 'lon': 118.96145},
                        'ur': {'lat': -26.36025, 'lon': 118.92432},
                        'll': {'lat': -28.49412, 'lon': 116.58121}
                    }
                },
                'size_bytes': 1854924494,
                'platform': {
                    'code': 'LANDSAT_8'},
                'creation_dt': datetime.datetime(2015, 4, 7, 0, 58, 8),
                'instrument': {'name': 'OLI_TIRS'},
                'checksum_path': 'package.sha1',
                'ga_label': 'LS8_OLITIRS_OTH_P51_GALPGS01-002_112_079_20140126',
                'grid_spatial': {
                    'projection': {
                        'map_projection': 'UTM',
                        'resampling_option': 'CUBIC_CONVOLUTION',
                        'zone': -50,
                        'geo_ref_points': {
                            'ul': {'y': 7082987.5, 'x': 459012.5},
                            'lr': {'y': 6847987.5, 'x': 692012.5},
                            'ur': {'y': 7082987.5, 'x': 692012.5},
                            'll': {'y': 6847987.5, 'x': 459012.5}
                        },
                        'orientation': 'NORTH_UP',
                        'datum': 'GDA94',
                        'ellipsoid': 'GRS80'
                    }
                },
                'acquisition': {
                    'groundstation': {
                        'code': 'ASA',
                        'eods_domain_code': '002',
                        'label': 'Alice Springs'
                    }
                },
                'format': {'name': 'GEOTIFF'},
                'lineage': {
                    'algorithm': {
                        'name': 'LPGS',
                        'parameters': {},
                        'version': '2.4.0'
                    },
                    'machine': {},
                    'source_datasets': {
                        'satellite_telemetry_data': {
                            'product_type': 'satellite_telemetry_data',
                            'checksum_path': 'package.sha1',
                            'id': _telemetry_uuid,
                            'ga_label': 'LS8_OLITIRS_STD-MD_P00_LC81160740742015089ASA00_'
                                        '116_074_20150330T022553Z20150330T022657',

                            'ga_level': 'P00',
                            'size_bytes': 637660782,
                            'platform': {
                                'code': 'LANDSAT_8'},
                            'creation_dt': datetime.datetime(2015, 4, 22, 6, 32, 4),
                            'instrument': {'name': 'OLI_TIRS'},
                            'format': {
                                'name': 'MD'},
                            'lineage': {
                                'source_datasets': {}
                            }
                        }
                    }
                }
            }
        }
    }
}


def test_index_dataset():

    class MockDb(object):

        def __init__(self):
            self.dataset = []
            self.dataset_source = set()

        def insert_dataset(self, dataset_doc, dataset_id, path, product_type):
            self.dataset.append((dataset_doc, dataset_id, path, product_type))

        def insert_dataset_source(self, classifier, dataset_id, source_dataset_id):
            self.dataset_source.add((classifier, dataset_id, source_dataset_id))

    mock_db = MockDb()
    index_dataset(mock_db, _EXAMPLE_NBAR)

    # Three datasets (ours and the two embedded source datasets)
    assert len(mock_db.dataset) == 3

    ids = {d[0]['id'] for d in mock_db.dataset}
    assert ids == {_nbar_uuid, _ortho_uuid, _telemetry_uuid}

    # Our three datasets should be linked together
    # Nbar -> Ortho -> Telemetry
    assert len(mock_db.dataset_source) == 2
    assert mock_db.dataset_source == {
        ('ortho', _nbar_uuid, _ortho_uuid),
        ('satellite_telemetry_data', _ortho_uuid, _telemetry_uuid)
    }
