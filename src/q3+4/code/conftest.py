# -*- coding: utf-8 -*-
"""pytest 配置：保证 tests 可以从 code/ 根目录做包导入。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
