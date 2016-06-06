Data Access API
===============

For examples on how to use the API, see the Jupyter notebooks at:
http://nbviewer.jupyter.org/github/data-cube/agdc-v2/blob/develop/examples/notebooks/The%20Unified%20Datacube%20Notebook.ipynb


.. currentmodule:: datacube

.. _datacube-class:

Datacube Class
--------------

.. autoclass:: Datacube

.. autosummary::
   :toctree: generate/

   Datacube
   Datacube.__init__


Higher Level User Functions
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. autosummary::
   :toctree: generate/

   Datacube.list_products
   Datacube.list_measurements
   Datacube.load


Low-Level Internal Functions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. autosummary::
   :toctree: generate/

   Datacube.product_observations
   Datacube.product_sources
   Datacube.product_data

.. just gets a single variable

   Datacube.measurement_data
   Datacube.measurement_data_lazy


GridWorkflow Class
------------------

.. currentmodule:: datacube.api
.. autoclass:: GridWorkflow

.. autosummary::
   :toctree: generate/

   GridWorkflow
   GridWorkflow.__init__
   GridWorkflow.list_cells
   GridWorkflow.list_tiles
   GridWorkflow.load

   GridWorkflow.list_cells
   GridWorkflow.list_tiles
   GridWorkflow.load


API for Analytics and Execution Engine
--------------------------------------

.. currentmodule:: datacube.api
.. autoclass:: API

.. autosummary::
   :toctree: generate/

    API.__init__
    API.list_products
    API.list_variables
    API.get_descriptor
    API.get_data


User Configuration
------------------
.. currentmodule:: datacube.config
.. autosummary::
  :toctree: generate/

  LocalConfig
  DEFAULT_CONF_PATHS
