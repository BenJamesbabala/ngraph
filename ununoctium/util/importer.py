#!/usr/bin/env python
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
"""
Import a TensorFlow GraphDef from a protobuf file and convert it to neon's
computation graph.

- TODO: ops used in the CIFAR10_conv example:
    - Conv2D(tf.nn.conv2d), MaxPool(tf.nn.max_pool), LRN(tf.nn.lrn),
      BiasAdd(tf.nn.bias_add),
    - Conv2DBackpropInput, Conv2DBackpropFilter, MaxPoolGrad, LRNGrad,
      BiasAddGrad,
    - QueueDequeueMany, RandomShuffleQueue, QueneEnqueue
- TODO: ops used in the MNIST_LTSM example:
    - Sequence Comparison and Indexing: ArgMax(tf.argmax)
    - Comparison: Equal(tf.equal)
    - Shapes and Shaping: Squeeze(tf.squeeze)
    - Slicing and Joining: Slice(tf.slice), Split(tf.split), Concat(tf.concat),
      Transpose(tf.transpose)
"""

from __future__ import absolute_import, division, print_function

import numpy as np
import scipy.stats as stats
from builtins import range, str
from functools import wraps

import geon as be
from geon.op_graph.op_graph import (TensorOp, softmax, is_constant,
                                    constant_value)
from geon.util.generics import TypeMethods

import tensorflow as tf
from tensorflow.python.framework import tensor_util

ignored_ops = {
    'ScalarSummary', 'ZerosLike', 'InTopK', 'MergeSummary',
}


class _OpTypeMethods(TypeMethods):
    def __init__(self, base_method, **kwargs):
        super(_OpTypeMethods, self).__init__(base_method, **kwargs)

    def on_type_wrapper(self, generic_function, dispatch_type):
        def add_method(method):
            if isinstance(dispatch_type, (list, tuple)):
                for type in dispatch_type:
                    self.methods[type] = method
            else:
                self.methods[dispatch_type] = method
            return generic_function

        return add_method

    def get_method(self, tf_node):
        method = self.methods.get(tf_node.op)
        return method if method is not None else self.base_method


def _generic_method(base_method):
    type_methods = _OpTypeMethods(base_method)

    @wraps(base_method)
    def generic(s, dispatch_arg, *args, **kwargs):
        return type_methods.get_method(dispatch_arg)(s, dispatch_arg, *args,
                                                     **kwargs)

    def on_op(op_str):
        return type_methods.on_type_wrapper(generic, op_str)

    generic.on_op = on_op
    return generic


def _scan_numerical_axes(graph_def):
    """
    Scan the graph to get the numerical axes for each variable.
    Variables are defined and initialized in the next round of graph traversal.

    Args:
      graph_def (GraphDef): a GraphDef object

    Returns:
      names_to_axes: a map from variable name to its axes
      batch_axis: the batch axis
      y_axis: axis for labels, not used for inference graph
    """
    name_to_axes = {}
    batch_axis = None
    y_axis = None
    y_name = ""

    for node in graph_def.node:
        inputs = []
        for i, input_name in enumerate([x for x in node.input]):
            inputs.append(input_name)

        node.op = node.op

        if node.op == 'Placeholder':
            dims = node.attr['shape'].shape
            shape = [d.size for d in dims.dim]

            if batch_axis is None:
                batch_axis = be.NumericAxis(shape[0])

            if len(shape) == 2:
                x_axis = be.NumericAxis(shape[1])
                name_to_axes[node.name] = be.Axes([x_axis, batch_axis])

            elif len(shape) == 1:
                name_to_axes[node.name] = (be.NumericAxis(10), batch_axis)
                y_name = node.name

        elif node.op == 'Variable':
            dims = node.attr['shape'].shape
            shape = [d.size for d in dims.dim]

            if len(shape) == 2:
                name_to_axes[node.name] = be.Axes([be.NumericAxis(shape[0]),
                                                   be.NumericAxis(shape[1])])
                y_axis = be.NumericAxis(shape[1])
            elif len(shape) == 1:
                name_to_axes[node.name] = be.Axes([be.NumericAxis(shape[0])])
            elif len(shape) == 0:
                name_to_axes[node.name] = be.Axes()

        elif node.op == 'Const':
            # in the frozen graph, all variables are converted to constant
            const_tensor = node.attr['value'].tensor
            shape = [d.size for d in const_tensor.tensor_shape.dim]

            if len(shape) == 1 and 'biases' in node.name:
                name_to_axes[node.name] = be.Axes([be.NumericAxis(shape[0])])
            elif len(shape) == 2 and 'weights' in node.name:
                name_to_axes[node.name] = be.Axes([be.NumericAxis(shape[0]),
                                                   be.NumericAxis(shape[1])])

    name_to_axes[y_name] = (y_axis, batch_axis)

    return name_to_axes, batch_axis, y_axis


def _shape_to_numeric_axis(shape):
    """
    Convert shape tuple to backend Axes objects

    Args:
        shape (tuple, list): input shapes

    Returns:
        Axes: backend axes object
    """
    if len(shape) == 0:
        return None
    axis_list = [be.NumericAxis(s) for s in shape]
    return be.Axes(tuple(axis_list))


class TensorFlowImporter:
    """
    Tensorflow GraphDef object to Neon graph converter
    """

    def __init__(self, pb_file, end_node_name="", loss_node_name="",
                 verbose=False):
        """
        Arguments:
            pb_file (str):
            end_node_name (str, optional): the last node name in TensorFlow's
                                           graph
            loss_node_name (str, optional): the final node representing loss
                                            computation
            verbose (bool, optional): if True, prints TensorFlow nodes during
                                      imports
        """

        # fields
        self.x = None
        self.y = None
        self.variables = None
        self.last_op = None
        self.name_to_op = None
        self.loss_op = None
        self.verbose = verbose

        # input fields
        self.pb_file = pb_file
        self.end_node_name = end_node_name
        self.loss_node_name = loss_node_name

        # read graph_def
        graph_def = tf.GraphDef()
        with open(pb_file, 'rb') as f:
            graph_def.ParseFromString(f.read())

        self.name_to_op = {}  # a map from TF node name to Neon op
        self.variables = {}  # trainable variables
        self.init_op = None
        self.update_op = None

        self.ignored_nodes = set()

        # scan axis info
        self.name_to_axes, self.batch_axis, self.y_axis = _scan_numerical_axes(
            graph_def)

        # process nodes
        for tf_node in graph_def.node:
            if self.verbose:
                print(tf_node)
            self.process(tf_node)
        self.last_op = self.name_to_op[tf_node.name]

        # loss op
        if loss_node_name in self.name_to_op:
            self.loss_op = self.name_to_op[loss_node_name]

    def process(self, tf_node):
        # skip ignored ops
        if tf_node.op in ignored_ops or 'save' in tf_node.name:
            self.ignored_nodes.add(tf_node.name)
            return

        # check if one of the inputs is ignored
        inputs = tf_node.input
        for input in inputs:
            if input in self.ignored_nodes:
                self.ignored_nodes.add(tf_node.name)
                return

        # convert other ops
        self.name_to_op[tf_node.name] = None
        self.convert(tf_node, inputs)

    @_generic_method
    def convert(self, tf_node, inputs):
        raise NotImplementedError('op not supported')

    @convert.on_op(['Tanh', 'Sigmoid'])
    def convert(self, tf_node, inputs):
        # unary ops
        unary_ops = {
            'Tanh': be.tanh,
            'Sigmoid': be.sigmoid,
            # TODO: 'Relu': be.relu,
        }
        self.name_to_op[tf_node.name] = unary_ops[tf_node.op](
            self.name_to_op[inputs[0]])

    @convert.on_op(['Add', 'Div', 'MatMul', 'Maximum', 'Mul'])
    def convert(self, tf_node, inputs):
        binary_ops = {
            'Add': be.add,
            'Div': be.divide,
            'MatMul': be.dot,
            'Maximum': be.maximum,
            'Mul': be.multiply,
            # TODO: 'Mod', be.mod,
        }
        # TODO: remove this hardcoded branch after ExpandDims op is implemented
        if tf_node.name == 'gradients/xentropy_grad/mul':
            # use be.Constant(1. / self.bastch_axis.length) as temporal result
            # to replace the output of ExpandDims  (self.name_to_op[inputs[0]])
            self.name_to_op[tf_node.name] = binary_ops[tf_node.op](
                be.Constant(1. / self.batch_axis.length),
                self.name_to_op[inputs[1]], name=tf_node.name)
        else:
            self.name_to_op[tf_node.name] = binary_ops[tf_node.op](
                self.name_to_op[inputs[0]],
                self.name_to_op[inputs[1]], name=tf_node.name)

    @convert.on_op(['Mean', 'Sum'])
    def convert(self, tf_node, inputs):
        reduction_ops = {
            'Mean': be.mean,
            'Sum': be.sum,
            # TODO: 'Prod': be.prod,
        }

        input_tensor = self.name_to_op[inputs[0]]
        assert isinstance(input_tensor, TensorOp)
        input_tensor_axes = self.name_to_op[inputs[0]].axes
        if self.name_to_op[inputs[1]] is None:
            reduction_indices = None
        else:
            reduction_indices = self.name_to_op[inputs[1]].const

        reduction_axes = ()
        if reduction_indices is not None:
            for i in reduction_indices:
                reduction_axes += (input_tensor_axes[int(i)],)

        self.name_to_op[tf_node.name] = reduction_ops[tf_node.op](
            input_tensor,
            reduction_axes=reduction_axes,
            name=tf_node.name)

    @convert.on_op('Relu')
    def convert(self, tf_node, inputs):
        self.name_to_op[tf_node.name] = be.maximum(self.name_to_op[inputs[0]],
                                                   0)

    @convert.on_op('Identity')
    def convert(self, tf_node, inputs):
        self.name_to_op[tf_node.name] = self.name_to_op[inputs[0]]

    @convert.on_op('Placeholder')
    def convert(self, tf_node, inputs):
        dims = tf_node.attr['shape'].shape
        shape = [d.size for d in dims.dim]
        self.name_to_op[tf_node.name] = be.placeholder(
            axes=self.name_to_axes[tf_node.name], name=tf_node.name)
        # TODO: handle other placeholders
        if len(shape) == 2:
            self.x = self.name_to_op[tf_node.name]
        elif len(shape) == 1:
            self.y = self.name_to_op[tf_node.name]

    @convert.on_op('Const')
    def convert(self, tf_node, inputs):
        const_tensor = tf_node.attr['value'].tensor
        shape = [d.size for d in const_tensor.tensor_shape.dim]
        np_val = tensor_util.MakeNdarray(const_tensor)

        if np_val.dtype is np.dtype('O'):
            self.ignored_nodes.add(tf_node.name)
            return

        if tf_node.name in self.name_to_axes:
            axes = self.name_to_axes[tf_node.name]
        else:
            axes = _shape_to_numeric_axis(shape)
        self.name_to_op[tf_node.name] = be.Constant(np_val, axes=axes,
                                                    name=tf_node.name)

    @convert.on_op('Variable')
    def convert(self, tf_node, inputs):
        self.name_to_op[tf_node.name] = be.Variable(
            axes=self.name_to_axes[tf_node.name], name=tf_node.name)
        self.variables[tf_node.name] = self.name_to_op[tf_node.name]

    @convert.on_op('Assign')
    def convert(self, tf_node, inputs):
        var = self.name_to_op[inputs[0]]
        init_value = self.name_to_op[inputs[1]]
        self.name_to_op[tf_node.name] = be.assign(var, init_value)
        var.initializers.append(self.name_to_op[tf_node.name])

    @convert.on_op('AssignAdd')
    def convert(self, tf_node, inputs):
        # TODO: check operations for scala variable
        # Things may broken for other graph in which the scala variable is not
        # named 'global_step'
        if inputs[0] == 'global_step':
            return

        var = self.name_to_op[inputs[0]]
        tensor_to_add = self.name_to_op[inputs[1]]
        self.name_to_op[tf_node.name] = be.assign(var, var + tensor_to_add)

    @convert.on_op('Fill')
    def convert(self, tf_node, inputs):
        # Creates a tensor filled with a scalar value.
        shape_tensor = self.name_to_op[inputs[0]].const
        init_val = self.name_to_op[inputs[1]]
        assert is_constant(init_val)

        if len(shape_tensor.shape) == 0:
            self.name_to_op[tf_node.name] = be.Constant(
                constant_value(init_val), name=tf_node.name)
        else:
            shape = tuple([int(s) for s in shape_tensor])
            array = np.zeros(shape)
            array.fill(constant_value(init_val))
            axes = _shape_to_numeric_axis(shape)
            self.name_to_op[tf_node.name] = be.Constant(array,
                                                        axes=axes,
                                                        name=tf_node.name)

    @convert.on_op(['TruncatedNormal', 'RandomStandardNormal'])
    def convert(self, tf_node, inputs):
        # TODO: implement tf.truncated_normal and tf.random_normal
        # get shape
        shape = self.name_to_op[inputs[0]].const
        shape = tuple([int(s) for s in shape])

        if tf_node.op == 'TruncatedNormal':
            lower, upper = -2.0, 2.0
            mu, sigma = 0, 1
            X = stats.truncnorm((lower - mu) / sigma,
                                (upper - mu) / sigma, loc=mu,
                                scale=sigma)
            val = X.rvs(shape)
        elif tf_node.op == "RandomStandardNormal":
            val = -0.5 + np.random.random_sample(shape).astype(
                np.float32)

        axes = _shape_to_numeric_axis(shape)
        self.name_to_op[tf_node.name] = be.Constant(val, axes=axes,
                                                    name=tf_node.name)

    @convert.on_op('Cast')
    def convert(self, tf_node, inputs):
        # TODO: need a real cast, currently just skip this op
        dst_type = tf_node.attr['DstT']
        src_type = tf_node.attr['SrcT']
        self.name_to_op[tf_node.name] = self.name_to_op[inputs[0]]

    @convert.on_op('SparseSoftmaxCrossEntropyWithLogits')
    def convert(self, tf_node, inputs):
        # implementation of tf.nn.sparse_softmax_cross_entropy_with_logits
        # check its doc via https://goo.gl/7ytJNB and its C++ implementation via
        # https://goo.gl/z5T2my

        pred = softmax(self.name_to_op[inputs[0]], be.Axes(self.y_axis, ))
        label = self.name_to_op[inputs[1]]

        self.name_to_op[tf_node.name] = be.cross_entropy_multi(pred, label,
                                                               out_axes=(
                                                                   self.batch_axis,))
        # equivalent: op = -be.sum(safelog(pred) * label * np.float(1. / np.log(2.0)),
        #                             out_axes=(self.bastch_axis,))

        # this op also calculates gradients and saved in the second output
        sum_exp_logits = be.sum(pred, out_axes=(self.batch_axis,))
        grad = be.divide(pred, sum_exp_logits) - label
        self.name_to_op[tf_node.name + ":1"] = grad

    @convert.on_op('Prod')
    def convert(self, tf_node, inputs):
        # TODO: implement tf.reduce_prod and merge with reduction_ops
        prod_val = np.prod(self.name_to_op[inputs[0]].const)
        self.name_to_op[tf_node.name] = be.Constant(prod_val,
                                                    name=tf_node.name)

    @convert.on_op('Shape')
    def convert(self, tf_node, inputs):
        axes = self.name_to_op[inputs[0]].axes
        shape = [axis.length for axis in axes]

        if len(shape) == 0:
            self.name_to_op[tf_node.name] = be.Constant(0,
                                                        name=tf_node.name)
        else:
            axes = be.Axes(be.NumericAxis(len(shape)), )
            self.name_to_op[tf_node.name] = be.Constant(np.array(shape),
                                                        axes=axes,
                                                        name=tf_node.name)

    @convert.on_op('Rank')
    def convert(self, tf_node, inputs):
        # The rank of a tensor is the number of axis
        shape = self.name_to_op[inputs[0]].shape
        self.name_to_op[tf_node.name] = be.Constant(len(shape),
                                                    name=tf_node.name)

    @convert.on_op('Size')
    def convert(self, tf_node, inputs):
        axes = self.name_to_op[inputs[0]].axes
        shape = [axis.length for axis in axes]
        self.name_to_op[tf_node.name] = be.Constant(np.prod(shape),
                                                    name=tf_node.name)

    @convert.on_op('Range')
    def convert(self, tf_node, inputs):
        start = self.name_to_op[inputs[0]]
        limit = self.name_to_op[inputs[1]]
        delta = self.name_to_op[inputs[2]]
        nums = np.arange(start.const, limit.const, delta.const).astype(
            np.float32)
        self.name_to_op[tf_node.name] = be.Constant(nums, axes=be.Axes(
            be.NumericAxis(len(nums)), ), name=tf_node.name)

    @convert.on_op('Mod')
    def convert(self, tf_node, inputs):
        # TODO: implement tf.mod, currently just skip
        self.name_to_op[tf_node.name] = self.name_to_op[inputs[0]]

    @convert.on_op('DynamicStitch')
    def convert(self, tf_node, inputs):
        # TODO: implement tf.dynamic_stich, currently just use a constant
        self.name_to_op[tf_node.name] = be.Constant(1)

    @convert.on_op('Reshape')
    def convert(self, tf_node, inputs):
        # TODO: implement tf.reshape
        # Currently it just does nothing but pass the first input without
        # actually reshape
        self.name_to_op[tf_node.name] = self.name_to_op[inputs[0]]

    @convert.on_op('Tile')
    def convert(self, tf_node, inputs):
        # Constructs a tensor by tiling a given tensor. Currently use numpy.tile
        # The first input is the result of tf.reshape, which is currently not
        # available
        # TODO: implement tf.reshape and tf.tile

        input = self.name_to_op[inputs[0]]
        multiples = self.name_to_op[inputs[1]]

        # should use the result of multiples as the second arg for np.tile
        # but the value is not available when this graph is constructed.
        array = []
        if is_constant(self.name_to_op[inputs[0]]):
            array = constant_value(self.name_to_op[inputs[0]])
        val = np.tile(array, self.batch_axis.length)
        shape = val.shape
        if len(shape) == 1:
            self.name_to_op[tf_node.name] = be.Constant(val, axes=be.Axes(
                be.NumericAxis(shape[0]), ), name=tf_node.name)
        else:
            assert False

    @convert.on_op('ExpandDims')
    def convert(self, tf_node, inputs):
        # TODO: implement tf.expand_dims
        dim = self.name_to_op[inputs[1]]
        self.name_to_op[tf_node.name] = self.name_to_op[inputs[0]]

    @convert.on_op('BroadcastGradientArgs')
    def convert(self, tf_node, inputs):
        # implementation of bcast_ops.cc (https://goo.gl/5vx4QN)
        sx = self.name_to_op[inputs[0]].const
        sy = self.name_to_op[inputs[1]].const

        grad_x_reduce_ = []
        grad_y_reduce_ = []

        if not np.array_equal(sx, sy):
            x = sx[::-1]
            y = sy[::-1]

            if len(x) > len(y):
                y = np.pad(y, (0, len(x) - len(y)), 'constant',
                           constant_values=1)
            else:
                x = np.pad(x, (0, len(y) - len(x)), 'constant',
                           constant_values=1)

        n = len(x)
        for i in range(n):
            if not x[i] == y[i]:
                if x[i] == 1:
                    grad_x_reduce_.append(n - 1 - i)
                elif y[i] == 1:
                    grad_y_reduce_.append(n - 1 - i)

        if grad_x_reduce_:
            val_x = np.array(grad_x_reduce_)
            axes = be.Axes(be.NumericAxis(len(grad_x_reduce_)), )
            self.name_to_op[tf_node.name] = be.Constant(val_x, axes=axes,
                                                        name=tf_node.name)

        self.name_to_op[tf_node.name + ":1"] = None
        if grad_y_reduce_:
            val_y = np.array(grad_y_reduce_)
            axes = be.Axes(be.NumericAxis(len(grad_y_reduce_)), )
            self.name_to_op[tf_node.name + ":1"] = be.Constant(val_y, axes=axes,
                                                               name=tf_node.name)

    @convert.on_op('ReluGrad')
    def convert(self, tf_node, inputs):
        gradient = self.name_to_op[inputs[0]]
        output = self.name_to_op[inputs[1]]
        self.name_to_op[tf_node.name] = gradient * output

    @convert.on_op('ApplyGradientDescent')
    def convert(self, tf_node, inputs):
        var = self.name_to_op[inputs[0]]
        lr = self.name_to_op[inputs[1]]
        grad = self.name_to_op[inputs[2]]
        updated_var = var - lr * grad
        self.name_to_op[tf_node.name] = be.assign(var, updated_var)

    @convert.on_op('NoOp')
    def convert(self, tf_node, inputs):
        # NoOp adds '^' before each original input name
        if tf_node.name == "GradientDescent/update":
            # gradient descent ops
            self.name_to_op[tf_node.name] = be.doall(
                all=[self.name_to_op[input[1:]] for input in inputs])
            self.update_op = self.name_to_op[tf_node.name]

        elif tf_node.name == "init":
            # variable initialization graph, used only once
            self.name_to_op[tf_node.name] = be.doall(
                all=[self.name_to_op[input[1:]] for input in inputs[:-1]])
            self.init_op = self.name_to_op[tf_node.name]
