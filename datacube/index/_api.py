# coding=utf-8
"""
Access methods for indexing datasets & storage units.
"""
from __future__ import absolute_import

import logging
from pathlib import Path

import datacube.utils
from datacube.config import LocalConfig
from ._datasets import DatasetResource, DatasetTypeResource, MetadataTypeResource
from .postgres import PostgresDb

_LOG = logging.getLogger(__name__)

_DEFAULT_METADATA_TYPES_PATH = Path(__file__).parent.joinpath('default-metadata-types.yaml')


def connect(local_config=None, application_name=None, validate_connection=True):
    """
    Connect to the index. Default Postgres implementation.

    :param application_name: A short, alphanumeric name to identify this application.
    :param local_config: Config object to use.
    :type local_config: :py:class:`datacube.config.LocalConfig`, optional
    :param validate_connection: Validate database schema and schema version is correct
    :rtype: Index
    :raises datacube.index.postgres._api.EnvironmentError:
    """
    if local_config is None:
        local_config = LocalConfig.find()

    return Index(
        PostgresDb.from_config(local_config, application_name=application_name, validate_db=validate_connection)
    )


class Index(object):
    """
    :type datasets: datacube.index._datasets.DatasetResource
    :type products: datacube.index._datasets.DatasetTypeResource
    :type metadata_types: datacube.index._datasets.MetadataTypeResource
    """
    def __init__(self, db):
        """
        :type db: datacube.index.postgres._api.PostgresDb
        """
        self._db = db

        self.metadata_types = MetadataTypeResource(db)
        self.products = DatasetTypeResource(db, self.metadata_types)
        self.datasets = DatasetResource(db, self.products)

    def init_db(self, with_default_types=True, with_permissions=True):
        is_new = self._db.init(with_permissions=with_permissions)

        if is_new and with_default_types:
            _LOG.info('Adding default metadata types.')
            for _, doc in datacube.utils.read_documents(_DEFAULT_METADATA_TYPES_PATH):
                self.metadata_types.add(doc, allow_table_lock=True)

        return is_new

    def grant_role(self, role, *users):
        """
        Grant a role to users
        """
        self._db.grant_role(role, users)

    def create_user(self, user_name, password, role):
        """
        Create a new user.
        """
        self._db.create_user(user_name, password, role)

    def list_users(self):
        """
        :return: list of (role, user, description)
        :rtype: list[(str, str, str)]
        """
        return self._db.list_users()

    def __repr__(self):
        return "Index<db={!r}>".format(self._db)
