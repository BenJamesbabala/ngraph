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
from __future__ import print_function
from builtins import next, zip
import geon.frontends.declarative_graph as nm
import geon.frontends.base.axis as ax
# from geon.util import analysis
from neon.initializers import Uniform


@nm.with_name_scope
def linear(m, x, x_axes, axes, batch_axes=(), init=None):
    """
    TODO.

    Arguments:
      m: TODO
      x: TODO
      x_axes: TODO
      axes: TODO
      batch_axes: TODO

    Returns:
      TODO
    """
    m.weights = nm.Variable(axes=axes + x_axes -
                            batch_axes, init=init, tags='parameter')
    m.bias = nm.Variable(axes=axes, init=init, tags='parameter')
    return nm.dot(m.weights, x) + m.bias


def affine(x, activation, batch_axes=None, **kwargs):
    """
    TODO.

    Arguments:
      x: TODO
      activation: TODO
      batch_axes: TODO
      **kwargs: TODO

    Returns:
      TODO
    """
    return activation(
        linear(
            x,
            batch_axes=batch_axes,
            **kwargs),
        batch_axes=batch_axes)


@nm.with_name_scope
def mlp(params, x, activation, x_axes, shape_spec, axes, **kwargs):
    """
    TODO.

    Arguments:
      params: TODO
      x: TODO
      activation: TODO
      x_axes: TODO
      shape_spec: TODO
      axes: TODO
      **kwargs: TODO

    Returns:
      TODO
    """
    value = x
    last_axes = x_axes
    with nm.name_scope_list('L') as layers:
        for hidden_activation, hidden_axes, hidden_shapes in shape_spec:
            for layer, shape in zip(layers, hidden_shapes):
                layer.axes = tuple(nm.Axis(like=axis) for axis in hidden_axes)
                for axis, length in zip(layer.axes, shape):
                    axis.length = length
                value = affine(value, activation=hidden_activation,
                               x_axes=last_axes, axes=layer.axes, **kwargs)
                last_axes = value.axes
        next(layers)
        value = affine(value, activation=activation,
                       x_axes=last_axes, axes=axes, **kwargs)
    return value


# noinspection PyPep8Naming
def L2(x):
    """
    TODO.

    Arguments:
      x: TODO

    Returns:
      TODO
    """
    return nm.dot(x, x)


def cross_entropy(y, t):
    """
    TODO.

    Arguments:
      y: Estimate
      t: Actual 1-hot data

    Returns:
      TODO
    """
    return -nm.sum(nm.log(y) * t)


class MyTest(nm.Model):
    """TODO."""

    def __init__(self, **kwargs):
        super(MyTest, self).__init__(**kwargs)

        uni = Uniform(-.01, .01)

        g = self.graph

        g.x = nm.Tensor(axes=(ax.C, ax.H, ax.W, ax.N))
        g.y = nm.Tensor(axes=(ax.Y, ax.N))

        layers = [(nm.tanh, (ax.H, ax.W), [(16, 16)] * 1 + [(4, 4)])]

        g.value = mlp(
            g.x,
            activation=nm.softmax,
            x_axes=g.x.axes,
            shape_spec=layers,
            axes=g.y.axes,
            batch_axes=(ax.N,),
            init=uni)

        g.error = cross_entropy(g.value, g.y)
        print(g.error)
        # L2 regularizer of parameters
        reg = None
        for param in nm.find_all(
                types=nm.Variable,
                tags='parameter',
                used_by=g.value):
            l2 = L2(param)
            if reg is None:
                reg = l2
            else:
                reg = reg + l2
        g.loss = g.error + .01 * reg

    def dump(self):
        """TODO."""
        def visitor(_):
            """TODO."""
            print('{s} # {info}'.format(
                s=_, info=_.file_info))

        nm.Node.visit_input_closure([self.graph.loss], visitor)


MyTest().dump()
