# ----------------------------------------------------------------------------
# Copyright 2016 Nervana Systems Inc.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ----------------------------------------------------------------------------
import numpy as np

import ngraph as ng
from ngraph.util.utils import executor


def test_dot_with_numerics():
    """TODO."""
    ax1 = ng.NumericAxis(2)
    ax2 = ng.NumericAxis(2)
    axes = ng.Axes([ax1, ax2])

    x_np = np.array([[1, 2], [1, 2]], dtype='float32')
    x = ng.Constant(x_np, axes=axes)

    d = ng.dot(x, x, numpy_matching=True)
    d_val = executor(d)()

    assert np.array_equal(d_val, np.dot(x_np, x_np))


def test_expand_dims():
    """TODO."""
    ax1 = ng.NumericAxis(2)
    ax2 = ng.NumericAxis(2)
    axes = ng.Axes([ax1, ax2])

    x_np = np.array([[1, 2], [1, 2]], dtype='float32')
    x = ng.Constant(x_np, axes=axes)

    x1 = ng.ExpandDims(x, ax1, 0)
    x1_val = executor(x1)()
    for i in range(ax1.length):
        assert np.array_equal(x1_val[i], x_np)
