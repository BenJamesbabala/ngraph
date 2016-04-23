import numpy as np
from geon.backends.graph.names import NameableValue, union_axes

from geon.backends.graph.errors import *


class ParamTypeFactory(object):
    def __init__(self, type_constructor):
        self.type_constructor = type_constructor

    def __getitem__(self, args):
        if not isinstance(args, tuple):
            args = tuple((args,))
        return self.type_constructor(*args)


class GraphType(object):
    def is_subtype_of(self, supertype):
        return self == supertype


class AxesType(object):
    def __init__(self, **kargs):
        super(AxesType, self).__init__(**kargs)


class DType(NameableValue):
    def __init__(self, name=None, dtype=np.float32, **kargs):
        super(DType, self).__init__(**kargs)
        self.dtype = np.dtype(dtype)

    @staticmethod
    def froma(o):
        if isinstance(o, type):
            o = np.dtype(o)
        if isinstance(o, DType):
            return o
        if isinstance(o, np.dtype):
            return DType(dtype=o)
        if o is None:
            return DType()
        raise IncompatibleTypesError()

    def __repr__(self):
        return '{name}DType[{dtype}]'.format(name=self.name or "", dtype=self.dtype.name)


class CallableType(GraphType):
    def __init__(self, args, out, **kargs):
        super(CallableType, self).__init__(**kargs)
        self.args = args
        self.out = out

    def __repr__(self):
        return 'Callable[{args},{out}]'.format(args=self.args, out=self.out)


def elementwise_function_type(n):
    A = Array[(Axis(name='I'),), DType(name='dtype')]
    return Callable[[A]*n, A]


class ArrayType(GraphType, AxesType):
    def __init__(self, axes, dtype=None):
        self.axes = axes
        self.dtype = DType.froma(dtype)

    def is_subtype_of(self, supertype):
        if not isinstance(supertype, ArrayType):
            return False
        return self.axes == supertype.axes and self.dtype == supertype.dtype

    def array_args(self):
        return dict(axes=self.axes, dtype=self.dtype)

    def __repr__(self):
        return 'Array[{axes}, {dtype}]'.format(axes=self.axes, dtype=self.dtype)


class TupleType(GraphType, AxesType):
    def __init__(self, *types):
        self.types = types
        self.axes = ()
        if len(types) > 1:
            first, = types
            if isinstance(first, AxesType):
                self.axes = first.axes


class VoidType(GraphType):
    pass


Callable = ParamTypeFactory(CallableType)
Array = ParamTypeFactory(ArrayType)
Tuple = ParamTypeFactory(TupleType)
Void = VoidType()

def graph_shape(graph_type):
    if isinstance(graph_type, ArrayType):
        return graph_type.shape
    return ()

def graph_axes(graph_type):
    if isinstance(graph_type, ArrayType):
        return graph_type.axes
    return ()

def elementwise_shape(*axes_list):

    n = max((len(shape) for shape in axes_list))

    def prepend(s):
        return tuple(1 for x in xrange(n-len(s)))+s

    axes_list = (prepend(s) for s in axes_list)

    def broadcast(*vals):
        result = 1
        for val in vals:
            if val == 1:
                continue
            elif result == 1 or val == result:
                result = val
            else:
                raise IncompatibleShapesError()
        return result

    return tuple(broadcast(*d) for d in zip(*shapes))


def argument_dtype(dtype, *args):
    return np.result_type(dtype, *(arg.dtype for arg in args))


def elementwise_graph_type(dtype, *graph_types):
    shapes = (graph_axes(graph_type) for graph_type in graph_types)
    axes = union_axes(shapes)
    dtype = np.result_type(dtype, *(graph_type.dtype for graph_type in graph_types))

    return Array[axes, dtype]

def graph_type(o):
    if isinstance(o, np.ndarray):
        return Array[o.shape, o.dtype]
    if isinstance(o, tuple):
        return Tuple(*(graph_type(e) for e in o))
    return np.dtype(type(o))



