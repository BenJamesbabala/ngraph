import numpy as np

from geon.backends.graph.errors import IncompatibleShapesError
from geon.backends.graph.arrayaxes import axes_sub
import pycuda.gpuarray as gpuarray
import pycuda.cumath as cumath
import geon.backends.graph.cudagpu as cudagpu
import geon.backends.graph.ast as ast
from geon.backends.graph.arrayaxes import find_axes_in_axes, reaxe, reaxe_like, tensor_axes, get_batch_axes, set_batch_axes
import geon.backends.graph.arrayaxes as arrayaxes
from geon.backends.graph.environment import get_current_environment, get_current_ops, captured_ops


def axes_shape(axes):
    return tuple(axis.length for axis in axes)


class Evaluator(object):
    def __init__(self, results, error=None, initialize=False, environment=None, **kvargs):
        super(Evaluator, self).__init__(**kvargs)
        if environment is None:
            environment = get_current_environment()
        self.environment = environment
        self.results = results

        self.ops = ast.Op.ordered_ops(self.results)
        self.compute_initializations(self.ops)
        self.compute_allocations()

        self.opids = dict()
        for op in self.initialization_ops:
            self.opids[op] = len(self.opids)
        for op in self.ops:
            self.opids[op] = len(self.opids)

    def compute_initializations(self, ops):
        initializers = []
        initialized_ops = set()
        with captured_ops(initializers):
            uninitialized_ops = ops
            while uninitialized_ops:
                for op in uninitialized_ops:
                    if op in initialized_ops:
                        continue
                    initialized_ops.add(op)
                    op.tensor_axes_info.generate_initializations(op)

                uninitialized_ops = ast.Op.ordered_ops(initializers)
                uninitialized_ops = [op for op in uninitialized_ops if op not in initialized_ops]

        self.initialization_ops = ast.Op.ordered_ops(initializers)
        for op in ops:
            op.call_info

    def compute_allocations(self):
        ops = set(self.initialization_ops)
        ops.update(self.ops)
        for op in ops:
            op.tensor_axes_info.allocate(self)

    def initialize(self):
        self.evaluate_ops(self.initialization_ops)

    def evaluate_ops(self, ops):
        for op in ops:
            op.sync(self)

        for op in ops:
            op.evaluate_call_info(self, *op.call_info)

    def evaluate(self):
        self.evaluate_ops(self.ops)
        r = {}
        for op in self.results:
            r[op] = self.value(op)
        return r

    def value(self, op):
        return op.tensor_axes_info.tensor_description.value

    def set_value(self, op, tensor):
        tensor_description = op.tensor_axes_info.tensor_description
        tensor_description.value = tensor
        for td in tensor_description.views:
            td.value = self.tensor_view(td)


class NumPyEvaluator(Evaluator):
    def __init__(self, **kargs):
        super(NumPyEvaluator, self).__init__(**kargs)

    # allocators
    def empty(self, tensor_description):
        return np.empty(tensor_description.sizes, tensor_description.dtype)

    def tensor_view(self, tensor_description):
        return np.ndarray(shape=tensor_description.shape, dtype=tensor_description.dtype, buffer=tensor_description.buffer.value,
                          offset=tensor_description.offset, strides=tensor_description.strides)

    def ones(self, tensor_allocation_info):
        return np.ones(tensor_allocation_info.sizes, tensor_allocation_info.dtype)

    def zeros(self, tensor_allocation_info):
        return np.zeros(tensor_allocation_info.sizes, tensor_allocation_info.dtype)

    def constant(self, value, out):
        if isinstance(out, np.ndarray):
            out.fill(value)
        else:
            return value

    # Operations
    def trace(self, x, label, out):
        oa = out
        xa = x
        if oa.shape == ():
            oa = oa.reshape((1,))
            xa = xa.reshape((1,))
        oa[:] = xa

    def rng(self, seed=None):
        return np.random.RandomState(seed=seed)

    def rng_uniform(self, rng, low, high, out):
        out[:] = rng.uniform(low, high, out.shape)

    def set_item(self, array, item, value):
        array.__setitem__(item, value)

    def fill(self, out, value):
        out.fill(value)

    def absolute(self, x, out):
        np.abs(x, out=out)

    def argmax(self, x, out):
        np.ndarray.argmax(x, 0, out)

    def argmin(self, x, out):
        np.ndarray.argmin(x, 0, out)

    def add(self, x, y, out):
        np.add(x, y, out=out)

    def cos(self, x, out):
        np.cos(x, out=out)

    def divide(self, x, y, out):
        np.divide(x, y, out=out)

    def dot(self, x, y, out):
        np.dot(x, y, out)

    def update(self, params, delta):
        if params.shape != delta.shape:
            print('mismatch', tensor_axes(params), tensor_axes(delta))
        np.subtract(params, delta, out=params)

    def equal(self, x, y, out):
        return np.equal(x, y, out=out)

    def exp(self, x, out):
        np.exp(x, out=out)

    def greater(self, x, y, out):
        np.greater(x, y, out=out)

    def greater_equal(self, x, y, out):
        np.greater_equal(x, y, out=out)

    def less(self, x, y, out):
        np.less(x, y, out=out)

    def less_equal(self, x, y, out):
        np.less_equal(x, y, out=out)

    def log(self, x, out):
        np.log(x, out=out)

    expm50 = np.exp(-50.)
    def safelog(self, x, out):
        np.maximum(x, NumPyEvaluator.expm50, out)
        np.log(out, out)

    def max(self, x, axis, out):
        np.max(x, axis, out=out)

    def maximum(self, x, y, out):
        np.maximum(x, y, out=out)

    def minimum(self, x, y, out):
        np.minimum(x, y, out=out)

    def multiply(self, x, y, out):
        np.multiply(x, y, out=out)

    def negative(self, x, out):
        np.negative(x, out=out)

    def not_equal(self, x, y, out):
        np.not_equal(x, y, out=out)

    def reciprocal(self, x, out):
        np.reciprocal(x, out=out)

    def sig(self, x, out):
        np.negative(x, out)
        np.exp(out, out)
        np.add(out, 1.0, out)
        np.reciprocal(out, out)

    def sign(self, x, out):
        np.sign(x, out=out)

    def sin(self, x, out):
        np.sin(x, out=out)

    def sqrt(self, x, out):
        np.sqrt(reaxe_like(x, out, True), out=out)

    def square(self, x, out):
        np.square(x, out=out)

    def subtract(self, x, y, out):
        np.subtract(x, y, out=out)

    def copy(self, x, out):
        out[()] = x[()]

    def sum(self, x, axis, out):
        np.sum(x, axis=axis, out=out)

    def tanh(self, x, out):
        np.tanh(x, out=out)

    def uniform(self, x, low, high):
        u = self.rng.uniform(low, high, x.shape)
        x[:] = u


class PyCUDAEvaluator(Evaluator):
    """
    Uses PuCUDA to evaluate.  Not fully tested; PyCUDA does not expose all the NumPy API.
    """
    def __init__(self, **kvargs):
        super(PyCUDAEvaluator, self).__init__(**kvargs)

    def evaluate(self, **kvargs):
        with cudagpu.cuda_device_context():
            return super(PyCUDAEvaluator, self).evaluate(**kvargs)

    def constant(self, value, axes, dtype):
        return value

    def absolute(self, x, out):
        cumath.fabs(reaxe_like(x, out, True), out=out)
        return out

    def add(self, x, y, out):
        reaxe_like(x, out, True)._axpbyz(1, reaxe_like(y, out, True), 1, out)
        return out

    def cos(self, x, out):
        cumath.cos(reaxe_like(x, out, True), out=out)
        return out

    def dot(self, x, y, int_axes, out):
        # TODO Implement axis dot
        cumath.dot(x, y, out=out)
        return out

    def empty(self, axes, dtype):
        return cumath.empty(axes, dtype)

    def exp(self, x, out):
        cumath.exp(reaxe_like(x, out, True), out=out)
        return out

    def log(self, x, out):
        cumath.log(reaxe_like(x, out, True), out=out)
        return out

    def maximum(self, x, y, out):
        cumath.maximum(reaxe_like(x, out, True), reaxe_like(y, out, True), out=out)
        return out

    def minimum(self, x, y, out):
        cumath.minimum(reaxe_like(x, out, True), reaxe_like(y, out, True), out=out)
        return out

    def multiply(self, xa, ya, out):
        x = reaxe_like(xa, out, True)
        y = reaxe_like(ya, out, True)
        if isinstance(x, gpuarray.GPUArray):
            if isinstance(y, gpuarray.GPUArray):
                x._elwise_multiply(y, out=out)
                return out
            x._axpbz(y, 0, out)
        elif isinstance(y, gpuarray.GPUArray):
            y._axpbz(x, 0, out)
            return out
        else:
            return x*y

    def negative(self, x, out):
        reaxe_like(x, out, True)._axpbz(-1, 0.0, out)
        return out

    def ones(self, axes, dtype):
        result = gpuarray.empty(axes_shape(axes), dtype)
        result.fill(1.0)
        return result

    def reciprocal(self, x, out):
        reaxe_like(x, out, True)._rdiv_scalar(1.0, out)
        return out

    def reshape(self, x, shape):
        return x.reshape(shape)

    def sig(self, x, out):
        self.negative(x, out=out)
        cumath.exp(out, out=out)
        # Add one
        out._axpbz(1.0, 1.0, out=out)
        out._rdiv_scalar(1.0, out=out)
        return out

    def sign(self, x, out):
        out.set(np.sign(reaxe_like(x, out, True).get()))
        return out

    def sin(self, x, out):
        cumath.sin(reaxe_like(x, out, True), out=out)
        return out

    def sqrt(self, x, out):
        cumath.sqrt(reaxe_like(x, out, True), out=out)
        return out

    def square(self, x, out):
        return self.multiply(reaxe_like(x, out, True), reaxe_like(x, out, True), out)

    def subtract(self, x, y, out):
        reaxe_like(x, out, True)._axpbyz(1, reaxe_like(y, out, True), 1, out)
        return out

    def tanh(self, x, out):
        cumath.tanh(reaxe_like(x, out, True), out=out)
        return out

    def zeros(self, axes, dtype):
        return gpuarray.zeros(axes_shape(axes), dtype)


class GenNumPy(Evaluator):

    def __init__(self, **kvargs):
        super(GenNumPy, self).__init__(**kvargs)

    def evaluate(self, **kvargs):
        liveness = ast.Op.analyze_liveness(self.results, self.ops)

        def varname(op):
            try:
                return 't%d' % self.opids[op]
            except KeyError:
                return "Error on "+str(op)

        body = []
        vals = {}
        for i, op in enumerate(self.ops):
            live = [varname(l) for l in liveness[i]]
            args = [varname(arg) for arg in op.inputs]
            val = '{var} = {val} # Live={live}'.format(val=op.evaluate(self, varname(op), *args), var=varname(op), live=live)
            vals[op] = val
            body.append(val)
        for line in body:
            print(line)
        return [vals[op] for op in self.results]

    def constant(self, value, axes, dtype):
        return 'constant {dtype} {axes} = {value}'.format(value=value, axes=axes, dtype=dtype)

    def absolute(self, x, out):
        return 'np.abs({x}, out={out})'.format(x=x, out=out)

    def add(self, x, y, out):
        return 'np.add({x}, {y}, out={out})'.format(x=x, y=y, out=out)

    def cos(self, x, out):
        return 'np.cos({x}, out={out})'.format(x=x, out=out)

    def dot(self, x, y, red_axes, out):
        return 'np.dot({x}, {y}, axes={a}, out={out})'.format(x=x, y=y, out=out, a=red_axes)

    def empty(self, axes, dtype):
        return 'np.empty({axes}, np.{dtype})'.format(axes=axes, dtype=dtype)

    def exp(self, x, out):
        return 'np.exp({x}, out={out})'.format(x=x, out=out)

    def log(self, x, out):
        return 'np.log({x}, out={out})'.format(x=x, out=out)

    def maximum(self, x, y, out):
        return 'np.maximum({x}, {y}, out={out})'.format(x=x, y=y, out=out)

    def minimum(self, x, y, out):
        return 'np.minimum({x}, {y}, out={out})'.format(x=x, y=y, out=out)

    def multiply(self, x, y, out):
        return 'np.multiply({x}, {y}, out={out})'.format(x=x, y=y, out=out)

    def negative(self, x, out):
        return 'np.negative({x}, out={out})'.format(x=x, out=out)

    def ones(self, axes, dtype):
        return 'np.ones({axes}, np.{dtype})'.format(axes=axes, dtype=dtype)

    def reciprocal(self, x, out):
        return 'np.reciprocal({x}, out={out})'.format(x=x, out=out)

    def reshape(self, x, shape):
        return '{x}.reshape({shape})'.format(x=x, shape=shape)

    def sig(self, x, out):
        return 'np.negative({x}, {out})\nnp.exp({out}, {out})\\nnp.add({out}, 1.0, {out}nnp.reciprocal({out}, {out})'.format(x=x, out=out)

    def sign(self, x, out):
        return 'np.sign({x}, out={out})'.format(x=x, out=out)

    def sin(self, x, out):
        return 'np.sin({x}, out={out})'.format(x=x, out=out)

    def softmax(self, x, batch_axes, out):
        return 'softmax({x}, batch_axes={batch_axes}, out=out'.format(x=x, batch_axes=batch_axes, out=out)

    def sqrt(self, x, out):
        return 'np.sqrt({x}, out={out})'.format(x=x, out=out)

    def square(self, x, out):
        return 'np.square({x}, out={out})'.format(x=x, out=out)

    def subtract(self, x, y, out):
        return 'np.subtract({x}, {y}, out={out})'.format(x=x, y=y, out=out)

    def sum(self, x, reduction_axes, out):
        return 'np.sum({x},axis={a}, out={out})'.format(x=x, a=reduction_axes, out=out)

    def tanh(self, x, out):
        return 'np.tanh({x}, out={out})'.format(x=x, out=out)

    def transpose(self, x):
        return '{x}.transpose()'.format(x=x)

    def zeros(self, axes, dtype):
        return 'np.zeros({axes}, np.{dtype})'.format(axes=axes,dtype=dtype)


