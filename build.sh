#!/bin/bash
set -e
python3 -m venv .venv
. .venv/bin/activate
pip install build twine
rm -rf dist/*
python3 -m build --wheel
# twine upload --repository-url https://test.pypi.org/legacy/ dist/*
twine upload dist/*
