#!/usr/bin/env bash
# Convenience script for running Travis-like checks.

set -eu
set -x

pep8 tests integration_tests --max-line-length 120

pylint -j 2 --reports no datacube examples/*.py

# Run tests, taking coverage.
# Users can specify extra folders as arguments.
py.test -r s --cov datacube --durations=5 datacube examples tests $@

