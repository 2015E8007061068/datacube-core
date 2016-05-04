# coding=utf-8
"""
Access methods for indexing datasets & storage units.
"""
from __future__ import absolute_import

import logging
from pathlib import Path

from datacube import ui
from datacube.config import LocalConfig
from ._datasets import DatasetResource, DatasetTypeResource, MetadataTypeResource
from ._storage import StorageUnitResource, StorageTypeResource
from .postgres import PostgresDb

_LOG = logging.getLogger(__name__)

_DEFAULT_METADATA_TYPES_PATH = Path(__file__).parent.joinpath('default-metadata-types.yaml')


def connect(local_config=LocalConfig.find(), application_name=None):
    """
    Connect to the index. Default Postgres implementation.

    :param application_name: A short, alphanumeric name to identify this application.
    :param local_config: Config object to use.
    :type local_config: :py:class:`datacube.config.LocalConfig`, optional
    :rtype: Index
    """
    return Index(
        PostgresDb.from_config(local_config, application_name=application_name),
        local_config
    )


class Index(object):
    def __init__(self, db, local_config):
        """
        :type db: datacube.index.postgres._api.PostgresDb
        """
        self._db = db

        self.metadata_types = MetadataTypeResource(db)
        dataset_types = DatasetTypeResource(db, self.metadata_types)
        self.datasets = DatasetResource(db, local_config, dataset_types, self.metadata_types)
        self.storage = StorageUnitResource(db, StorageTypeResource(db, local_config), dataset_types, self.datasets,
                                           self.metadata_types, local_config)

    def init_db(self, with_default_types=True, with_permissions=True):
        is_new = self._db.init(with_permissions=with_permissions)

        if is_new and with_default_types:
            _LOG.info('Adding default metadata types.')
            for _, doc in ui.read_documents(_DEFAULT_METADATA_TYPES_PATH):
                self.metadata_types.add(doc, allow_table_lock=True)

        return is_new

    def grant_role(self, role, *users):
        """
        Grant a role to users
        """
        self._db.grant_role(role, users)

    def create_user(self, user, key, role):
        """
        Create a new user.
        """
        self._db.create_user(user, key, role)

    def list_users(self):
        """
        :returns list of (role, user, description)
        :rtype: list[(str, str, str)]
        """
        return self._db.list_users()

    def __repr__(self):
        return "Index<db={!r}>".format(self._db)
