# coding=utf-8
"""
User configuration.
"""
from __future__ import absolute_import

from io import StringIO
import logging
import os
try:
    import configparser
except ImportError:
    import ConfigParser as configparser
from configparser import SafeConfigParser, NoOptionError


# Config locations in order. Properties found in latter locations override former.
DEFAULT_CONF_PATHS = (
    '/etc/datacube.conf',
    os.environ.get('DATACUBE_CONFIG_PATH'),
    os.path.expanduser("~/.datacube.conf"),
    'datacube.conf'
)

# Default configuration options.
_DEFAULT_CONF = u"""
[datacube]
# Blank implies localhost
db_hostname:
db_database: datacube

[locations]
# Where to reach storage locations from the current machine.
#  -> Location names (here 'gdata') are arbitrary, but correspond to names used in the
#     storage mapping files.
#  -> We may eventually support remote protocols (http, S3, etc) to lazily fetch remote data.
gdata: file:///g/data
"""


class LocalConfig(object):
    """
    System configuration for the user.

    This is deliberately kept minimal: it's primarily for connection information and defaults for the
    current user.
    """

    def __init__(self, config):
        self._config = config

    @classmethod
    def find(cls, paths=DEFAULT_CONF_PATHS):
        """
        Find config from possible filesystem locations.
        :type paths: list[str]
        :rtype: LocalConfig
        """
        config = SafeConfigParser()
        config.readfp(StringIO(_DEFAULT_CONF))
        config.read([p for p in paths if p])
        return LocalConfig(config)

    def _prop(self, key, section='datacube'):
        return self._config.get(section, key)

    @property
    def db_hostname(self):
        return self._prop('db_hostname')

    @property
    def db_database(self):
        return self._prop('db_database')

    @property
    def location_mappings(self):
        """
        :rtype: dict[str, str]
        """
        return dict(self._config.items('locations'))

    @property
    def db_username(self):
        try:
            return self._prop('db_username')
        except NoOptionError:
            return None

    @property
    def db_port(self):
        try:
            return self._prop('db_port')
        except NoOptionError:
            return None


def init_logging(verbosity_level=0, log_queries=False):
    logging_level = logging.WARN - 10 * verbosity_level
    logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logging_level)
    logging.getLogger('datacube').setLevel(logging_level)
    if log_queries:
        logging.getLogger('sqlalchemy.engine').setLevel('INFO')
