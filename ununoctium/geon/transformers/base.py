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
import numbers
import collections
from future.utils import with_metaclass

import numpy as np

from geon.backends.graph.environment import get_current_environment
from geon.op_graph.op_graph import Op, placeholder
from geon.analysis.memory import assign_buffers


class Computation(with_metaclass(abc.ABCMeta, object)):
    def __init__(self, transformer, returns, *args):
        """
        Defines computation.

        Arguments:
          transformer: TODO
          returns: If an Op, return the value of the Op, if sequence of Ops, return
                   the sequence of values, if a Set return a map, if None, return None.
          args: Placeholders will be arguments to the function, other values are ops
                to compute but not return.
        """
        self.transformer = transformer
        self.returns = returns
        self.ops = set()
        if isinstance(returns, collections.Set):
            self.ops.update(returns)
        elif isinstance(returns, collections.Sequence):
            self.ops.update(returns)
        elif isinstance(returns, Op):
            self.ops.add(returns)
        elif returns is None:
            pass
        else:
            raise ValueError()

        self.parameters = []
        for arg in args:
            if isinstance(arg, placeholder):
                self.parameters.append(arg)
            if isinstance(arg, Op):
                self.ops.add(arg)
            else:
                raise ValueError()

        self.transformer.all_results.update(self.ops)
        self.executor = None

    def __call__(self, *args):
        # TODO Should this be automatic?
        self.transformer.initialize()

        # Get the parameters to the device
        for param, arg in zip(self.parameters, args):
            self.transformer.copy_to_model(param, arg)
        self.executor()

        # TODO Should copy this out of the device to a destination when it is not scalar
        def value(op):
            """TODO."""
            return op.tensor_description(self.transformer).value

        if isinstance(self.returns, Op):
            return value(self.returns)
        elif isinstance(self.returns, collections.Set):
            result = dict()
            for op in self.returns:
                dict[op] = value(op)
            return result

        elif isinstance(self.returns, collections.Sequence):
            return tuple(value(op) for op in self.returns)

        else:
            return None


class Transformer(with_metaclass(abc.ABCMeta, object)):
    """
    Given a list of ops you want to compute the results of, this transformer
    will compile the graph required to compute those results and exposes an
    evaluate method to execute the compiled graph.
    """

    def __init__(self, environment=None, fusion=None, **kvargs):
        """
        TODO.

        Arguments:
          results: A list of Ops whose results the Transformer should
                   return on `.evaluate()`.  There aren't any good reasons to initialize a
                   transformer with None except for in tests.
          environment: The environment to use to grab things like axis.  WARNING: `environment`
                       will be deprecated soon.
        """
        super(Transformer, self).__init__(**kvargs)
        self.transform_hook = None
        if environment is None:
            environment = get_current_environment()
        self.environment = environment
        self.computations = set()
        self.all_results = set()
        self.values = dict()
        self.cache = dict()
        self.tensor_descriptions = set()
        self.finalized = False
        self.allocated = False
        self.initialized = False
        self.opids = dict()
        self.fusion = fusion

    def finalize(self):
        """
        Prepare for allocation.
        """
        Op.simple_prune(self.all_results)

        # Crate tensor descriptions
        ops = Op.ordered_ops(self.all_results)
        inits = self.ordered_initializers(ops)
        all_ops = ops + inits
        # Give ids
        for op in all_ops:
            if op not in self.opids:
                self.opids[op] = len(self.opids)

        # Create tensor descriptions
        for op in all_ops:
            op.create_tensor_descriptions(self)

        self.dataflow, self.memory = assign_buffers(
            self, self.all_results, self.fusion
        )

        for tensor_description in self.tensor_descriptions:
            tensor_description.initialize()

        self.ops = self.dataflow.instructions
        self.order = {op: i for i, op in enumerate(self.ops)}
        self.initializers = self.ordered_initializers(self.ops)

        self.finalized = True

    def allocate(self):
        """
        Allocate storage.

        Will finalize if not already done.
        """
        if self.allocated:
            return
        if not self.finalized:
            self.finalize()
        self.allocate_ordered_ops(self.initializers)
        self.allocate_ordered_ops(self.ops)

        # Compile the computations now that we know their storage
        for computation in self.computations:
            ordered_ops = self.dataflow.can_reach(computation.ops, order=self.ops)
            computation.executor = self.compile_computation(ordered_ops)

        self.allocated = True

    def initialize(self):
        """
        Initialize storage.  Will allocate if not already performed.
        """
        if self.initialized:
            return
        self.allocate()
        self.transform_ordered_ops(self.initializers)
        self.initialized = True

    def compile_computation(self, ordered_ops):
        """
        Return a function that will run the computation in this transformer.

        Should be overridden by transformers.

        Arguments:
          ordered_ops: TODO

        Returns:
          Function that runs the computation
        """
        return lambda: self.transform_ordered_ops(ordered_ops)

    def computation(self, results, *parameters):
        """
        Adds a computation to the transformer.

        Arguments:
          results: Values to be computed
          parameters: Values to be set as arguments to evaluate

        Returns:
          Dictionary from results to their values
        """
        if self.finalized:
            raise ValueError(
                'Cannot create computations from a finalized transformer'
            )

        result = Computation(self, results, *parameters)
        self.computations.add(result)
        return result

    def copy_to_model(self, tensor_op, value):
        """
        TODO.

        Arguments:
          tensor_op: TODO
          value: TODO

        Returns:

        """
        self.allocate()
        td = tensor_op.tensor_description(self)
        if isinstance(value, numbers.Real):
            self.fill(td.value, value)
        elif isinstance(value, np.ndarray):
            if td.value.shape != value.shape:
                raise ValueError()
            self.set_item(td.value, (), value)
        else:
            raise ValueError()

    def ordered_initializers(self, ordered_ops):
        """
        TODO.

        Arguments:
          ordered_ops: TODO

        Returns:

        """
        todo = set(ordered_ops)
        initializers = set()
        while todo:
            these_ops = todo
            todo = set()
            for op in these_ops:
                initializers.update(op.initializers)
                todo.update(op.initializers)

        ordered_initializer_ops = []
        visited = set()
        inits = set()

        def visit(node):
            """
            TODO.

            Arguments:
              node: TODO

            Returns:

            """
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
        """
        TODO.

        Arguments:
          ordered_ops: TODO
        """
        # Allocate
        for op in ordered_ops:
            op.allocate(self)

    def transform_ordered_ops(self, ordered_ops):
        """
        Call op.transform_call_info on every op in ordered_ops.

        If transform_hooks are present on the op or on this transformer, call
        those as well.well

        Arguments:
          ordered_ops: TODO
        """

        def transform_op(op):
            """
            This is the call we would make directly if there were no hooks.
            wrap it up into a function so we can pass it to a hook which has
            the responsibility of making the call to the hook.  This allows the
            hook to execute both before and after the transform.

            Arguments:
              op: TODO
            """
            op.transform_call_info(self)

        for op in ordered_ops:
            if op.transform_hook is not None:
                op.transform_hook(self, op, transform_op)
            elif self.transform_hook is not None:
                self.transform_hook(self, op, transform_op)
            else:
                # run the transform without any hooks
                transform_op(op)

    def set_value(self, op, tensor):
        """
        TODO.

        Arguments:
          op: TODO
          tensor: TODO
        """
        op.tensor_description(self).value = tensor

    @abc.abstractmethod
    def make_raw_buffer(self, size):
        """
        Allocate raw buffer.

        Arguments:
          size: Size in bytes of the buffer to allocate
        """

    @abc.abstractmethod
    def nparray(self, tensor_description, array):
        """
        Allocate a tensor and initialize it with a numpy array.

        This needs to be executed from the CPU since that's where the NumPy array is.

        Arguments:
          tensor_description: TODO
          array: TODO

        Returns:
          Reference to the tensor
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def rng(self, seed=None):
        """
        Allocate a random number generator.

        Arguments:
          seed: An integer.

        Returns:
          Reference to the random number generator.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def rng_uniform_tensor(self, rng, tensor_description, low, high):
        """
        Allocate a tensor initialized with a uniform distribution.

        Arguments:
          rng: Random number generator
          tensor_description: Description of the tensor's type, shape, size, and strides.
          low: TODO
          high: TODO

        Returns:
          Reference to uniform distribution.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def rng_normal_tensor(self, rng, tensor_description, loc, scale):
        """
        Allocate a tensor initialized with a uniform distribution.

        Arguments:
          rng: Random number generator
          tensor_description: Description of the tensor's type, shape, size, and strides.
          loc: TODO
          scale: TODO

        Returns:
          Reference to normal distribution.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def tensor_view(self, tensor_description):
        """
        Allocate a view of a tensor.

        Arguments:
          tensor_description: Description of the tensor view.

        Returns:
          Reference to the tensor view.
        """
        raise NotImplementedError()

    # Side-effects
    # TODO Should this be combined with set_item?
    @abc.abstractmethod
    def fill(self, out, value):
        """
        Initialize a tensor with a scalar.

        Arguments:
          out: Tensor to initialize
          value: Scalar value.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def set_item(self, tensor, item, value):
        """
        Implements __setitem__.

        Arguments:
          tensor: Tensor to be modified
          item: Slice/index to set
          value: New values for tensor[item]
        """
        raise NotImplementedError()

    # Operations
    @abc.abstractmethod
    def absolute(self, x, out):
        """
        Absolute value.

        Arguments:
          x: Input tensor
          out: Output tensor, may be input.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def add(self, x, y, out):
        """
        out = x + y

        Arguments:
          x: TODO
          y: TODO
          out: TODO
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def argmax(self, x, out):
        """
        Argmax on dim 0 of x.

        Arguments:
          x: TODO
          out: Integer tensor
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def argmin(self, x, out):
        """
        Argmin on dim 0 of x.

        Arguments:
          x: TODO
          out: Integer tensor
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def cos(self, x, out):
        """
        Cosine.

        Arguments:
          x: TODO
          out: TODO
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def divide(self, x, y, out):
        """
        out = x/y

        Arguments:
          x: TODO
          y: TODO
          out: TODO
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def dot(self, x, y, out):
        """
        Generalized dot using NumPy dimension conventions.

        Arguments:
          x: TODO
          y: TODO
          out: TODO
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def equal(self, x, y, out):
        """
        Numerical equality.

        Arguments:
          x: TODO
          y: TODO
          out: Boolean tensor.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def exp(self, x, out):
        """
        out = e^x

        Arguments:
          x: TODO
          out: TODO
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def greater(self, x, y, out):
        """
        x > y

        Arguments:
          x: TODO
          y: TODO
          out: Boolean tensor.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def greater_equal(self, x, y, out):
        """
        x >= y

        Arguments:
          x: TODO
          y: TODO
          out: Boolean tensor.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def less(self, x, y, out):
        """
        x < y

        Arguments:
          x: TODO
          y: TODO
          out: Boolean tensor.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def less_equal(self, x, y, out):
        """
        x <= y

        Arguments:
          x: TODO
          y: TODO
          out: Boolean tensor.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def log(self, x, out):
        """
        log(x)

        Arguments:
          x: TODO
          out: Boolean tensor.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def max(self, x, axis, out):
        """
        Maximum x value on axis.

        Arguments:
          x: TODO
          axis: Axis to maximize over.
          out: TODO
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def maximum(self, x, y, out):
        """
        max(x, y)

        Arguments:
          x: TODO
          y: TODO
          out: TODO
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def min(self, x, axis, out):
        """
        Minimum x value on axis.

        Arguments:
          x: TODO
          axis: Axis to maximize over.
          out: TODO
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def minimum(self, x, y, out):
        """
        min(x, y)

        Arguments:
          x: TODO
          y: TODO
          out: TODO
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def multiply(self, x, y, out):
        """
        x*y

        Arguments:
          x: TODO
          y: TODO
          out: TODO
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def negative(self, x, out):
        """
        -x

        Arguments:
          x: TODO
          out: TODO
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def not_equal(self, x, y, out):
        """
        x != y

        Arguments:
          x: TODO
          y: TODO
          out: Boolean tensor.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def onehot(self, idx, out):
        """
        TODO

        Arguments:
          idx: Index tensor
          out: 2-d tensor, axis 0 gets onehot expansion
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def reciprocal(self, x, out):
        """
        1/x

        Arguments:
          x: TODO
          out: TODO
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def sign(self, x, out):
        """
        signum(x)

        Arguments:
          x: TODO
          out: TODO
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def sin(self, x, out):
        """
        sine(x)

        Arguments:
          x: TODO
          out: TODO
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def sqrt(self, x, out):
        """
        sqrt(x)

        Arguments:
          x: TODO
          out: TODO
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def square(self, x, out):
        """
        x^2

        Arguments:
          x: TODO
          out: TODO
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def subtract(self, x, y, out):
        """
        x - y

        Arguments:
          x: TODO
          y: TODO
          out: TODO
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def sum(self, x, axis, out):
        """
        sum of x over axis

        Arguments:
          x: TODO
          axis: TODO
          out: TODO
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def tanh(self, x, out):
        """
        tanh(x)

        Arguments:
          x: TODO
          out: TODO
        """
        raise NotImplementedError()

    # @abc.abstractmethod
    def allreduce(self, x, out):
        """
        MPI allreduce

        Arguments:
          x: TODO
          out: TODO
        """
        raise NotImplementedError()

    # @abc.abstractmethod
    def conv2d(self, x, y, out):
        """
        2 dimensional convolution

        Arguments:
          x: TODO
          y: TODO
          out: TODO
        """
        raise NotImplementedError()
