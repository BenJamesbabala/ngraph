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

from tf_importer.tf_importer.ops_base import OpsBase
from tf_importer.tf_importer.utils import to_int, shape_to_axes
import ngraph as ng
import numpy as np


class OpsGradient(OpsBase):
    """
    Mix-in class for gradient related ops
    """

    def ReluGrad(self, tf_node, inputs):
        """
        [TensorFlow Docs]
        C++ implementation: https://goo.gl/l07FXx

        Computes ReluGrad backprops.

        NOTE: When the activation is exactly zero, we do not propagate the
        associated gradient value. This allows the output of the Relu to be used,
        as well as its input.

        Args:
            gradients: gradients backpropagated to the Relu op.
            features: either the inputs that were passed to the Relu or, or its
                      outputs (using either one yields the same result here).


        Returns:
            backprops: gradients to backpropagate to the Relu inputs.
        """
        # get inputs
        gradients, features = inputs

        # gradient of relu op
        relu_grad = ng.greater(features, 0.)
        relu_grad = ng.cast_axes(relu_grad, gradients.axes)

        return gradients * relu_grad

    def ApplyGradientDescent(self, tf_node, inputs):
        """
        Apply gradient descent
        :param tf_node:
        :param inputs:
        :return:

        CPU: https://goo.gl/oMq2HA
        GPU: https://goo.gl/US3t0r
        """
        var, lr, grad = inputs
        return ng.assign(var, var - lr * grad)

    def BroadcastGradientArgs(self, tf_node, inputs):
        """
        Given shapes of two tensors, computes the reduction indices for the
        gradient computation

        Naive copy of the C++ implementation:
        - BCastGradArgsOp https://goo.gl/5vx4QN
        - BCast::BCast https://goo.gl/gzOiA2

        TODO: Untested in real models, dangerous!
        """
        # get inputs
        sx, sy = list(to_int(inputs[0].const)), list(to_int(inputs[1].const))

        # fast path for common case of identical shapes for sx and sy
        if np.array_equal(sx, sy):
            return None, None

        # reverse the shape of x and y for convenience.
        x = list(reversed(sx))
        y = list(reversed(sy))

        # 1-extend and align x and y so that they are the same size
        if len(x) > len(y):
            y += [1] * (len(x) - len(y))
        else:
            x += [1] * (len(y) - len(x))

        # going through each dimension starting from the inner-most
        # dimension, compares dimension of x and y. They are compatible if
        # they are equal or either is 1
        grad_x_reduce_idx_ = []
        grad_y_reduce_idx_ = []
        n = len(x)
        for i in range(n):
            if x[i] == y[i]:
                continue
            elif x[i] == 1:
                grad_x_reduce_idx_.append(n - 1 - i)
            elif y[i] == 1:
                grad_y_reduce_idx_.append(n - 1 - i)
            else:
                raise ValueError("Shape %s and %s not numpy-compatible" %
                                 (sx, sy))

        # reverse all vectors since x and y were reversed at very beginning
        grad_x_reduce_idx_ = list(reversed(grad_x_reduce_idx_))
        grad_y_reduce_idx_ = list(reversed(grad_y_reduce_idx_))

        # make ng constant array
        if grad_x_reduce_idx_:
            x_array = np.array(grad_x_reduce_idx_)
            ng_x_array = ng.Constant(x_array, axes=shape_to_axes(x_array.shape),
                                     name=tf_node.name)
        else:
            ng_x_array = None

        if grad_y_reduce_idx_:
            y_array = np.array(grad_y_reduce_idx_)
            ng_y_array = ng.Constant(y_array, axes=shape_to_axes(y_array.shape),
                                     name=tf_node.name)
        else:
            ng_y_array = None

        return ng_x_array, ng_y_array
