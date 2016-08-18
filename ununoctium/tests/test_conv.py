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
# import pytest

import geon as be
from geon.op_graph import arrayaxes
import geon.frontends.base.axis as ax
from geon.util.utils import executor


@be.with_bound_environment
def test_constant_tensor_convolution_fprop():
    """
    A simple test running a convolution filter over an input where both filter
    and input are ones and both are the same size.
    """

    arrayaxes.set_batch_axes([ax.N])

    ax.N.length = 1
    ax.C.length = 2
    ax.H.length = 2
    ax.W.length = 2
    ax.Cout = arrayaxes.Axis(2)

    input_axes = arrayaxes.Axes([ax.C, ax.H, ax.W, ax.N])
    filter_axes = arrayaxes.Axes([ax.C, ax.H, ax.W, ax.Cout])

    input = be.NumPyTensor(
        np.ones(input_axes.lengths, dtype='float32'), axes=input_axes,
    )
    filter = be.NumPyTensor(
        np.ones(filter_axes.lengths, dtype='float32'), axes=filter_axes,
    )

    output = be.convolution(input, filter)

    result = executor(output)()
    assert np.allclose(result, [[[8.0]]])
