#!/usr/bin/env python3

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from application import PatchworkApplication

if __name__ == "__main__":
    app = PatchworkApplication()
    app.run(sys.argv)
