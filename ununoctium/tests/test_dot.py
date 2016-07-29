from builtins import range
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
import random
import geon.backends.graph.funs as be
import geon.backends.graph.axis as ax
from geon.util.utils import in_bound_environment
from geon.util.utils import raise_all_numpy_errors
from geon.util.utils import transform_numeric_derivative
from geon.util.utils import transform_derivative

'''
Test graphiti's implementation of the dot product.

'''


def evaluate(result):
    return be.NumPyTransformer(results=[result]).evaluate()[result]


def get_random_shape(max_num_axes, max_axis_length):
    assert max_num_axes >= 2
    num_axes = 0

    while num_axes < 2:
        num_axes = random.randint(0, max_num_axes)
        shape = ()
        for i in range(num_axes):
            shape += (random.randint(0, max_axis_length),)
    return shape


def get_random_np_array(
        max_num_axes,
        max_axis_length,
        mean=0,
        sigma=1,
        dtype=np.float32):
    arr = sigma * \
        np.random.randn(
            *get_random_shape(max_num_axes, max_axis_length)) + mean
    arr.dtype = dtype
    return arr


@in_bound_environment
def graphiti_l2_norm(np_array):
    axes = ()
    for i, l in enumerate(np_array.shape):
        axes += (be.AxisVar(name='axis%s' % i, length=l),)
    np_tensor = be.NumPyTensor(np_array, axes=axes)
    var = be.Variable(axes=axes, initial_value=np_tensor)
    return evaluate(be.sqrt(be.dot(var, var)))


@raise_all_numpy_errors
def test_l2_norm():
    tests_ = [
        [],
        [1],
        [1, 4, 5, 6],
        [[1, 3, 5], [4, 2, 5]]
    ]
    tests = [np.array(_, dtype=np.float32) for _ in tests_]
    for i, test in enumerate(tests):
        assert np.array_equal(np.linalg.norm(test), graphiti_l2_norm(test))


@raise_all_numpy_errors
@in_bound_environment
def test_tensor_dot_tensor():
    delta = 1e-3
    rtol = atol = 1e-2

    tests = [
        {
            'tensor1': [[1, 2], [4, 5], [3, 4]],
            'tensor1_axes': (ax.C, ax.D),
            'tensor2': [2, 5],
            'tensor2_axes': (ax.D,),
            'expected_output': [12, 33, 26],
            'axes_lengths': {ax.C: 3, ax.D: 2}
        },
        {
            'tensor1': [[1, 4, 3], [2, 5, 4]],
            'tensor1_axes': (ax.D, ax.C),
            'tensor2': [2, 5],
            'tensor2_axes': (ax.D,),
            'expected_output': [12, 33, 26],
            'axes_lengths': {ax.C: 3, ax.D: 2}
        },
        {
            # Resembles hidden state to hidden state transformation
            'tensor1': [[1, 4], [2, 5]],
            'tensor1_axes': (ax.H, ax.H),
            'tensor2': [2, 5],
            'tensor2_axes': (ax.H,),
            'expected_output': [12, 33],
            'axes_lengths': {ax.H: 2}
        },
        {
            'tensor1': [[[1, 4], [2, 5]], [[7, 12], [13, 2]]],
            'tensor1_axes': (ax.N, ax.D, ax.C),
            'tensor2': [[[3, 6], [7, 2]], [[9, 8], [10, 4]]],
            'tensor2_axes': (ax.H, ax.D, ax.C),
            'expected_output': [[51, 81], [188, 297]],
            'axes_lengths': {ax.N: 2, ax.D: 2, ax.C: 2, ax.H: 2}
        },
        {
            'tensor1': [1, 2],
            'tensor1_axes': (ax.C,),
            'tensor2': [7, 11, 13],
            'tensor2_axes': (ax.D,),
            'expected_output': [[7, 11, 13], [14, 22, 26]],
            'axes_lengths': {ax.C: 2, ax.D: 3}
        },
        {
            'tensor1': [[1, 4], [6, 2]],
            'tensor1_axes': (ax.C, ax.D),
            'expected_output': 57,
            'axes_lengths': {ax.C: 2, ax.D: 2}
        }
    ]

    for test in tests:
        for axis, length in list(test['axes_lengths'].items()):
            axis.length = length

        tensor1_axes = test['tensor1_axes']
        tensor1 = be.placeholder(axes=tensor1_axes)
        tensor1.value = np.array(
            test['tensor1'], dtype=np.float32
        )

        if 'tensor2' in test:
            tensor2_axes = test['tensor2_axes']
            tensor2 = be.placeholder(axes=tensor2_axes)
            tensor2.value = np.array(
                test['tensor2'], dtype=np.float32
            )
        else:
            tensor2 = tensor1
        expected_output = np.array(test['expected_output'], dtype=np.float32)

        dot = be.dot(tensor1, tensor2)
        evaluated = evaluate(dot)
        assert np.array_equal(evaluated, expected_output),\
            'Expected: %s, found: %s' % (expected_output, evaluated)

        numeric_deriv_1 = transform_numeric_derivative(dot, tensor1, delta)
        sym_deriv_1 = transform_derivative(dot, tensor1)
        assert np.allclose(numeric_deriv_1, sym_deriv_1, rtol=rtol, atol=atol)

        numeric_deriv_2 = transform_numeric_derivative(dot, tensor2, delta)
        sym_deriv_2 = transform_derivative(dot, tensor2)
        assert np.allclose(numeric_deriv_2, sym_deriv_2, rtol=rtol, atol=atol)
