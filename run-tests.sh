#!/bin/sh
# Synthetic capture, queue durability, and local daemon tests.
set -e
for t in capture queue; do
  node "$(dirname "$0")/extension/test/$t.test.js"
done

python3 -m unittest discover -s tests
