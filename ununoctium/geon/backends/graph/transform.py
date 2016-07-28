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
from __future__ import division

import abc
from builtins import object
from future.utils import with_metaclass

from geon.backends.graph.environment import get_current_environment
from geon.backends.graph.graphop import Op


class Transformer(with_metaclass(abc.ABCMeta, object)):

    def __init__(
            self,
            results,
            error=None,
            initialize=False,
            environment=None,
            **kvargs):
        super(Transformer, self).__init__(**kvargs)
        self.transform_hook = None
        if environment is None:
            environment = get_current_environment()
        self.environment = environment
        self.results = results
        self.opids = dict()

        Op.simple_prune(results)

        # print('The memory footprint is {} MB'.format(memory*10**-6))
        # dataflow.render('cifar_mlp.gv', True)

        self.ops = Op.ordered_ops(self.results)
        self.initializers = self.ordered_initializers(self.ops)
        self.initialize_call_info(self.initializers)
        self.initialize_call_info(self.ops)
        self.allocate_ordered_ops(self.initializers)
        self.allocate_ordered_ops(self.ops)
        self.transform_ordered_ops(self.initializers)

    def initialize_call_info(self, ordered_ops):
        # Give ids
        for op in ordered_ops:
            if op not in self.opids:
                self.opids[op] = len(self.opids)

        # Determine required views
        for op in ordered_ops:
            op.call_info

    def ordered_initializers(self, ordered_ops):
        todo = set(ordered_ops)
        initializers = set()
        while todo:
            these_ops = todo
            todo = set()
            for op in these_ops:
                if not op.tensor_axes_info.initialized:
                    initializers.update(op.initializers)
                    todo.update(op.initializers)
                    op.tensor_axes_info.initialized = True

        ordered_initializer_ops = []
        visited = set()
        inits = set()

        def visit(node):
            if node not in visited:
                if node.initializers:
                    if node in inits:
                        if node not in visited:
                            ordered_initializer_ops.append(node)
                            visited.add(node)
                    else:
                        inits.add(node)
                        for n in node.initializers:
                            visit(n)
                else:
                    for n in node.args:
                        visit(n)
                if node not in visited:
                    ordered_initializer_ops.append(node)
                    visited.add(node)

        for node in initializers:
            visit(node)

        return ordered_initializer_ops

    def allocate_ordered_ops(self, ordered_ops):
        # Allocate
        for op in ordered_ops:
            op.tensor_axes_info.allocate(self)

    def transform_ordered_ops(self, ordered_ops):
        for op in ordered_ops:
            op.sync(self)

        def transform_op(op):
            op.transform_call_info(self, *op.call_info)

        for op in ordered_ops:
            if op.transform_hook is not None:
                op.transform_hook(self, op, transform_op)
            elif self.transform_hook is not None:
                self.transform_hook(self, op, transform_op)
            else:
                transform_op(op)

    def transform_ops(self, transfrom_ops):
        ops = Op.ordered_ops(transfrom_ops)
        self.allocate_ordered_ops(ops)
        self.transform_ordered_ops(ops)

    def evaluate(self):
        self.transform_ordered_ops(self.ops)
        r = {}
        for op in self.results:
            r[op] = self.value(op)
        return r

    def value(self, op):
        return op.output_view_info.value

    def set_value(self, op, tensor):
        op.tensor_axes_info.set_tensor(self, tensor)

    # Allocators
    # TODO Should this be combined with tensor_view?
    @abc.abstractmethod
    def empty(self, tensor_description):
        """
        Allocate unitialized tensor.

        :param tensor_description: Description of the tensor's type, shape, size, and strides.
        :return: Reference to the tensor.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def nparray(self, tensor_description, array):
        """
        Allocate a tensor and initialize it with a numpy array.

        This needs to be executed from the CPU since that's where the NumPy array is.

        :param tensor_description:
        :param array:
        :return: Reference to the tensor
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def rng(self, seed=None):
        """
        Allocate a random number generator.

        :param seed: An integer.
        :return: Reference to the random number generator.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def rng_uniform_tensor(self, rng, tensor_description, low, high):
        """
        Allocate a tensor initialized with a uniform distribution.

        :param rng: Random number generator
        :param tensor_description: Description of the tensor's type, shape, size, and strides.
        :param low:
        :param high:
        :return: Reference to uniform distribution.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def rng_normal_tensor(self, rng, tensor_description, loc, scale):
        """
        Allocate a tensor initialized with a uniform distribution.

        :param rng: Random number generator
        :param tensor_description: Description of the tensor's type, shape, size, and strides.
        :param loc:
        :param scale:
        :return: Reference to normal distribution.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def tensor_view(self, tensor_description):
        """
        Allocate a view of a tensor.

        :param tensor_description: Description of the tensor view.
        :return: Reference to the tensor view.
        """
        raise NotImplementedError()

    # Side-effects
    # TODO Should this be combined with set_item?
    @abc.abstractmethod
    def fill(self, out, value):
        """
        Initialize a tensor with a scalar.

        :param out: Tensor to initialize
        :param value: Scalar value.
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def set_item(self, tensor, item, value):
        """
        Implements __setitem__.

        :param tensor: Tensor to be modified
        :param item: Slice/index to set
        :param value: New values for tensor[item]
        :return:
        """
        raise NotImplementedError()

    # Operations
    @abc.abstractmethod
    def absolute(self, x, out):
        """
        Absolute value.

        :param x: Input tensor
        :param out: Output tensor, may be input.
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def add(self, x, y, out):
        """
        out = x + y

        :param x:
        :param y:
        :param out:
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def argmax(self, x, out):
        """
        Argmax on dim 0 of x.

        :param x:
        :param out: Integer tensor
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def argmin(self, x, out):
        """
        Argmin on dim 0 of x.

        :param x:
        :param out: Integer tensor
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def cos(self, x, out):
        """
        Cosine.

        :param x:
        :param out:
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def divide(self, x, y, out):
        """
        out = x/y

        :param x:
        :param y:
        :param out:
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def dot(self, x, y, out):
        """
        Generalized dot using NumPy dimension conventions.

        :param x:
        :param y:
        :param out:
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def equal(self, x, y, out):
        """
        Numerical equality.

        :param x:
        :param y:
        :param out: Boolean tensor.
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def exp(self, x, out):
        """
        out = e^x

        :param x:
        :param out:
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def greater(self, x, y, out):
        """
        x > y

        :param x:
        :param y:
        :param out: Boolean tensor.
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def greater_equal(self, x, y, out):
        """
        x >= y

        :param x:
        :param y:
        :param out: Boolean tensor.
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def less(self, x, y, out):
        """
        x < y

        :param x:
        :param y:
        :param out: Boolean tensor.
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def less_equal(self, x, y, out):
        """
        x <= y

        :param x:
        :param y:
        :param out: Boolean tensor.
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def log(self, x, out):
        """
        log(x)

        :param x:
        :param out:
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def max(self, x, axis, out):
        """
        Maximum x value on axis.

        :param x:
        :param axis: Axis to maximize over.
        :param out:
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def maximum(self, x, y, out):
        """
        max(x, y)

        :param x:
        :param y:
        :param out:
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def min(self, x, axis, out):
        """
        Minimum x value on axis.

        :param x:
        :param axis: Axis to maximize over.
        :param out:
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def minimum(self, x, y, out):
        """
        min(x, y)

        :param x:
        :param y:
        :param out:
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def multiply(self, x, y, out):
        """
        x*y

        :param x:
        :param y:
        :param out:
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def negative(self, x, out):
        """
        -x

        :param x:
        :param out:
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def not_equal(self, x, y, out):
        """
        x != y
        :param x:
        :param y:
        :param out: Boolean tensor.
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def onehot(self, idx, out):
        """

        :param idx: Index tensor
        :param out: 2-d tensor, axis 0 gets onehot expansion
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def reciprocal(self, x, out):
        """
        1/x

        :param x:
        :param out:
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def sign(self, x, out):
        """
        signum(x)

        :param x:
        :param out:
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def sin(self, x, out):
        """
        sine(x)

        :param x:
        :param out:
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def sqrt(self, x, out):
        """
        sqrt(x)

        :param x:
        :param out:
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def square(self, x, out):
        """
        x^2

        :param x:
        :param out:
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def subtract(self, x, y, out):
        """
        x - y

        :param x:
        :param y:
        :param out:
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def sum(self, x, axis, out):
        """
        sum of x over axis

        :param x:
        :param axis:
        :param out:
        :return:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def tanh(self, x, out):
        """
        tanh(x)

        :param x:
        :param out:
        :return:
        """
        raise NotImplementedError()

    def allreduce(self, x, out):
        """
        MPI allreduce
        :param x:
        :param out:
        :return:
        """
        raise NotImplementedError()
