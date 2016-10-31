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
from ngraph.util.utils import RandomTensorGenerator
from neon.backends.layer_cpu import ConvLayer
from neon.backends import gen_backend

rng = RandomTensorGenerator(0, np.float32)


def np_convolution(inputs, filters, result):
    """
    numpy implementation of convolution with stride 1 and no padding
    """
    C, D, H, W, N = inputs.shape
    _, T, R, S, K = filters.shape
    _, M, P, Q, N = result.shape

    weights = filters.reshape(C * T * R * S, K).T
    for m, p, q in np.ndindex(M, P, Q):
        data = inputs[:, m:m + T, p:p + R, q:q + S].reshape((C * T * R * S, N))
        result[:, m, p, q] = np.dot(weights, data)


def test_convolution_fprop():
    """
    test convolution forward path
    """
    N = 128
    D = 4
    H = W = 32
    T = R = S = 2
    dims = ConvLayer(gen_backend('cpu'), np.float32, N=N, C=3, K=8,
                     D=D, H=H, W=W, T=T, R=R, S=S)
    Nx = ng.Axis(N, batch=True)

    Cx = ng.Axis(dims.C)
    Dx = ng.Axis(D)
    Hx = ng.Axis(H)
    Wx = ng.Axis(W)

    Tx = ng.Axis(T)
    Rx = ng.Axis(R)
    Sx = ng.Axis(S)
    Kx = ng.Axis(dims.K)

    inputs = ng.placeholder(axes=ng.Axes([Cx, Dx, Hx, Wx, Nx]))
    filters = ng.placeholder(axes=ng.Axes([Cx, Tx, Rx, Sx, Kx]))

    # randomly initialize
    input_value = rng.uniform(-1, 1, inputs.axes)
    filter_value = rng.uniform(-1, 1, filters.axes)

    assert input_value.shape == tuple([ax.length for ax in [Cx, Dx, Hx, Wx, Nx]])
    assert filter_value.shape == tuple([ax.length for ax in [Cx, Tx, Rx, Sx, Kx]])

    # compute convolution with graph
    output = ng.convolution(dims, inputs, filters)
    result_og = executor(output, inputs, filters)(input_value, filter_value)

    result_value = np.zeros((dims.K, dims.M, dims.P, dims.Q, N), dtype=np.float32)

    np_convolution(input_value, filter_value, result_value)
    np.testing.assert_allclose(result_og, result_value)
