# Copyright 2015-2016 Nervana Systems Inc.
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
'''
Test of the activation functions
'''
from math import tanh as true_tanh
import numpy as np
from ngraph.frontends.neon.activation import Identity, Rectlin, Softmax, Tanh, Logistic
from ngraph.util.utils import ExecutorFactory
import ngraph as ng
import pytest


def compare_tensors(func, inputs, expected_result, deriv=False, tol=0.):
    ex = ExecutorFactory()
    C = ng.Axis('C')
    N = ng.Axis('N', batch=True)
    C.length, N.length = inputs.shape
    x = ng.placeholder(axes=ng.Axes([C, N]))

    if deriv is False:
        costfunc = ex.executor(func.__call__(x), x)
        result = costfunc(inputs)
    else:
        costfunc = ex.derivative(func.__call__(x), x)

        result = costfunc(inputs)

        # hack to get derivatives
        result = result.ravel()
        result = result[0:result.size:(C.length * N.length + 1)]
        result = result.reshape(inputs.shape)

    np.testing.assert_allclose(result, expected_result, rtol=tol)


"""Identity
"""


def test_identity():
    inputs = np.array([0, 1, -2]).reshape((3, 1))
    outputs = np.array([0, 1, -2]).reshape((3, 1))
    compare_tensors(Identity(), inputs, outputs)


def test_identity_derivative():
    inputs = np.array([[0, 1, -2], [1, 5, 6]]).reshape((3, 2))
    outputs = np.ones(inputs.shape)
    compare_tensors(Identity(), inputs, outputs, deriv=True)

"""Rectified Linear unit
"""


def test_rectlin_positives():
    inputs = np.array([1, 3, 2]).reshape((3, 1))
    outputs = np.array([1, 3, 2]).reshape((3, 1))
    compare_tensors(Rectlin(), inputs, outputs)


def test_rectlin_negatives():
    inputs = np.array([[-1, -3], [-2, -4]])
    outputs = np.array([[0, 0], [0, 0]])
    compare_tensors(Rectlin(), inputs, outputs)


def test_rectlin_mixed():
    inputs = np.array([[4, 0], [-2, 9]])
    outputs = np.array([[4, 0], [0, 9]])
    compare_tensors(Rectlin(), inputs, outputs)


def test_rectlin_derivative_positives():
    inputs = np.array([1, 3, 2]).reshape((3, 1))
    outputs = np.array([1, 1, 1]).reshape((3, 1))
    compare_tensors(Rectlin(), inputs, outputs, deriv=True)


def test_rectlin_derivative_negatives():
    inputs = np.array([[-1, -3], [-2, -4]])
    outputs = np.array([[0, 0], [0, 0]])
    compare_tensors(Rectlin(), inputs, outputs, deriv=True)


@pytest.mark.xfail(strict=True)
def test_rectlin_derivative_mixed():
    """
    Marked as xfail because it does not match old neon behavior at x=0,
    even though the derivative is technically undefined
    """
    inputs = np.array([[4, 0], [-2, 9]])
    outputs = np.array([[1, 0], [0, 1]])
    compare_tensors(Rectlin(), inputs, outputs, deriv=True)


"""Leaky Rectified Linear unit
"""


def test_leaky_rectlin_positives():
    slope = 0.2
    ax = ng.name_scope("ax")
    ax.X = ng.Axis(length=3)
    ax.Y = ng.Axis(length=1)
    inputs = np.array([1, 3, 2]).reshape((3, 1))
    outputs = np.array([1, 3, 2]).reshape((3, 1))
    compare_tensors(Rectlin(slope=slope), inputs, outputs)


def test_leaky_rectlin_negatives():
    slope = 0.2
    inputs = np.array([[-1, -3], [-2, -4]])
    outputs = inputs * slope
    compare_tensors(Rectlin(slope=slope), inputs, outputs, tol=1e-7)


def test_leaky_rectlin_mixed():
    slope = 0.2
    inputs = np.array([[4, 0], [-2, 9]])
    outputs = np.array([[4, 0], [-2 * slope, 9]])
    compare_tensors(Rectlin(slope=slope), inputs, outputs, tol=1e-7)


def test_leaky_rectlin_derivative_positives():
    slope = 0.2
    inputs = np.array([1, 3, 2]).reshape((3, 1))
    outputs = np.array([1, 1, 1]).reshape((3, 1))
    compare_tensors(Rectlin(slope=slope), inputs, outputs, deriv=True)


@pytest.mark.xfail(strict=True)
def test_leaky_rectlin_derivative_negatives():
    """
    ngraph derivative for negative values is 0, not the slope
    """
    slope = 0.2
    inputs = np.array([[-1, -3], [-2, -4]])
    outputs = np.array([[0, 0], [0, 0]]) + slope
    compare_tensors(Rectlin(slope=slope), inputs, outputs, deriv=True, tol=1e-7)


@pytest.mark.xfail(strict=True)
def test_leaky_rectlin_derivative_mixed():
    slope = 0.2
    inputs = np.array([[4, 0], [-2, 9]])
    outputs = np.array([[1, 0], [slope, 1]])
    compare_tensors(Rectlin(slope=slope), inputs, outputs, deriv=True, tol=1e-7)


"""Softmax
"""


def test_softmax():
    inputs = np.array([0, 1, -2]).reshape((3, 1))
    outputs = (np.exp(inputs - 1) / np.sum(np.exp(inputs - 1))).reshape((3, 1))
    compare_tensors(Softmax(), inputs, outputs, tol=1e-5)


def test_softmax_derivative():
    inputs = np.array([0, 1, -2], dtype=np.float).reshape((3, 1))
    outputs = (np.exp(inputs - 1) / np.sum(np.exp(inputs - 1)))
    outputs = outputs * (1 - outputs)  # shortcut only
    compare_tensors(Softmax(), inputs, outputs, deriv=True, tol=1e-6)


@pytest.mark.xfail(strict=True)
def test_softmax_big_inputs():
    """
    This fails with memory error because the ex.derivative function
    attempts to compute the full derivative.

    Keeping this test since it was in original neon.
    """
    inputs = np.random.random((1000, 128))
    outputs = (np.exp(inputs - 1) / np.sum(np.exp(inputs - 1)))
    outputs = outputs * (1 - outputs)  # shortcut only
    compare_tensors(Softmax(), inputs, outputs, deriv=True, tol=1e-6)


"""Tanh
"""


def test_tanh():
    inputs = np.array([0, 1, -2]).reshape((3, 1))
    outputs = np.array(
        [true_tanh(0), true_tanh(1), true_tanh(-2)]).reshape((3, 1))
    compare_tensors(Tanh(), inputs, outputs, tol=1e-7)


def test_tanh_derivative():
    inputs = np.array([0, 1, -2], dtype=np.float).reshape((3, 1))

    # bprop is on the output
    outputs = np.array([1 - true_tanh(0) ** 2,
                        1 - true_tanh(1) ** 2,
                        1 - true_tanh(-2) ** 2]).reshape((3, 1))
    compare_tensors(Tanh(), inputs, outputs, deriv=True, tol=1e-6)


"""Logistic
"""


def test_logistic():
    inputs = np.array([0, 1, -2]).reshape((3, 1))
    outputs = 1.0 / (1.0 + np.exp(-inputs)).reshape((3, 1))
    compare_tensors(Logistic(), inputs, outputs, tol=1e-7)


def test_logistic_derivative():
    # bprop is on the output
    inputs = np.array([0, 1, -2], dtype=np.float).reshape((3, 1))
    f = 1.0 / (1.0 + np.exp(-inputs))
    outputs = f * (1.0 - f)
    compare_tensors(Logistic(shortcut=False),
                    inputs, outputs, deriv=True, tol=1e-7)
