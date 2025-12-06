#!/bin/bash

# This script runs the Gentoo Installer application.
# It sets the PYTHONPATH to include the 'src' directory
# so that Python can find the application modules.

export PYTHONPATH=$(pwd)/src
python3 -u src/main.py
