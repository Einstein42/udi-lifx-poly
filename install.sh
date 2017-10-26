#!/usr/bin/env bash
pip3 install -r requirements.txt -t .
rm -Rf *.dist-info
find . -name "__pycache__" -exec rm -rfv {} \;  # python 3
