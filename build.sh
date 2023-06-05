#!/bin/bash
set -e
python3 -m venv .venv
. .venv/bin/activate
pip install poetry
poetry build -n -f wheel
poetry publish
