.. _release_process:

Release Process
===============

#. Pick a release name for the next version.
    Releases are versioned using the ``major.minor.bugfix`` numbering system.

#. Update the release notes on the :ref:`whats_new` page.
    Check the git log for changes since the last release.

#. Check that Travis_ and readthedocs_ are passing (ie. have also finished running!) for the latest commit.

#. Tag the branch.
    Use the format of ``datacube-major.minor.bugfix``.

#. Merge changes leading up to the release into the `stable` branch

#. Draft a new release on the Datacube_ GitHub repository.
    Include the items added to the release notes in step 2.

#. Mark the version as released in Jira_.
    Move any open issues to the next version.

#. Install the datacube module on `raijin`.
    Follow the instructions on installing the Data Cube module on the `Datacube Environment`_ repository.

#. Notify the community of the release using the Datacube Central mailing list.
    Ask Simon Oliver for the MailChimp details.

.. _Travis: https://travis-ci.org/data-cube/agdc-v2

.. _readthedocs: http://readthedocs.org/projects/agdc-v2/builds/

.. _Datacube: https://github.com/data-cube/agdc-v2/releases

.. _Jira: https://gaautobots.atlassian.net/projects/ACDD?selectedItem=com.atlassian.jira.jira-projects-plugin%3Arelease-page&status=unreleased

.. _Datacube Environment: https://github.com/GeoscienceAustralia/ga-datacube-env#data-cube-module
