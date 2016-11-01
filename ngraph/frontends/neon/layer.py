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
from builtins import object
import ngraph as ng
from neon import NervanaObject


# TODO These are stubs for implementing Neon's layers

class Layer(object):
    """TODO."""

    def __init__(
            self,
            name=None,
            graph=None,
            axes=None,
            parallelism="Unknown",
            **kwargs):
        super(Layer, self).__init__(**kwargs)
        self.name = name
        self.axes = axes

    def configure(self, in_obj):
        """
        Add to computation graph for the layer.

        Arguments:
          in_obj: The input for the layer

        Returns:
          The output of the layer
        """
        return in_obj


class BranchNode(Layer):
    """TODO."""

    def __init__(self, **kwargs):
        super(BranchNode, self).__init__(**kwargs)


class SkipNode(Layer):
    """TODO."""

    def __init__(self, **kwargs):
        super(SkipNode, self).__init__(**kwargs)


class ParameterLayer(Layer):
    """TODO."""

    def __init__(self, init=None, name=None, parallelism='Unknown', **kwargs):
        super(ParameterLayer, self).__init__(name=name, parallelism=parallelism,
                                             **kwargs)
        self.has_params = True
        self.init = init
        self.W = None
        self.dW = None
        self.batch_sum = None


# class nnBatchNorm(object):
#     def __init__(self, out_axis, eps=1.0e-6):
#         self.out_axis = out_axis
#         self.eps = eps

#     def initialize(self, in_obj):
#         bn_axes = ng.Axes
#         self.gamma = ng.Variable(axes=bn_axes, initial_value=1.)
#         self.beta = ng.Variable(axes=bn_axes, initial_value=0.)

#     def __call__(self, in_obj):
#         xhat = (in_obj - ng.mean(in_obj, reduction_axes=)) / ng.sqrt(ng.var(in_obj + self.eps))
#         return (xhat - self.beta) * self.gamma

class nnAffine(object):
    def __init__(self, out_axis, init, activation=(lambda x : x), bias_init=None):
        self.out_axis = out_axis
        self.init = init
        self.activation = activation
        self.b = 0
        self.bias_init = None

    def initialize(self, in_axes):
        # if self.bias_init:
        #     b_axes = ng.Axes([self.out_axis])
        #     self.b = ng.Variable(axes=b_axes, initial_value=self.bias_init(b_axes.lengths))
        w_axes = ng.Axes.linear_map_axes(in_axes.sample_axes(), [self.out_axis])
        self.W = ng.Variable(axes=w_axes, initial_value=self.init(w_axes.lengths))
        return ng.Axes(in_axes.batch_axes() + [self.out_axis])

    def get_outputs(self, in_obj):
        return self.activation(ng.dot(self.W, in_obj) + self.b)

class nnPreprocess(object):
    def __init__(self, functor):
        self.functor = functor

    def initialize(self, in_axes):
        return in_axes

    def get_outputs(self, in_obj):
        return self.functor(in_obj)

class Convolution(ParameterLayer):
    """
    Convolutional layer implementation.

    Arguments:
       fshape (tuple(int)): three dimensional shape of convolution window
       strides (int, dict, optional): strides to apply convolution
           window over. An int applies to both dimensions, or a dict with
           str_h and str_w applies to h and w dimensions distinctly.  Defaults
           to str_w = str_h = None
       padding (int, dict, optional): padding to apply to edges of
           input. An int applies to both dimensions, or a dict with pad_h
           and pad_w applies to h and w dimensions distinctly.  Defaults
           to pad_w = pad_h = None
       init (Initializer, optional): Initializer object to use for
           initializing layer weights
       name (str, optional): layer name. Defaults to "ConvolutionLayer"
    """

    def __init__(self, fshape, strides={}, padding={}, init=None, bsum=False,
                 name=None, parallelism="Data", cafe_compat=False, dtype=None):
        super(Convolution, self).__init__(init, name, parallelism)
        self.be = NervanaObject.be
        self.weight_shape = None
        self.nglayer = None
        self.bsum = bsum
        self.convparams = {'str_h': 1, 'str_w': 1, 'str_d': 1,
                           'pad_h': 0, 'pad_w': 0, 'pad_d': 0,
                           'T': 1, 'D': 1}  # 3D parameters

        # keep around args in __dict__ for get_description.
        self.fshape = fshape
        self.strides = strides
        self.padding = padding
        self.cafe_compat = cafe_compat
        self.dtype = dtype

        if isinstance(fshape, tuple) or isinstance(fshape, list):
            fkeys = ('R', 'S', 'K') if len(
                fshape) == 3 else ('T', 'R', 'S', 'K')
            fshape = {k: x for k, x in zip(fkeys, fshape)}
        if isinstance(strides, int):
            strides = {'str_h': strides, 'str_w': strides}
        if isinstance(padding, int):
            padding = {'pad_h': padding, 'pad_w': padding}
        for d in [fshape, strides, padding]:
            self.convparams.update(d)

    def __str__(self):
        spatial_dim = len(self.in_shape[1:])
        spatial_str = "%d x (" + "x".join(("%d",) * spatial_dim) + ")"
        padstr_str = ",".join(("%d",) * spatial_dim)
        padstr_dim = ([] if spatial_dim == 2 else ['d']) + ['h', 'w']

        pad_tuple = tuple(self.convparams[k]
                          for k in ['pad_' + d for d in padstr_dim])
        str_tuple = tuple(self.convparams[k]
                          for k in ['str_' + d for d in padstr_dim])

        fmt_tuple = (self.name,) + self.in_shape + \
            self.out_shape + pad_tuple + str_tuple
        fmt_string = "Convolution Layer '%s': " + \
                     spatial_str + " inputs, " + spatial_str + " outputs, " + \
                     padstr_str + " padding, " + padstr_str + " stride"

        return ((fmt_string % fmt_tuple))

    def configure(self, in_obj):
        """
        Sets shape based parameters of this layer given an input tuple or int
        or input layer.

        Arguments:
            in_obj (int, tuple, Layer or Tensor): object that provides shape
                                                  information for layer

        Returns:
            (tuple): shape of output data
        """
        super(Convolution, self).configure(in_obj)
        assert self.nglayer is None
        self.convparams.update(in_obj.shape_dict())
        self.nglayer = self.be.conv_layer(self.be.default_dtype, **self.convparams)
        assert self.weight_shape is None
        names = ['C', 'T', 'R', 'S', 'K']
        weights_axes = [ng.Axis(self.convparams[key], name=key) for key in names]
        weights = ng.Variable(axes=weights_axes, init=self.init)
        self.weight_shape = self.nglayer.dimF2
        if self.bsum:
            self.batch_sum_shape = (self.nglayer.K, 1)
        return ng.convolution(self.nglayer, in_obj, weights)


class Deconvolution(ParameterLayer):
    """TODO."""

    def __init__(self, fshape, strides={}, padding={}, bsum=False, **kwargs):
        super(Deconvolution, self).__init__(**kwargs)


class Pooling(Layer):

    """
    Pooling layer implementation.

    Arguments:
        fshape (int, tuple(int, int)): one or two dimensional shape
            of pooling window
        op (str, optional): pooling operation in [max, avg]. Defaults to "max"
        strides (int, dict, optional): strides to apply pooling window
            over. An int applies to both dimensions, or a dict with str_h
            and str_w applies to h and w dimensions distinctly.  Defaults
            to str_w = str_h = None
        padding (int, dict, optional): padding to apply to edges of
            input. An int applies to both dimensions, or a dict with pad_h
            and pad_w applies to h and w dimensions distinctly.  Defaults
            to pad_w = pad_h = None
        name (str, optional): layer name. Defaults to "PoolingLayer"
    """

    def __init__(self, fshape, op="max", strides={}, padding={},
                 name=None):
        super(Pooling, self).__init__(name)
        self.be = NervanaObject.be
        self.poolparams = {'str_h': None, 'str_w': None, 'str_d': None, 'str_c': None,
                           'pad_h': 0, 'pad_w': 0, 'pad_d': 0, 'pad_c': 0,
                           'J': 1, 'T': 1, 'D': 1, 'op': op}  # 3D paramaters

        # keep args around in __dict__ for get_description
        self.op = op
        self.fshape = fshape
        self.strides = strides
        self.padding = padding
        self.owns_delta = True
        if isinstance(fshape, int):
            fshape = {'R': fshape, 'S': fshape}
        elif isinstance(fshape, tuple):
            fkeys = ('R', 'S') if len(fshape) == 2 else ('T', 'R', 'S')
            fshape = {k: x for k, x in zip(fkeys, fshape)}
        elif fshape == 'all':
            fshape = dict(R=None, S=None)
        if isinstance(strides, int):
            strides = {'str_h': strides, 'str_w': strides}
        if isinstance(padding, int):
            padding = {'pad_h': padding, 'pad_w': padding}
        for d in [fshape, strides, padding]:
            self.poolparams.update(d)
        self.nglayer = None

    def __str__(self):
        return "Pooling Layer '%s': %d x (%dx%d) inputs, %d x (%dx%d) outputs" % (
               self.name,
               self.in_shape[0], self.in_shape[1], self.in_shape[2],
               self.out_shape[0], self.out_shape[1], self.out_shape[2])

    def configure(self, in_obj):
        """
        Sets shape based parameters of this layer given an input tuple or int
        or input layer.

        Arguments:
            in_obj (int, tuple, Layer or Tensor): object that provides shape
                                                  information for layer

        Returns:
            (tuple): shape of output data
        """
        super(Pooling, self).configure(in_obj)
        assert self.nglayer is None
        shapedict = in_obj.shape_dict()
        shapedict['N'] = self.be.bsz
        self.poolparams.update(shapedict)
        if self.poolparams['R'] is None:
            self.poolparams['R'] = shapedict['H']
            self.poolparams['S'] = shapedict['W']
        self.nglayer = self.be.pool_layer(self.be.default_dtype, **self.poolparams)
        (K, M, P, Q, N) = self.nglayer.dimO
        self.out_shape = (K, M, P, Q)
        out_shape_dict = dict(C=K, D=M, H=P, W=Q, N=N)
        argmax_axes = [ng.Axis(out_shape_dict[key], name=key) for key in ['C', 'D', 'H', 'W', 'N']]
        argmax = ng.persistent_tensor(axes=argmax_axes, name='pool')
        return ng.pooling(self.nglayer, in_obj, argmax)


class Linear(ParameterLayer):
    """TODO."""

    def __init__(self, nout, bsum=False, **kwargs):
        super(Linear, self).__init__(**kwargs)
        self.nout = nout
        self.inputs = None
        self.bsum = bsum

    def configure(self, in_obj):
        """
        Sets shape based parameters of this layer given an input tuple or int
        or input layer.

        Arguments:
           in_obj (int, tuple, Layer or Tensor): object that provides shape
                                                 information for layer

        Returns:
           (Tensor): output

        """
        in_obj = super(Linear, self).configure(in_obj)
        out_axes = ng.Axes(self.axes or [ng.Axis(self.nout, name='Hidden')])

        in_axes = in_obj.axes.sample_axes()
        in_axes = in_axes - in_axes.recurrent_axes()

        self.W = ng.Variable(axes=out_axes - out_axes.recurrent_axes() + in_axes.get_dual(),
                             init=self.init)
        return ng.dot(self.W, in_obj, use_dual=True)


class Bias(ParameterLayer):
    """
    A bias layer implemented that adds a learned bias to inputs and produces
    outputs of the same shape.

    Arguments:
       init (Initializer, optional): Initializer object to use for
           initializing layer bias
       name (str, optional): Layer name. Defaults to "BiasLayer"

    Returns:

    """

    def __init__(self, init, **kwargs):
        super(Bias, self).__init__(**kwargs)
        self.y = None
        self.owns_output = False
        self.owns_delta = False

    def configure(self, in_obj):
        """
        Sets shape based parameters of this layer given an input tuple or int
        or input layer.

        Arguments:
            graph: TODO.
            in_obj (int, tuple, Layer or Tensor): object that provides shape
                                                 information for layer
        Returns:
            (Tensor): output

        """
        in_obj = super(Bias, self).configure(in_obj)
        return in_obj + ng.Variable(axes=in_obj.axes.sample_axes())


class Activation(Layer):
    """
    A layer that applies a specified transform to the inputs and
    produces outputs of the same shape.

    Generally used to implement nonlinearities for layer post activations.

    Arguments:
       transform (Transform): a transform object with fprop and bprop
           functions to apply
       name (str, optional): Layer name. Defaults to "ActivationLayer"
    """

    def __init__(self, transform, **kwargs):
        super(Activation, self).__init__(**kwargs)
        self.transform = transform

    def configure(self, in_obj):
        """
        Sets shape based parameters of this layer given an input tuple or int
        or input layer.

        Arguments:
          in_obj: input to the layer

        Returns:
          (Tensor): output

        """
        in_obj = super(Activation, self).configure(in_obj)
        return self.transform(in_obj)


class DataTransform(Layer):
    """TODO."""

    def __init__(self, transform, **kwargs):
        super(DataTransform, self).__init__(**kwargs)


class ColorNoise(Layer):
    """TODO."""

    def __init__(
            self,
            colorpca=None,
            colorstd=None,
            noise_coeff=0.1,
            name="ColorNoiseLayer",
            **kwargs):
        super(ColorNoise, self).__init__(name=name, **kwargs)


class CompoundLayer(list):
    """Base class for macro layers."""

    def __init__(
            self,
            bias=None,
            batch_norm=False,
            activation=None,
            name=None,
            axes=None):
        if batch_norm and (bias is not None):
            raise AttributeError('Batchnorm and bias cannot be combined')
        self.activation = activation
        self.batch_norm = batch_norm
        self.bias = bias
        self.axes = axes

    def add_postfilter_layers(self):
        """TODO."""
        if self.bias is not None:
            self.append(Bias(init=self.bias))
        if self.batch_norm:
            self.append(BatchNorm())
        if self.activation is not None:
            self.append(Activation(transform=self.activation))


class Affine(CompoundLayer):
    """
    A linear layer with a learned bias and activation, implemented as a list
    composing separate linear, bias/batchnorm and activation layers.

    Arguments:
       nout (int, tuple): Desired size or shape of layer output
       init (Initializer, optional): Initializer object to use for
           initializing layer weights and bias
       bias (Initializer): an initializer to use for bias parameters
       activation (Transform): a transform object with fprop and bprop
           functions to apply
       name (str): the root name for the layer, suffixes are automatically
           generated for the component layers

    Returns:

    """

    def __init__(self, nout, init, bias=None,
                 batch_norm=False, activation=None, name=None, **kwargs):
        super(Affine, self).__init__(bias=bias, batch_norm=batch_norm,
                                     activation=activation, name=name, **kwargs)
        self.append(Linear(nout, init=init, bsum=batch_norm,
                           name=name, axes=self.axes))
        self.add_postfilter_layers()


class Conv(CompoundLayer):
    """
    A convolutional layer with a learned bias and activation, implemented as a
    list composing separate Convolution, Bias and Activation layers.

    Arguments:
       fshape (tuple(int)): three dimensional shape of convolution window
       init (Initializer, optional): Initializer object to use for
           initializing layer weights and bias
       strides (int, dict, optional): strides to apply convolution
           window over. An int applies to both dimensions, or a dict with
           str_h and str_w applies to h and w dimensions distinctly.  Defaults
           to str_w = str_h = None
       pad (int, dict, optional): padding to apply to edges of
           input. An int applies to both dimensions, or a dict with pad_h
           and pad_w applies to h and w dimensions distinctly.  Defaults
           to pad_w = pad_h = None
       bias (Initializer): an initializer to use for bias parameters
       activation (Transform): a transform object with fprop and bprop
           functions to apply
       name (str): the root name for the layer, suffixes are automatically
           generated for the component layers

    Returns:

    """

    def __init__(self, fshape, init, strides={}, padding={},
                 bias=None,
                 batch_norm=False,
                 activation=None,
                 name=None):
        super(Conv, self).__init__(bias=bias, batch_norm=batch_norm,
                                   activation=activation, name=name)
        self.append(
            Convolution(
                fshape=fshape,
                strides=strides,
                padding=padding,
                init=init,
                bsum=batch_norm,
                name=name))
        self.add_postfilter_layers()


class Deconv(CompoundLayer):
    """Same as Conv layer, but implements a composite deconvolution layer."""

    def __init__(
            self,
            fshape,
            init,
            strides={},
            padding={},
            bias=None,
            batch_norm=False,
            activation=None,
            name=None):
        super(Deconv, self).__init__(bias=bias, batch_norm=batch_norm,
                                     activation=activation, name=name)
        self.append(
            Deconvolution(
                fshape=fshape,
                strides=strides,
                padding=padding,
                init=init,
                bsum=batch_norm))
        self.add_postfilter_layers()


class LRN(Layer):
    """TODO."""

    def __init__(
            self,
            depth,
            alpha=1.,
            beta=0.,
            ascale=1.,
            bpower=1.,
            **kwargs):
        super(LRN, self).__init__(**kwargs)


class Dropout(Layer):
    """TODO."""

    def __init__(self, keep=0.5, **kwargs):
        super(Dropout, self).__init__(**kwargs)


class LookupTable(ParameterLayer):
    """TODO."""

    def __init__(self, vocab_size, embedding_dim, init, update=True,
                 pad_idx=None, **kwargs):
        super(LookupTable, self).__init__(**kwargs)


class GeneralizedCost(object):
    """
    A cost layer that applies the provided cost function and computes errors
    with respect to inputs and targets.

    Arguments:
      costfunc (Cost): Class with costfunc that computes error.

    Returns:

    """

    def __init__(self, costfunc, name=None, **kwargs):
        super(GeneralizedCost, self).__init__(**kwargs)
        self.costfunc = costfunc
        self.name = name

    def initialize(self, inputs, targets):
        """
        Compute the cost function over the inputs and targets.

        Arguments:
         inputs (Tensor): Tensor containing input values to be compared to
             targets
         targets (Tensor): Tensor containing target values.

        Returns:
          Tensors containing mean cost, total costs, sample costs

        """
        self.costs = self.costfunc(inputs, targets)
        self.total_cost = ng.sum(self.costs, out_axes=())
        self.mean_cost = self.total_cost / ng.batch_size(self.costs)


class BatchNorm(Layer):
    """TODO."""

    def __init__(self, rho=0.9, eps=1e-3, **kwargs):
        super(BatchNorm, self).__init__(**kwargs)


class BatchNormAutodiff(BatchNorm):
    """TODO."""

    def __init__(self, rho=0.99, eps=1e-6, **kwargs):
        super(BatchNormAutodiff, self).__init__(**kwargs)
