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
importing a TensorFlow GraphDef protobuf and convert it to Neon computation graph.

"""

from __future__ import absolute_import, division, print_function
from builtins import str

import geon.backends.graph.funs as be
from geon.backends.graph.arrayaxes import AxisVar
from geon.backends.graph.graphop import Tensor, ComputationOp
from geon.backends.graph.graph_test_utils import *

from tensorflow.python.framework import tensor_util
import numpy as np

# known operators that can be processed by Neon graph importer
known_ops = [
    'Add', 'Div', 'MatMul', 'Maximum', 'Mul', 'Mod',
    'Mean', 'Prod', 'Sum',  # Reduction
    'Identity',
    'Relu', 'Tanh',  # Activation
    'Const', 'Variable', 'Placeholder', 'Range',
    'Assign', 'Cast',
    'SparseSoftmaxCrossEntropyWithLogits',
    'Shape', 'Rank', 'Size', 'Reshape', 'ExpandDims',  # Shapes and Shaping
    'TruncatedNormal',
    'Fill',  # Constant Value Tensors
    'Tile', 'DynamicStitch',  # Slicing and Joining
    'BroadcastGradientArgs', 'ApplyGradientDescent', 'ReluGrad',
]

two_inputs_ops = {
    'Add': be.add,
    'Div': be.divide,
    'MatMul': be.dot,
    'Maximum': be.maximum,
    'Mul': be.multiply,
    # 'Mod' not implemented
}

reduction_ops = {
    'Mean': be.mean,
    'Sum': be.sum,
    # 'Prod': be.prod, # not implemented
}

one_inputs_ops = {
    'Tanh': be.tanh,
}

ignore_ops = {
    'ScalarSummary', 'ZerosLike', 'NoOp',
}


def scan_variables(graph_def, env):
    """
    Scan the graph to get the axes for each variable.
    Variables are defined and initialized in the next round of graph traversal.

    :param
      - graph_def: a GraphDef object
    :return:
      - names_to_axes: a map from variable name to its axes
      - batch_axis: the batch axis
      - in_axis: axis for input data
      - y_axis: axis for labels
    """
    name_to_axes = {}
    in_axis = None
    batch_axis = None
    x_axis = None
    y_axis = None
    y_name = ""

    for node in graph_def.node:
        inputs = []
        for i, input_name in enumerate([x for x in node.input]):
            inputs.append(input_name)

        op_type = node.op

        with be.bound_environment(env):
            if op_type == 'Placeholder':
                dims = node.attr['shape'].shape
                shape = [d.size for d in dims.dim]

                if batch_axis is None:
                    batch_axis = AxisVar(name='batch', length=shape[0])

                if len(shape) == 2:
                    x_axis = AxisVar(name='x', length=shape[1])
                    name_to_axes[node.name] = (x_axis, batch_axis)
                    in_axis = x_axis

                elif len(shape) == 1:
                    name_to_axes[node.name] = (AxisVar(name='y', length=10), batch_axis)
                    y_name = node.name

            elif op_type == 'Variable':
                dims = node.attr['shape'].shape
                shape = [d.size for d in dims.dim]

                if len(shape) == 2:
                    if 'weights' in node.name:
                        assert (in_axis is not None)
                        assert (in_axis.length == shape[0])
                        out_axis = AxisVar(name=node.name, length=shape[1])
                        name_to_axes[node.name] = (in_axis, out_axis)
                        in_axis = out_axis  # now the output axis becomes input axis for the next layer
                        y_axis = out_axis

                elif len(shape) == 1:
                    if 'biases' in node.name:
                        assert (in_axis is not None)
                        assert (in_axis.length == shape[0])
                        name_to_axes[node.name] = (in_axis,)

                elif len(shape) == 0:
                    name_to_axes[node.name] = (AxisVar(name=node.name, length=1),)

    name_to_axes[y_name] = (y_axis, batch_axis)

    return name_to_axes, batch_axis, x_axis, y_axis


def create_nervana_graph(graph_def, env, end_node=None):
    """
    convert TF graph_def to Neon's graph

    :param
      - graph_def: a (frozen) GraphDef object
    :return:
      - graph: converted graph, including:
       - variables: a map from variable names to variables
       - last_op: the last operator of the graph
       - name_to_op: the operations map.
    """

    name_to_op = {}
    variables = {}
    graph = be.Model()

    graph.x = None
    graph.y = None

    name_to_axes, batch_axis, in_axis, y_axis = scan_variables(graph_def, env)
    print(y_axis)
    print(in_axis)
    assert(in_axis is not None)

    for node in graph_def.node:
        op_type = node.op

        if op_type in ignore_ops:
            continue

        if op_type not in known_ops:
            # TODO: raise unrecognized operator error
            print("unrecognized operator: " + op_type)
            break

        print(node)

        inputs = []
        for i, input_name in enumerate([x for x in node.input]):
            inputs.append(input_name)

            print('inputs[' + str(i) + "]: " + inputs[i])

            if inputs[i] in name_to_op and isinstance(name_to_op[inputs[i]], Tensor):
                print(name_to_op[inputs[i]])

        with be.bound_environment(env):
            if op_type in two_inputs_ops:

                if op_type == 'Mul' and node.name == 'gradients/xentropy_grad/mul':
                    # TODO: remove after ExpandDims is implemented
                    op = two_inputs_ops[op_type](name_to_op["xentropy"], be.Constant(1. / batch_axis.length),
                                                 name=node.name)
                else:
                    op = two_inputs_ops[op_type](name_to_op[inputs[0]], name_to_op[inputs[1]], name=node.name)

            elif op_type in one_inputs_ops:
                op = one_inputs_ops[op_type](name_to_op[inputs[0]])

            elif op_type == 'Relu':
                op = be.maximum(name_to_op[inputs[0]], 0)

            elif op_type == 'Identity':
                print(name_to_op[inputs[0]])
                op = name_to_op[inputs[0]]

            elif op_type == 'Placeholder':
                dims = node.attr['shape'].shape
                shape = [d.size for d in dims.dim]
                op = be.placeholder(axes=name_to_axes[node.name], name=node.name)
                if len(shape) == 2:
                    graph.x = op
                elif len(shape) == 1:
                    graph.y = op

            elif op_type == 'Const':
                const_tensor = node.attr['value'].tensor
                shape = [d.size for d in const_tensor.tensor_shape.dim]
                np_val = tensor_util.MakeNdarray(const_tensor)

                if len(shape) == 0:
                    op = be.Constant(np_val, name=node.name)
                elif len(shape) == 1:
                    if 'biases' in node.name:
                        assert (in_axis is not None)
                        assert (in_axis.length == shape[0])
                        op = be.NumPyTensor(np_val, axes=[in_axis], name=node.name)
                    else:
                        op = be.NumPyTensor(np_val, axes=Axes(be.NumericAxis(shape[0]), ), name=node.name)
                elif len(shape) == 2:
                    if 'weights' in node.name:
                        assert (in_axis is not None)
                        assert (in_axis.length == shape[0])
                        out_axis = AxisVar(name=node.name, length=shape[1])
                        op = be.NumPyTensor(np_val, axes=[in_axis, out_axis], name=node.name)
                        in_axis = out_axis  # now the output axis becomes input axis for the next layer
                    else:
                        op = be.NumPyTensor(np_val, axes=Axes(be.NumericAxis(shape[0]),
                                                              be.NumericAxis(shape[1]), ), name=node.name)

            elif op_type == 'Variable':
                variables[node.name] = be.Variable(axes=name_to_axes[node.name], name=node.name)
                op = variables[node.name]

            elif op_type == 'Assign':
                var = name_to_op[inputs[0]]
                init_value = name_to_op[inputs[1]]
                assert (isinstance(var, be.Variable))
                op = be.assign(var, init_value)
                var.initializers.append(op)

            elif op_type == 'Fill':
                # Creates a tensor filled with a scalar value.
                shape_tensor = name_to_op[inputs[0]]
                init_val = name_to_op[inputs[1]]
                assert isinstance(init_val, be.Constant)

                if isinstance(shape, be.Constant):
                    op = be.Constant(init_val.const, name=node.name)
                else:
                    array = np.array(shape_tensor.value)
                    array.fill(init_val.const)
                    print(array)
                    shape = shape_tensor.tensor_axes_info.tensor_description.shape
                    if len(shape) == 1:
                        op = be.NumPyTensor(array, axes=Axes(be.NumericAxis(shape[0])), name=node.name)

            elif op_type == 'TruncatedNormal':
                # TODO: implement tf.truncated_normal
                shape_tensor = name_to_op[inputs[0]]  # numpy ndarray
                assert isinstance(shape_tensor, Tensor)
                shape = shape_tensor.nptensor
                val = np.random.random_sample(shape).astype(np.float32)

                if len(shape) == 0:
                    op = be.Constant(val, name=node.name)
                elif len(shape) == 1:
                    op = be.NumPyTensor(val, axes=Axes(be.NumericAxis(shape[0]), ), name=node.name)
                elif len(shape) == 2:
                    op = be.NumPyTensor(val, axes=Axes(be.NumericAxis(shape[0]),
                                                       be.NumericAxis(shape[1]), ), name=node.name)
                else:
                    print("Not supported")
                    assert False

            elif op_type == 'Cast':
                # TODO: need a real cast, currently just skip this op
                dst_type = node.attr['DstT']
                src_type = node.attr['SrcT']
                op = name_to_op[inputs[0]]

            elif op_type == 'SparseSoftmaxCrossEntropyWithLogits':
                op = be.cross_entropy_multi(name_to_op[inputs[0]], name_to_op[inputs[1]],
                                            out_axes=(batch_axis,))
                name_to_op[node.name + ":1"] = be.cross_entropy_multi(name_to_op[inputs[0]],
                                                                      name_to_op[inputs[1]],
                                                                      out_axes=(batch_axis, y_axis))

            elif op_type in reduction_ops:
                keep_dims = node.attr['keep_dims']
                reduction_indices = name_to_op[inputs[1]]

                # TODO: use the attribute of kee_dims
                # The rank of the tensor is reduced by 1 for each entry in reduction_indices.
                # If keep_dims is true, the reduced dimensions are retained with length 1.

                # TODO: use the reduction_indices info
                # currently the reduction_axes or out_axes is hardcoded.
                # should interpret from the reduction_indices.

                out_axes = None

                if node.name == 'gradients/softmax_linear/add_grad/Sum':
                    out_axes = (batch_axis, y_axis)
                elif node.name == 'gradients/softmax_linear/add_grad/Sum_1':
                    out_axes = (y_axis,)
                elif node.name == 'gradients/hidden2/add_grad/Sum' or \
                                node.name == 'gradients/hidden1/add_grad/Sum':
                    out_axes = name_to_op[inputs[0]].tensor_axes_info.axes
                elif node.name == 'gradients/hidden2/add_grad/Sum_1' or \
                                node.name == 'gradients/hidden1/add_grad/Sum_1':
                    print(name_to_op[inputs[0]].tensor_axes_info.axes)
                    out_axes = (name_to_op[inputs[0]].tensor_axes_info.axes[1],)

                print("out_axes:")
                print(out_axes)
                op = reduction_ops[op_type](name_to_op[inputs[0]], out_axes=out_axes, name=node.name)

            elif op_type == 'Prod':
                # TODO: implement tf.reduce_prod and merge with reduction_ops
                keep_dims = node.attr['keep_dims']
                reduction_indices = name_to_op[inputs[1]]

                if isinstance(name_to_op[inputs[0]], be.Constant):
                    prod_val = np.prod(name_to_op[inputs[0]].const)
                elif isinstance(name_to_op[inputs[0]], be.NumPyTensor):
                    prod_val = np.prod(name_to_op[inputs[0]].nptensor)
                else:
                    assert False

                op = be.Constant(prod_val, name=node.name)

            elif op_type == 'Shape':
                shape = name_to_op[inputs[0]].tensor_axes_info.tensor_description.shape
                print(shape)
                if len(shape) == 0:
                    op = be.Constant(0, name=node.name)
                else:
                    op = be.NumPyTensor(np.array(shape), axes=Axes(be.NumericAxis(len(shape)), ), name=node.name)

            elif op_type == 'Rank':
                # The rank of a tensor is the number of axis
                shape = name_to_op[inputs[0]].tensor_axes_info.tensor_description.shape
                op = be.Constant(len(shape), name=node.name)

            elif op_type == 'Size':
                shape = name_to_op[inputs[0]].tensor_axes_info.tensor_description.shape
                op = be.Constant(np.prod(shape), name=node.name)

            elif op_type == 'Range':
                assert (len(inputs) == 3)
                start = name_to_op[inputs[0]]
                limit = name_to_op[inputs[1]]
                delta = name_to_op[inputs[2]]
                print(start + ", " + limit + " " + delta)
                nums = np.arange(start.const, limit.const, delta.const).astype(np.float32)
                op = be.NumPyTensor(nums, axes=Axes(be.NumericAxis(len(nums)), ), name=node.name)

            elif op_type == 'Mod':
                # TODO: implement tf.mod, currently just skip
                op = name_to_op[inputs[0]]

            elif op_type == 'DynamicStitch':
                # TODO: implemente tf.dynamic_stich, currently just use a constant
                op = be.Constant(1)

            elif op_type == 'Reshape':
                # TODO: implemente tf.reshape
                print('tensor:' + inputs[0])
                print(name_to_op[inputs[0]])
                print('shape:' + inputs[1])
                print(name_to_op[inputs[1]])

                if node.name == 'gradients/xentropy_mean_grad/Reshape':
                    op = name_to_op[inputs[0]]
                elif node.name == 'gradients/softmax_linear/add_grad/Reshape':
                    op = name_to_op[inputs[0]]
                elif node.name == 'gradients/softmax_linear/add_grad/Reshape_1':
                    op = name_to_op[inputs[0]]

            elif op_type == 'Tile':
                # Constructs a tensor by tiling a given tensor.
                # TODO: implement tf.tile
                # the first input is tf.reshape, which is currently not available
                # use numpy.tile instead, so has to provide a constant value instead

                input = name_to_op[inputs[0]]
                multiples = name_to_op[inputs[1]]

                # should use the result of multiples as the second arg for np.tile
                # but the value is not available when this graph is constructed.

                val = np.tile(name_to_op[inputs[0]].const, batch_axis.length)
                shape = val.shape
                if len(shape) == 1:
                    op = be.NumPyTensor(val, axes=Axes(be.NumericAxis(shape[0]), ), name=node.name)

            elif op_type == 'ExpandDims':
                # TODO: implement tf.expand_dims
                op = name_to_op[inputs[0]]

            elif op_type == 'BroadcastGradientArgs':
                sx = name_to_op[inputs[0]].nptensor
                sy = name_to_op[inputs[1]].nptensor

                grad_x_reduce_ = []
                grad_y_reduce_ = []

                if not np.array_equal(sx, sy):
                    x = sx[::-1]
                    y = sy[::-1]

                    if len(x) > len(y):
                        y = np.pad(y, (0, len(x) - len(y)), 'constant', constant_values=1)
                    else:
                        x = np.pad(x, (0, len(y) - len(x)), 'constant', constant_values=1)

                n = len(x)
                for i in xrange(n):
                    if not x[i] == y[i]:
                        if x[i] == 1:
                            grad_x_reduce_.append(n - 1 - i)
                        elif y[i] == 1:
                            grad_y_reduce_.append(n - 1 - i)

                print(grad_x_reduce_)
                print(grad_y_reduce_)
                op = None
                name_to_op[node.name + ":1"] = None

            elif op_type == 'ReluGrad':
                gradient = name_to_op[inputs[0]]
                output = name_to_op[inputs[1]]
                op = gradient * output

            elif op_type == 'ApplyGradientDescent':
                var = name_to_op[inputs[0]]
                lr = name_to_op[inputs[1]]
                grad = name_to_op[inputs[2]]
                updated_var = var - lr * grad
                op = be.assign(var, updated_var)

            print(op)
            print("---------------------------------------------")

            name_to_op[node.name] = op
            last_op_name = node.name

            if node.name == end_node:
                print('last_op: ' + last_op_name)
                break

    graph.variables = variables
    graph.last_op = name_to_op[last_op_name]
    graph.name_to_op = name_to_op

    return graph
