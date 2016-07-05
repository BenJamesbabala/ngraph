import geon.backends.graph.dataloaderbackend
import geon.backends.graph.graph as graph

from geon.backends.graph.names import name_scope_list, with_name_scope, name_scope, next_name_scope
from geon.backends.graph.graph import Model, with_graph_scope, with_environment, get_current_environment
from geon.backends.graph.environment import bound_environment

from geon.backends.graph.ast import deriv, placeholder, Variable, Constant, linear_map_axes, sample_axes, batch_axes
from geon.backends.graph.arrayaxes import axes_list, Axis, AxisVar, \
    set_batch_axes, get_batch_axes, set_phase_axes, get_phase_axes

from geon.backends.graph.ast import absolute, add, argmax, argmin, cos, divide, dot, equal, exp, log, maximum, \
    mean, minimum, multiply, greater, greater_equal, less, less_equal, power
from geon.backends.graph.ast import negative, not_equal, reciprocal, sig, sin, softmax, sqrt, square, subtract, \
    sum
from geon.backends.graph.ast import tanh, safelog, cross_entropy_binary, cross_entropy_multi
from geon.backends.graph.ast import doall, decrement, trace, RNG

from geon.backends.graph.ast import AllReduce


def relu(x, out):
    maximum(x, 0, out)


# TODO These are just here as placeholders
def add_fc_bias(self, inputs, bias):
    pass


def array(self, ary, dtype=None, name=None, persist_values=None, *args):
    pass


def batched_dot(self, A, B, C, alpha=None, beta=None, relu=None):
    pass


def begin(self, block, identifier):
    pass


def bprop_conv(self, layer, F, E, grad_I, alpha=None, repeat=None):
    pass


def bprop_pool(self, layer, I, E, grad_I):
    pass


def check_cafe_compat(self):
    pass


def clip(self, a, a_min, a_max, out=None):
    pass


def compound_bprop_lut(self, nin, inputs, error, *args):
    pass


def compound_dot(self, A, B, C, alpha=None, beta=None, relu=None):
    pass


def conv_layer(self, dtype, N, C, K, D=None, H=None, W=None, T=None, R=None, *args):
    pass


def deconv_layer(self, dtype, N, C, K, P, Q, R=None, S=None, *args):
    pass


def empty_like(self, other_ary, name=None, persist_values=None):
    pass


def end(self, block, identifier):
    pass


def exp2(self, a, out=None):
    pass


def fabs(self, a, out=None):
    pass


def finite(self, a, out=None):
    pass


def fprop_conv(self, layer, I, F, O, alpha=None, relu=None, repeat=None):
    pass


def fprop_pool(self, layer, I, O):
    pass


def gen_rng(self, seed=None):
    pass


def log2(self, a, out=None):
    pass


def make_binary_mask(self, out, keepthresh=None):
    pass


def max(self, axis=None, out=None, keepdims=None):
    pass


def min(self, a, axis=None, out=None, keepdims=None):
    pass


def onehot(self, indices, axis, out=None):
    pass


def output_dim(self, X, S, padding, strides, pooling=None):
    pass


def pool_layer(self, dtype, op, N, C, D=None, H=None, W=None, J=None, T=None, *args):
    pass


def revert_tensor(self, tensor):
    pass


def rng_get_state(self, state):
    pass


def rng_reset(self):
    pass


def rng_set_state(self, state):
    pass


def safelog(a, out=None):
    pass


def set_caffe_compat(self):
    pass


def sig2(self, a, out=None):
    pass


def std(self, a, axis=None, partial=None, out=None, keepdims=None):
    pass


def take(self, a, indices, axis, out=None):
    pass


def tanh2(self, a, out=None):
    pass


def true_divide(self, a, b, out=None):
    pass


def update_conv(self, layer, I, E, grad_F, alpha=None, repeat=None):
    pass


def update_fc_bias(self, err, out):
    pass


def var(self, a, axis=None, partial=None, out=None, keepdims=None):
    pass


def zeros_like(self, other_ary, name=None, persist_values=None):
    pass
