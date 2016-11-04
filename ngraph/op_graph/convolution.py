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

from ngraph.op_graph import op_graph
from ngraph.op_graph.axes import make_axis, Axes


def convolution(dims, inputs, filters, name=None, docstring=None):
    """

    Args:
        dims: Dimensions.
        inputs (TensorOp): The input tensor.
        filters (TensorOp): Filter/kernel tensor.
        name (String, optional): Name for the op.
        docstring (String, optional): Documentation for the op.

    Returns:
        TensorOp: The result of the convolution.

    """
    return ConvolutionOp(dims, inputs, filters, name=name, docstring=docstring)


class ConvolutionOp(op_graph.TensorOp):
    _index = 0

    def __init__(self, dims, inputs, filters, *args, **kwargs):
        """
        Arguments:
            inputs  : input tensor.
            filters : filter/kernel tensor.

        Return:
        """
        if len(inputs.shape) != 5:
            raise ValueError((
                'convolution input shape must be length 5, found {}'
            ).format(len(inputs.shape)))

        if len(filters.shape) != 5:
            raise ValueError((
                'convolution filter shape must be length 5, found {}'
            ).format(len(filters.shape)))

        if 'axes' in kwargs:
            raise ValueError(
                "convolution does not currently support the 'axes' argument.  The "
                "output axes are entirely determined by the shape of the "
                "input and filter Ops."
            )

        if inputs.axes[0].length != filters.axes[0].length:
            raise ValueError((
                'the first axis in input and filter must be the same.  The '
                'first axis in input is {inputs} and in filter is {filters}.'
            ).format(
                inputs=inputs.axes[0],
                filters=filters.axes[0],
            ))

        batch_axes = inputs.axes.batch_axes()
        if len(batch_axes) != 1:
            raise ValueError((
                "Input must have one batch axis.  Found {n_batch_axes} batch "
                "axes: {batch_axes} and {n_sample_axes} sample axes: "
                "{sample_axes}."
            ).format(
                n_batch_axes=len(batch_axes),
                batch_axes=batch_axes,
                n_sample_axes=len(inputs.axes.sample_axes()),
                sample_axes=inputs.axes.sample_axes(),
            ))
        self.batch_axis = batch_axes[0]
        axes = Axes([make_axis(dim) for dim in dims.dimO[:-1]]) + self.batch_axis
        for i, name in enumerate(['C', 'D', 'H', 'W']):
            axes[i].name = name

        self.dims = dims
        self.index = ConvolutionOp._index
        ConvolutionOp._index += 1

        super(ConvolutionOp, self).__init__(
            args=(inputs, filters), *args, axes=axes, **kwargs
        )

    def generate_adjoints(self, adjoints, delta, inputs, filters):
        """
        TODO
        """
        filters.generate_add_delta(adjoints, update_conv(delta, inputs, filters, self))
        inputs.generate_add_delta(adjoints, bprop_conv(delta, inputs, filters, self))


class update_conv(op_graph.TensorOp):
    def __init__(self, delta, inputs, filters, fprop, *args, **kwargs):
        """
        Arguments:
            inputs  : input tensor.
            filters : filter/kernel tensor.
        """
        self.dims = fprop.dims
        self.index = fprop.index

        super(update_conv, self).__init__(
            args=(delta, inputs), *args, axes=filters.axes, **kwargs
        )


class bprop_conv(op_graph.TensorOp):
    def __init__(self, delta, inputs, filters, fprop, *args, **kwargs):
        """
        Arguments:
            inputs  : input tensor.
            filters : filter/kernel tensor.
        """
        self.dims = fprop.dims
        self.index = fprop.index

        super(bprop_conv, self).__init__(
            args=(delta, filters), *args, axes=inputs.axes, **kwargs
        )
