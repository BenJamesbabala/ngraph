from contextlib import contextmanager
import weakref
import numbers

import numpy as np

from geon.backends.graph.names import AxisGenerator, NameableValue, VariableBlock
import geon.backends.graph.typing as typing
from geon.backends.graph.errors import *
from geon.backends.graph.environment import get_default_graph, set_default_graph, bound_graph, Environment, get_current_environment
from geon.backends.graph.names import Naming


def find_axes_in_axes(subaxes, axes):
    subaxes = list(subaxes)
    axes = list(axes)
    if not subaxes:
        return 0
    head = subaxes[0]
    for i, axis in enumerate(axes):
        if head is axis and axes[i:i+len(subaxes)] == subaxes:
            return i
    return -1

def axes_sub(x, y):
    """Returns x with elements from y removed"""
    return [_ for _ in x if _ not in y]


def axes_intersect(x, y):
    """Returns intersection of x and y in x order"""
    return [_ for _ in x if _ in y]


def axes_append(*axes_list):
    """Returns x followed by elements of y not in x"""
    result = []
    for axes in axes_list:
        for axis in axes:
            if axis not in result:
                result.append(axis)
    return result


def axes_replace(axes, replace, replacements):
    """Returns axes with those axes in replace replace by those in replacements"""
    r = dict()
    for k in axes:
        r[k] = k
    for k,v in zip(replace, replacements):
        r[k] = v
    return [r[axis] for axis in axes]


def axes_reshape(in_axes, out_axes):
    """
    Compute the reshape shape to broadcase in to out.  Axes must be consistently ordered

    :param in_axes: Axes of the input
    :param out_axes: Axes of the output
    :return: shape argument for reshape()
    """
    result = []
    for out_axis in out_axes:
        if out_axis in in_axes:
            result.append(out_axis.size())
        else:
            result.append(1)
    return tuple(result)


def merge_axes(x, y):
    """Combine x and y into order-preserving x-y, x&y, y-x"""
    return axes_sub(x, y), axes_intersect(x, y), axes_sub(y, x)


def union_axes(axes_list):
    allaxes = []
    for ax in sum(axes_list, ()):
        if ax not in allaxes:
            allaxes.append(ax)
    return tuple(allaxes)


def axes_list(axes, shape_list):
    result = []
    for shape in shape_list:
        for axis, size in zip(axes, shape):
            axis[size]
        result.append(axes)
        axes = [axis.prime() for axis in axes]
    return result


class AxesComp(object):
    """A Computation for computing axes"""

    @staticmethod
    def as_axes(axes):
        if isinstance(axes, AxesComp):
            return axes
        return LiteralAxesComp(axes)

    def resolve(self, environment):
        raise NotImplementedError()

    def __add__(self, x):
        return AxesAppendComp(self, AxesComp.as_axes(x))

    def __radd__(self, x):
        return AxesAppendComp(AxesComp.as_axes(x), self)

    def __sub__(self, x):
        return AxesSubComp(self, AxesComp.as_axes(x))

    def __rsub__(self, x):
        return AxesSubComp(AxesComp.as_axes(x), self)

    def __mul__(self, x):
        return AxesIntersectComp(self, AxesComp.as_axes(x))

    def __rmul__(self, x):
        return AxesIntersectComp(AxesComp.as_axes(x), self)


class LiteralAxesComp(AxesComp):
    """Actual axes are provided"""
    def __init__(self, axes):
        self.axes = axes

    def resolve(self, environment):
        return self.axes


class ValueAxesComp(AxesComp):
    """Determine axes from value computed by x"""
    def __init__(self, x):
        self.x = x

    def resolve(self, environment):
        return environment.get_cached_node_axes(self.x)


class AxesSubComp(AxesComp):
    """Result will be removal of axes in y from those in x"""
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def resolve(self, environment):
        x_axes = self.x.resolve(environment)
        y_axes = self.y.resolve(environment)
        return axes_sub(x_axes, y_axes)


class AxesIntersectComp(AxesComp):
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def resolve(self, environment):
        x_axes = self.x.resolve(environment)
        y_axes = self.y.resolve(environment)
        return axes_intersect(x_axes, y_axes)


class AxesAppendComp(AxesComp):
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def resolve(self, environment):
        x_axes = self.x.resolve(environment)
        y_axes = self.y.resolve(environment)
        return axes_append(x_axes, y_axes)


class AxesEnvironment(AxesComp):
    def __init__(self, node):
        self.node = node

    def resolve(self, environment):
        return environment.get_node_axes(self.node)


class Op(NameableValue):
    """Any operation that can be in an AST"""

    def __init__(self, **kwds):
        graph = get_default_graph()
        self._graph_ref = weakref.ref(graph)
        self._context_ref = weakref.ref(graph.context)
        self.predecessors = weakref.WeakSet()
        self._adjoints = None
        super(Op, self).__init__(**kwds)

    @property
    def graph(self):
        return self._graph_ref()

    @property
    def context(self):
        return self._context_ref()

    @property
    def inputs(self):
       return ()

    @staticmethod
    def get_ordered_ops(op, ordered_ops, outputs):
        """
        Get dependent ops ordered for autodiff.
        """
        if op not in ordered_ops:
            if isinstance(op, ArgsOp):
                for arg in op.inputs:
                    Op.get_ordered_ops(arg, ordered_ops, outputs)
                output = op.output
                if outputs and output is not None and op is not output:
                    Op.get_ordered_ops(op.output, ordered_ops, outputs)
            ordered_ops.append(op)

    @property
    def adjoints(self):
        if self._adjoints is not None:
            return self._adjoints

        self._adjoints = weakref.WeakKeyDictionary()
        ordered_ops = []
        Op.get_ordered_ops(self, ordered_ops, False)
        self._adjoints[self] = ones(axes=self.axes)
        for o in reversed(ordered_ops):
            o.generate_adjoints(self._adjoints, self._adjoints[o], *o.inputs)
        return self._adjoints

    @staticmethod
    def ordered_ops(results, outputs):
        ordered_ops = []
        for result in results:
            Op.get_ordered_ops(result, ordered_ops, outputs)
        return ordered_ops

    @staticmethod
    def analyze_liveness(results, ordered_ops):
        liveness = [set() for _ in ordered_ops]
        i = len(liveness) - 1
        for result in results:
            liveness[i].add(result.output)
        while i > 0:
            op = ordered_ops[i]
            prealive = liveness[i - 1]
            alive = set(liveness[i])
            if isinstance(op, ValueOp):
                output = op.output
                alive.discard(output)
                for arg in op.inputs:
                    alive.add(arg.output)
                prealive |= alive
            i = i - 1
        return liveness

    @staticmethod
    def as_op(x):
        if isinstance(x, ValueOp):
            return x

        return Constant(x)

    @property
    def ops(self):
        return []

    def __str__(self):
        return '<{cl}:{id}>'.format(cl=self.__class__.__name__, id=id(self))


class ControlOp(Op):
    def __init__(self, **kargs):
        super(ControlOp, self).__init__(**kargs)


class RandomStateOp(Op):
    def __init__(self, seed=None, **kargs):
        super(RandomStateOp, self).__init__(**kargs)
        self.seed = seed


class ValueOp(Op):

    def __init__(self, graph_type=None, **kwds):
        super(ValueOp, self).__init__(**kwds)
        self.graph_type = graph_type

        # Ops that directly use the result
        self.users = weakref.WeakSet()  # Name assigned by user

    @property
    def output(self):
        return self

    @property
    def axes(self):
        return ValueAxesComp(self)

    def resolved_axes(self, environment):
        return environment.get_node_axes(self)

    def generate_add_delta(self, adjoints, delta):
        if self not in adjoints:
            adjoints[self] = delta
        else:
            adjoints[self] = delta + adjoints[self]

    def reshape(self, shape):
        return reshape(self, shape)

    # Magic methods for builtin operations we want to use for creating nodes
    def __neg__(self):
        return negative(self)

    def __pos__(self):
        return self

    def __abs__(self):
        return absolute(self)

    def __add__(self, val):
        return add(self, val)

    def __radd__(self, val):
        return add(val, self)

    def __sub__(self, val):
        return subtract(self, val)

    def __rsub__(self, val):
        return subtract(val, self)

    def __mul__(self, val):
        return multiply(self, val)

    def __rmul__(self, val):
        return multiply(val, self)

    def __div__(self, val):
        return divide(self, val)

    def __rdiv__(self, val):
        return divide(val, self)

    def __pow__(self, val):
        return Pow(self, val)

    def __rpow__(self, val):
        return Pow(val, self)

    @property
    def T(self):
        return transpose(self)


class ArgsOp(Op):

    def __init__(self, args, **kargs):
        super(ArgsOp, self).__init__(**kargs)
        self.__args = tuple(Op.as_op(arg) for arg in args)

        for arg in self.inputs:
            arg.users.add(self)

    @property
    def inputs(self):
        return self.__args

    def add_dependencies(self):
        super(ArgsOp, self).add_dependencies()
        for arg in self.inputs:
            arg.users.add(self)


class ComputationOp(ArgsOp, ValueOp):
    """
    An TensorOp is the result of some sort of operation.
    """
    def __init__(self, **kargs):
        super(ComputationOp, self).__init__(**kargs)

    def compute_graph_type(self, *argtypes):
        raise NotImplementedError()

    def add_dependencies(self):
        self.output.users.add(self)

    @property
    def output(self):
        return self.__out

    @output.setter
    def output(self, value):
        self.__out = value
        if value is not self:
            value.users.add(self)


class OutputArgOp(ComputationOp):
    """
    An OutputArgOp has an out= argument for its result.
    """

    def __init__(self, out=None, **kargs):
        super(OutputArgOp, self).__init__(**kargs)
        if out is None:
            out = empty(axes=self.axes)
        self.output = out


class ElementWise(OutputArgOp):
    def __init__(self, **kargs):
        super(ElementWise, self).__init__(**kargs)

    @property
    def axes(self):
        inputs = self.inputs
        result = self.inputs[0].axes
        for input in inputs[1:]:
            result = AxesAppendComp(result, input.axes)
        return result


class AllocationOp(ValueOp):
    def __init__(self, axes=None, dtype=None, **kargs):
        super(AllocationOp, self).__init__(graph_type=typing.Array[AxesComp.as_axes(axes), dtype], **kargs)
        self.aliases = weakref.WeakSet()

    @property
    def axes(self):
        return self.graph_type.axes


class AliasOp(ArgsOp, AllocationOp):
    """
    Allocates a descriptor that aliases another allocation.
    """
    def __init__(self, axes, aliased, **kargs):
        super(AliasOp, self).__init__(axes=axes, dtype=aliased.graph_type.dtype, args=(aliased,), **kargs)
        aliased.output.aliases.add(self)

    @property
    def aliased(self):
        return self.inputs[0]


class input(AllocationOp):
    """
    Can be set externally.
    """
    def __init__(self, **kargs):
        super(input, self).__init__(**kargs)

    def evaluate(self, evaluator):
        return evaluator.input(self.name, axes=self.resolved_axes(evaluator.environment), dtype=self.graph_type.dtype)

    def generate_adjoints(self, tape, delta):
        pass

    @property
    def axes(self):
        return AxesEnvironment(self)


class Constant(AllocationOp):
    """
    A constant that appears in a graph.
    """
    def __init__(self, const, **kargs):
        if isinstance(const, np.ndarray):
            # TODO: Figure out what to do for axes here
            super(Constant, self).__init__(shape=const.shape, dtype=const.dtype, **kargs)
        else:
            super(Constant, self).__init__(axes=(), dtype=np.dtype(type(const)), **kargs)
        self.const = const

    def evaluate(self, evaluator):
        return evaluator.constant(self.const, axes=self.resolved_axes(evaluator.environment), dtype=self.graph_type.dtype)

    def generate_adjoints(self, tape, delta):
        pass

    def __str__(self):
        return '<{cl} ({const})>'.format(cl=self.__class__.__name__, const=self.const)


class absolute(ElementWise):
    def __init__(self, x, out=None):
        super(absolute, self).__init__(out=out, args=(x,))

    def evaluate(self, evaluator, out, x):
        return evaluator.absolute(x, out)

    def generate_adjoints(self, adjoints, delta, x):
        x.generate_add_delta(adjoints, sig(x)*delta)


class add(ElementWise):
    def __init__(self, x, y, out=None):
        super(add, self).__init__(out=out, args=(x, y))

    def evaluate(self, evaluator, out, x, y):
        return evaluator.add(x, y, out)

    def generate_adjoints(self, adjoints, delta, x, y):
        x.generate_add_delta(adjoints, delta)
        y.generate_add_delta(adjoints, delta)


class cos(ElementWise):
    def __init__(self, x, out=None):
        super(cos, self).__init__(out=out, args=(x,))

    def generate_adjoints(self, adjoints, delta, x):
        x.generate_add_delta(adjoints, delta*sin(x))

    def evaluate(self, evaluator, out, x):
        return evaluator.cos(x, out)


# This makes the derivative simpler if we need it
def divide(x, y, out=None):
    result = multiply(x, reciprocal(y), out=out)
    return result


class dot(OutputArgOp):
    def __init__(self, x, y):
        super(dot, self).__init__(args=(x, y))

    def evaluate(self, evaluator, out, x, y):
        xarg, yarg = self.inputs
        int_axes_comp = AxesIntersectComp(xarg.axes, yarg.axes)
        int_axes = int_axes_comp.resolve(evaluator.environment)
        return evaluator.dot(x, y, int_axes, out)

    @property
    def axes(self):
        x, y = self.inputs
        x_axes = x.axes
        y_axes = y.axes
        return AxesAppendComp(AxesSubComp(x_axes, y_axes), AxesSubComp(y_axes, x_axes))

    def generate_adjoints(self, adjoints, delta, x, y):
        x.generate_add_delta(adjoints, dot(delta, y))
        y.generate_add_delta(adjoints, dot(x, delta))


class empty(AllocationOp):
    def __init__(self, **kargs):
        super(empty, self).__init__(**kargs)

    def generate_adjoints(self, adjoints, delta):
        pass

    def evaluate(self, evaluator):
        return evaluator.empty(axes=self.resolved_axes(evaluator.environment), dtype=self.graph_type.dtype)


class Parameter(AllocationOp):
    def __init__(self, init, **kargs):
        super(Parameter, self).__init__(**kargs)
        self.init = init

    def generate_adjoints(self, adjoints, delta):
        pass

    def evaluate(self, evaluator):
        return evaluator.empty(axes=self.resolved_axes(evaluator.environment), dtype=self.graph_type.dtype)



class exp(ElementWise):
    def __init__(self, x, out=None):
        super(exp, self).__init__(out=out, args=(x,))

    def generate_adjoints(self, adjoints, delta, x):
        x.generate_add_delta(adjoints, delta)

    def evaluate(self, evaluator, out, x):
        return evaluator.exp(x, out)


class log(ElementWise):
    def __init__(self, x, out=None):
        super(log, self).__init__(out=out, args=(x,))

    def generate_adjoints(self, adjoints, delta, x):
        x.generate_add_delta(adjoints, delta/x)

    def evaluate(self, evaluator, out, x):
        return evaluator.log(x, out)


class maximum(ElementWise):
    def __init__(self, x, y, out=None):
        super(maximum, self).__init__(out=out, args=(x, y))

    def evaluate(self, evaluator, out, x, y):
        return evaluator.maximum(x, y, out=out)

    def generate_adjoints(self, adjoints, delta, x, y):
        p, n = posneg(x-y)
        x.generate_add_delta(delta*p)
        y.generate_add_delta(delta*n)


class minimum(ElementWise):
    def __init__(self, x, y, out=None):
        super(minimum, self).__init__(out=out, args=(x, y))

    def evaluate(self, evaluator, out, x, y):
        return evaluator.minimum(x, y, out=out)

    def generate_adjoints(self, adjoints, delta, x, y):
        p, n = posneg(y-x)
        x.generate_add_delta(delta*p)
        y.generate_add_delta(delta*n)


class multiply(ElementWise):
    def __init__(self, x, y, out=None):
        super(multiply, self).__init__(out=out, args=(x, y))

    def generate_adjoints(self, adjoints, delta, x, y):
        x.generate_add_delta(adjoints, delta*y)
        y.generate_add_delta(adjoints, x*delta)


    def evaluate(self, evaluator, out, x, y):
        return evaluator.multiply(x, y, out)


class negative(ElementWise):
    def __init__(self, x, out=None):
        super(negative, self).__init__(out=out, args=(x,))

    def generate_adjoints(self, adjoints, delta, x):
        x.generate_add_delta(adjoints, -delta)

    def evaluate(self, evaluator, out, x):
        return evaluator.negative(x, out)


class ones(AllocationOp):
    def __init__(self, **kargs):
        super(ones, self).__init__(**kargs)

    def generate_adjoints(self, adjoints, delta):
        pass

    def evaluate(self, evaluator):
        return evaluator.ones(axes=self.resolved_axes(evaluator.environment), dtype=self.graph_type.dtype)


class reciprocal(ElementWise):
    def __init__(self, x, out=None):
        super(reciprocal, self).__init__(out=out, args=(x,))

    def generate_adjoints(self, adjoints, delta, x):
        x.generate_add_delta(adjoints, -self*self*delta)

    def evaluate(self, evaluator, out, x):
        return evaluator.reciprocal(x, out)


#TODO This should be restride, as should transpose, is terms of (i,j,k) -> ((i,j),k) i.e. remap
class reshape(AliasOp):
    def __init__(self, x, shape):
        super(reshape, self).__init__(shape=shape, aliased=x)

    def generate_adjoints(self, adjoints, delta, x):
        x.generate_add_delta(adjoints, reshape(delta, x.graph_type.shape))

    def evaluate(self, evaluator, x):
        return evaluator.reshape(x, self.graph_type.shape)


class sgn(ElementWise):
    def __init__(self, x, out=None):
        super(sgn, self).__init__(out=out, args=(x,))

    def generate_adjoints(self, adjoints, delta, x):
        # Zero
        pass

    def evaluate(self, evaluator, out, x):
        return evaluator.sign(x, out)


class sig(ElementWise):
    def __init__(self, x, out=None):
        super(sig, self).__init__(out=out, args=(x,))

    def generate_adjoints(self, adjoints, delta, x):
        x.generate_add_delta(adjoints, delta*self*(1.0-self))

    def evaluate(self, evaluator, out, x):
        return evaluator.sig(x, out)

class sin(ElementWise):
    def __init__(self, x, out=None):
        super(sin, self).__init__(out=out, args=(x,))

    def generate_adjoints(self, adjoints, delta, x):
        x.generate_add_delta(adjoints, delta*cos(x))

    def evaluate(self, evaluator, out, x):
        return evaluator.sin(x, out)


class sqrt(ElementWise):
    def __init__(self, x, out=None):
        super(sqrt, self).__init__(out=out, args=(x,))

    def generate_adjoints(self, adjoints, delta, x):
        x.generate_add_delta(adjoints, .5*delta*self)

    def evaluate(self, evaluator, out, x):
        return evaluator.sqrt(x, out)


class square(ElementWise):
    def __init__(self, x, out=None):
        super(square, self).__init__(out=out, args=(x,))

    def generate_adjoints(self, adjoints, delta, x):
        x.generate_add_delta(adjoints, 2.0*delta*x)

    def evaluate(self, evaluator, out, x):
        return evaluator.square(x, out)


class subtract(ElementWise):
    def __init__(self, x, y, out=None):
        super(subtract, self).__init__(out=out, args=(x, y))

    def generate_adjoints(self, adjoints, delta, x, y):
        x.generate_add_delta(adjoints, delta)
        y.generate_add_delta(adjoints, -delta)

    def evaluate(self, evaluator, out, x, y):
        return evaluator.subtract(x, y, out)


class tanh(ElementWise):
    def __init__(self, x, out=None):
        super(tanh, self).__init__(out=out, args=(x,))

    def generate_adjoints(self, adjoints, delta, x):
        x.generate_add_delta(adjoints, delta*(1.0-self*self))

    def evaluate(self, evaluator, out, x):
        return evaluator.tanh(x, out)


class transpose(AliasOp):
    def __init__(self, x):
        super(transpose, self).__init__(axes=tuple(reversed(x.graph_type.axes)), aliased=x)

    def evaluate(self, evaluator, out, x):
        return evaluator.transpose(x)

    def generate_adjoints(self, adjoints, delta, x):
        x.generate_add_delta(adjoints, delta.T)


class zeros(AllocationOp):
    def __init__(self, **kargs):
        super(zeros, self).__init__(**kargs)

    def generate_adjoints(self, adjoints, delta):
        pass

    def evaluate(self, evaluator):
        return evaluator.zeros(axes=self.resolved_axes(evaluator.environment), dtype=self.graph_type.dtype)


class range(ValueOp):
    def __init__(self, start, stop=None, step=1, **kargs):
        super(self, range).__init__(**kargs)
        if stop is None:
            start = 0
            stop = start
        super(range, self).__init__(args=(start, stop, step))


def deriv(dep, indep):
    return dep.adjoints[indep]

