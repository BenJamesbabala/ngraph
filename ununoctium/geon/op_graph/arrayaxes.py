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
from builtins import object, map, range, zip
from future.utils import with_metaclass
from functools import reduce, wraps

from abc import ABCMeta
import collections
import operator
import types
import weakref

import numpy as np

from geon.op_graph.names import NameableValue


class Axis(with_metaclass(ABCMeta, NameableValue)):
    """
    An Axis of a tensor.

    Tensor operations uses Axis identity to pair/specify dimensions.

    Arguments:
        length: The length of the axis.
        batch: Whether the axis is a batch axis.

    Attributes:
        length: The length of the axis.

    """
    batch_axes = set()

    def __init__(self, length=None, batch=False, **kwargs):
        super(Axis, self).__init__(**kwargs)
        self.__length = length
        self.batch = batch

    def axis_id(self, key):
        """
        TODO.

        Arguments:
          key: TODO

        Returns:

        """
        return AxisID(self, key)

    @property
    def batch(self):
        """
        Whether the axis is a batch axis.
        """
        return self.__batch

    @batch.setter
    def batch(self, value):
        if value:
            Axis.batch_axes.add(self)
        else:
            Axis.batch_axes.discard(self)
        self.__batch = value

    @property
    def length(self):
        """

        :return: The length of the axis.
        """
        return self.__length

    @length.setter
    def length(self, value):
        self.__length = value

    def __repr__(self):
        return 'Axis({name}: {length})'.format(name=self.name, length=self.length)


class NumericAxis(Axis):
    """
    A NumericAxis is an axis which is uniquely identified by its length.

    Every NumericAxis with the same length is the same instance of
    NumericAxis.
    """

    cache = {}

    def __new__(cls, length=None, **kwargs):
        if length in NumericAxis.cache:
            return NumericAxis.cache[length]

        axis = super(NumericAxis, cls).__new__(cls, **kwargs)
        NumericAxis.cache[length] = axis

        return axis

    def __init__(self, length=None, **kwargs):
        super(NumericAxis, self).__init__(length=length, **kwargs)

    def __repr__(self):
        return 'NumericAxis({length})'.format(length=self.length)


class FunctionAxis(Axis):
    """
    A function axis is an axis whose length is computed by a user-supplied function.

     Instances should only be created internally because using a
    function that changes the length after a transformation will result in
    undefined behaviour.
    """
    def __init__(self, length_fun, **kwargs):
        super(FunctionAxis, self).__init__(length=-1, **kwargs)
        self.length_fun = length_fun

    @property
    def length(self):
        return self.length_fun()


def _sliced_length(s, incoming_length):
    start, stop, step = s.indices(incoming_length)

    # max with 0 so we dont ever return a negative length.  This
    # matches how python handles it internally.  Raising an exception
    # might also be reasonable.
    if step == 1:
        return max(stop - start, 0)
    elif step == -1:
        return max(start - stop, 0)
    else:
        _validate_slice(s)


def _validate_slice(s):
    if s.step not in (-1, 1, None):
        raise ValueError((
            'SlicedAxis cant currently handle a step size other '
            'than -1, 1 or None.  Was given {step} in slice {slice}'
        ).format(
            step=s.step,
            slice=s,
        ))


class SlicedAxis(FunctionAxis):
    """
    An axis created by slicing a parent axis.

    The length is computed dynamically from the length of the parent.

    Arguments:
        parent: The axis being sliced.
        s: The slice.
        kwargs: Arguments for related classes.

    TODO: Right now, a 0 length slice is allowed.  Perhaps we want to raise an
    exception instead?
    """
    def __init__(self, parent, s, **kwargs):
        _validate_slice(s)

        super(SlicedAxis, self).__init__(
            length_fun=lambda: _sliced_length(s, parent.length),
            **kwargs
        )


class PaddedAxis(FunctionAxis):
    """
    An axis created by padding a parent axis.

    Arguments:
        parent: The axis being padded.
        pad: A two-element array of pre and post padding.
    """
    def __init__(self, parent, pad, **kwargs):
        def padded_length():
            return parent.length + pad[0] + pad[1]
        super(PaddedAxis, self).__init__(length_fun=padded_length, **kwargs)


class AxisID(object):
    """TODO."""

    def __init__(self, axis, idx, **kwargs):
        assert isinstance(idx, int)
        super(AxisID, self).__init__(**kwargs)
        self.axis = axis
        self.idx = idx

    def __eq__(self, other):
        return isinstance(other, AxisID) \
            and self.axis == other.axis and self.idx == other.idx

    def __hash__(self):
        return hash(self.axis) + hash(self.idx)

    def __repr__(self):
        return '{axis}[{idx}]'.format(axis=self.axis, idx=self.idx)


def no_duplicates(arr):
    """
    TODO.

    Arguments:
      arr: TODO

    Returns:

    """
    s = set()
    for x in enumerate(arr):
        if x in s:
            return False
        s.add(x)
    return True


class Axes(object):
    """TODO."""

    def __init__(self, axes=None):
        if axes is None:
            axes = []
        elif isinstance(axes, Axis):
            axes = [axes]
        elif isinstance(axes, types.GeneratorType):
            axes = tuple(axes)
        elif isinstance(axes, (list, tuple)) and not isinstance(axes, Axes):
            axes = tuple(axes)

        def canonicalize(seq):
            """
            TODO.

            Arguments:
              seq: TODO

            Returns:

            """
            elems = []
            for x in seq:
                if isinstance(x, FlattenedAxis):
                    if x.empty:
                        continue
                    elif x.single:
                        x = x.axes[0]
                elif isinstance(x, collections.Iterable):
                    x = canonicalize(x)
                    if len(x) == 0:
                        continue
                    elif len(x) == 1:
                        x = x[0]
                    else:
                        x = FlattenedAxis(Axes(x))
                elems.append(x)
            return elems

        axes = canonicalize(axes)

        for x in axes:
            if not isinstance(x, Axis):
                raise ValueError((
                    'tried to initialize an Axes with object type '
                    '{found_type}.  all values should be an instance '
                    'of a type which inherits from Axis.'
                ).format(
                    found_type=type(x),
                ))

        self._axes = axes

    @staticmethod
    def as_axes(axes):
        if isinstance(axes, Axes):
            return axes
        elif isinstance(axes, AxisID):
            return axes.as_axes()
        return Axes(axes)

    @property
    def full_lengths(self):
        """TODO."""
        return tuple(x.axes.full_lengths if isinstance(x, FlattenedAxis)
                     else x.length for x in self)

    @property
    def lengths(self):
        """

        :return: The lengths of the axes.
        """
        return tuple(x.length for x in self)

    def batch_axes(self):
        """

        :return: The Axes subset that are batch axes.
        """
        return Axes(axis for axis in self if axis.batch)

    def sample_axes(self):
        """

        :return: The Axes subset that are not batch axes.
        """
        return Axes(axis for axis in self if not axis.batch)

    def __iter__(self):
        return self._axes.__iter__()

    def __len__(self):
        return len(self._axes)

    def __getitem__(self, item):
        if isinstance(item, slice):
            return Axes(self._axes.__getitem__(item))
        else:
            return self._axes.__getitem__(item)

    def __getslice__(self, i, j):
        return self.__getitem__(slice(i, j))

    def __add__(self, other):
        if isinstance(other, Axes):
            other = other.as_axis_ids()
        return (self.as_axis_ids() + other).as_axes()

    def __sub__(self, other):
        if isinstance(other, Axes):
            other = other.as_axis_ids()
        return (self.as_axis_ids() - other).as_axes()

    def __eq__(self, other):
        if not isinstance(other, Axes):
            raise ValueError((
                'other must be of type Axes, found type {}'
            ).format(type(other)))

        return self._axes.__eq__(other._axes)

    def __ne__(self, other):
        return not self == other

    def __nonzero__(self):
        """ Axes considered nonzero if axes are nonzero. """
        return bool(self._axes)

    def concat(self, other):
        """
        TODO.

        Arguments:
          other: TODO

        Returns:

        """
        return Axes(tuple(self) + tuple(other))

    def index(self, axis):
        """
        TODO.

        Arguments:
          axis: TODO

        Returns:

        """
        return self._axes.index(axis)

    # TODO: delete this method, the size should come from the tensor
    @property
    def size(self):
        """TODO."""
        size = 1
        for x in self:
            size *= x.length
        return size

    def as_axis_ids(self):
        """TODO."""
        m = collections.defaultdict(int)
        elems = []

        for x in self:
            index = m[x]
            m[x] = index + 1
            elems.append(AxisID(x, index))

        return AxisIDTuple(*elems)

    def __repr__(self):
        s = 'Axes('
        for x in self:
            s += repr(x) + ','
        s += ')'
        return s


# func(agg, elem) -> agg
def reduce_nested(elem, agg, func):
    """
    TODO.

    Arguments:
      elem: TODO
      agg: TODO
      func: TODO

    Returns:

    """
    if isinstance(elem, collections.Iterable):
        for sub in elem:
            agg = reduce_nested(sub, agg, func)
        return agg
    else:
        return func(agg, elem)


def with_axes_as_axis_ids(f):
    """
    TODO.

    Arguments:
      f: TODO

    Returns:

    """
    @wraps(f)
    def wrapper(*args):
        """
        TODO.

        Arguments:
          *args: TODO

        Returns:

        """
        new_args = []
        for a in args:
            if isinstance(a, Axes):
                a = Axes(a).as_axis_ids()
            new_args.append(a)
        return f(*new_args)
    return wrapper


class AxisIDTuple(tuple):
    """TODO."""

    def __new__(cls, *seq):
        if len(seq) > 0 and isinstance(seq[0], types.GeneratorType):
            assert len(seq) == 1
            seq = tuple(seq[0])
        seq = [x[0] if isinstance(x, Axis) else x for x in seq]
        assert all([isinstance(x, AxisID) for x in seq])
        return tuple.__new__(cls, seq)

    def as_axes(self):
        """TODO."""
        return Axes(x.axis for x in self)

    @staticmethod
    @with_axes_as_axis_ids
    def sub(at1, at2):
        """
        TODO.

        Arguments:
          at1: TODO
          at2: TODO

        Returns:

        """
        assert isinstance(at1, AxisIDTuple) and isinstance(at2, AxisIDTuple)
        return AxisIDTuple(_ for _ in at1 if _ not in at2)

    @staticmethod
    @with_axes_as_axis_ids
    def intersect(at1, at2):
        """
        TODO.

        Arguments:
          at1: TODO
          at2: TODO

        Returns:

        """
        assert isinstance(at1, AxisIDTuple) and isinstance(at2, AxisIDTuple)
        return AxisIDTuple(_ for _ in at1 if _ in at2)

    @staticmethod
    @with_axes_as_axis_ids
    def append(*at_list):
        """
        TODO.

        Arguments:
          *at_list: TODO

        Returns:

        """
        assert all([isinstance(at, AxisIDTuple) for at in at_list])
        elems = []
        for at in at_list:
            for x in at:
                if x not in elems:
                    elems.append(x)
        return AxisIDTuple(*elems)

    @staticmethod
    @with_axes_as_axis_ids
    def find(subaxes, axes):
        """
        TODO.

        Arguments:
          subaxes: TODO
          axes: TODO

        Returns:

        """
        assert isinstance(subaxes, AxisIDTuple)\
            and isinstance(axes, AxisIDTuple)
        for i in range(len(axes)):
            if axes[i:i + len(subaxes)] == subaxes:
                return i
        raise ValueError('Could not find subaxes')

    def __getitem__(self, item):
        if isinstance(item, slice):
            return AxisIDTuple(*super(AxisIDTuple, self).__getitem__(item))
        else:
            return super(AxisIDTuple, self).__getitem__(item)

    def __getslice__(self, i, j):
        return self.__getitem__(slice(i, j))

    def __add__(self, other):
        return AxisIDTuple.append(self, other)

    def __sub__(self, other):
        return AxisIDTuple.sub(self, other)

    def __repr__(self):
        s = 'AxisIDTuple('
        for i, x in enumerate(self):
            s += repr(x)
            s += ', '
        s += ')'
        return s


class FlattenedAxis(Axis):
    """
    A FlattenedAxis has length which is the product of the lengths of all
    Axis in the axes.  The original Axes object is stored so that we can later
    unflatten this Axis back to its original component Axis.

    Arguments:

    Returns:

    """

    def __init__(self, axes, **kwargs):
        assert isinstance(axes, Axes)
        length = reduce(operator.mul, axes.lengths, 1)
        super(FlattenedAxis, self).__init__(length=length, **kwargs)
        self.__axes = axes

    @property
    def empty(self):
        """TODO."""
        return len(self.__axes) == 0

    @property
    def single(self):
        """TODO."""
        return len(self.__axes) == 1

    @property
    def axes(self):
        """TODO."""
        return self.__axes

    def __repr__(self):
        s = 'FlattenedAxis('
        for i, x in enumerate(self.axes):
            s += repr(x)
            s += ', '
        s += ')'
        return s


def reduce_strides(strides):
    """
    TODO.

    Arguments:
      strides: TODO

    Returns:

    """
    return tuple(int(reduce_nested(elem, float('inf'), min))
                 for elem in strides)


def _check_sliced_axis_length(s, axis, new_axis):
    """
    Ensure that the length of the axis resulting from slicing axis with
    slice s matches the length of new_axis
    """

    expected_length = _sliced_length(s, axis.length)
    if expected_length != new_axis.length:
        raise ValueError((
            "A slice operation ({slice}) was attempted on axis "
            "{axis} with length {axis_length}.  The result of "
            "which is a new sliced axis of length "
            "{expected_length}.  The new_axis passed in "
            "{new_axis} has a different length which does not "
            "match: {new_axis_length}."
        ).format(
            slice=s,
            axis=axis,
            axis_length=axis.length,
            expected_length=expected_length,
            new_axis=new_axis,
            new_axis_length=new_axis.length,
        ))


class TensorDescription(NameableValue):
    """
    Description of a tensor that will be allocated in hardware.

    Names the tensor's dimensions with axes and holds pointers to the
    buffer allocated by the analysis and the backend tensor value
    (e.g. a numpy or gpu tensor).

    Arguments:
        axes: Axes of the tensor.
        base: If a view, the viewed tensor's description.
        dtype: The type of the tensor.
        full_strides: The strides of each axis.
        full_sizes: The allocated size of each axis (may be larger than the axis).
        offset: An offset into the viewed tensor.
        **kwargs: Additional args for related classes.

    """

    def __init__(self, axes, base=None,
                 dtype=np.dtype(np.float32),
                 full_strides=None, full_sizes=None, offset=0,
                 **kwargs):
        super(TensorDescription, self).__init__(**kwargs)
        # TODO: get the default type from the backend. May not always be numpy.
        # TODO: support flattening, unflattening, other complex reshapes
        axes = Axes(axes)
        self.axes = axes
        self.transformer = None
        self.__casts = weakref.WeakValueDictionary()
        self.__slices = weakref.WeakValueDictionary()
        self.__value = None
        self.__buffer = None
        self.__base = base
        self.dtype = dtype
        self.offset = offset
        self.ndim = len(self.axes)
        self.__read_only = False
        self.full_sizes = full_sizes if full_sizes is not None \
            else self.axes.full_lengths
        self.style = {}

        for axis in axes:
            if axis.length is None:
                raise ValueError((
                    'axes used in the constructor of TensorDescription must '
                    'always have non-None length.  Axis {axis} has length '
                    'None.'
                ).format(axis=axis))

        if full_strides is None:
            # TODO: deduce strides of nested axes.
            full_strides = []
            stride = self.dtype.itemsize
            for axis, full_size in reversed(list(zip(self.axes, self.full_sizes))):
                assert not isinstance(axis, FlattenedAxis)
                full_strides.append(stride)
                stride *= full_size
            self.full_strides = tuple(reversed(full_strides))
        else:
            self.full_strides = full_strides

        assert len(self.full_sizes) == self.ndim, \
            "Sizes must have same number of dimensions as axes"
        assert len(self.full_strides) == self.ndim, \
            "Strides must have same number of dimensions as axes"

    @property
    def parameter_key(self):
        """

        Returns: A tuple that can be used to tell if two views of a tensor are equivalent.

        """
        return (self.shape, self.dtype, self.offset, self.strides)

    def try_guess_positions(self, new_axes):
        """
        TODO.

        Arguments:
          new_axes: TODO

        Returns:

        """
        # Supports broadcast and combining one level of axes
        # Does not support unrolling
        old_poss = []

        used_set = set()

        def get_old_axis(new_axis):
            """
            TODO.

            Arguments:
              new_axis: TODO

            Returns:

            """
            for i, axis in enumerate(self.axes):
                if i not in used_set and axis == new_axis:
                    used_set.add(i)
                    return i
            else:
                return -1

        for axis in new_axes:
            old_pos = get_old_axis(axis)
            if old_pos == -1 and isinstance(axis, FlattenedAxis):
                poss = []
                for sub in axis.axes:
                    assert not isinstance(sub, FlattenedAxis)
                    poss.append(get_old_axis(sub))
                old_poss.append(tuple(poss))
            else:
                old_poss.append(old_pos)
        return old_poss

    def split_reduce_at(self, div_point):
        """
        TODO.

        Arguments:
          div_point: TODO

        Returns:

        """
        def pos_tup(lower, upper):
            """
            TODO.

            Arguments:
              lower: TODO
              upper: TODO

            Returns:

            """
            if lower == upper - 1:
                return lower
            else:
                return tuple(range(lower, upper))
        if div_point == 0 or div_point == self.ndim:
            new_axes = Axes([FlattenedAxis(self.axes)])
            old_poss = (pos_tup(0, self.ndim),)
        else:
            new_axes = Axes([
                FlattenedAxis(self.axes[:div_point]),
                FlattenedAxis(self.axes[div_point:])
            ])
            old_poss = (
                pos_tup(0, div_point),
                pos_tup(div_point, self.ndim)
            )
        return self.reaxe_with_positions(new_axes, old_poss)

    def dot_reaxe_left(self, red_axis_ids):
        """
        TODO.

        Arguments:
          red_axis_ids: TODO

        Returns:

        """
        old_axis_ids = self.axes.as_axis_ids()
        idx = AxisIDTuple.find(red_axis_ids, old_axis_ids)
        axis_ids = old_axis_ids[:idx]\
            + old_axis_ids[idx + len(red_axis_ids):]\
            + red_axis_ids
        div_point = len(old_axis_ids) - len(red_axis_ids)
        return self.reaxe_with_axis_ids(axis_ids).split_reduce_at(div_point)

    # This function is symmetric to dot_reaxe_left unless forward_axis
    # ids is specified. It then attempts to rename the reduction axis using
    # the mapping from the forward axis ids to the current axis ids.
    # In the case of backpropagation, this helps preserve the axis id numbering
    # of the original output, which is necessary if the derivative is to be
    # projected onto the input correctly.
    def dot_reaxe_right(self, red_axis_ids, forward_axis_ids=None):
        """
        TODO.

        Arguments:
          red_axis_ids: TODO
          forward_axis_ids: TODO

        Returns:

        """
        old_axis_ids = self.axes.as_axis_ids()
        if forward_axis_ids:
            trans = dict(list(zip(forward_axis_ids, old_axis_ids)))

            def trans_func(x):
                """
                TODO.

                Arguments:
                  x: TODO

                Returns:

                """
                if x in trans:
                    return trans[x]
                else:
                    return x

            red_axis_ids = AxisIDTuple(*list(map(trans_func, red_axis_ids)))
        idx = AxisIDTuple.find(red_axis_ids, old_axis_ids)
        axis_ids = red_axis_ids + old_axis_ids[:idx]\
            + old_axis_ids[idx + len(red_axis_ids):]
        div_point = len(red_axis_ids)
        return self.reaxe_with_axis_ids(axis_ids).split_reduce_at(div_point)

    def reaxe(self, new_axes, broadcast=True):
        """
        TODO.

        Arguments:
          new_axes: TODO
          broadcast: TODO

        Returns:

        """
        new_axes = Axes(new_axes)
        old_poss = self.try_guess_positions(new_axes)
        return self.reaxe_with_positions(new_axes, old_poss, broadcast)

    def reaxe_with_axis_ids_positions(self, new_axis_id_tuple):
        """
        TODO.

        Arguments:
          new_axis_id_tuple: TODO

        Returns:

        """
        old_axis_ids = self.axes.as_axis_ids()

        old_poss = []
        for axis_id in new_axis_id_tuple:
            for i, old_axis_id in enumerate(old_axis_ids):
                if axis_id == old_axis_id:
                    old_poss.append(i)
        return old_poss

    def reaxe_with_axis_ids(self, new_axis_id_tuple):
        """
        TODO.

        Arguments:
          new_axis_id_tuple: TODO

        Returns:

        """
        # This function does not allow any unrolling of axes
        # The argument is a tuple of axis ids.
        # The indices of the axis ids refer to the existing order of axes
        old_poss = self.reaxe_with_axis_ids_positions(new_axis_id_tuple)
        return self.reaxe_with_positions(new_axes=new_axis_id_tuple.as_axes(),
                                         old_poss=old_poss,
                                         broadcast=True)

    def reaxe_with_dummy_axis(self, dummy_axis, dim=-1):
        """
        TODO.

        Arguments:
          dummy_axis: TODO
          dim: TODO

        Returns:

        """
        if dim == -1:
            dim = len(self.axes)
        new_axes = self.axes[:dim]\
            .concat(Axes(dummy_axis,)).concat(self.axes[dim:])
        old_poss = list(range(dim)) + [-1] + list(range(dim, len(self.axes)))
        return self.reaxe_with_positions(new_axes=new_axes,
                                         old_poss=old_poss,
                                         broadcast=True)

    def reaxe_with_positions(self, new_axes, old_poss, broadcast=True):
        """
        TODO.

        Arguments:
          new_axes: TODO
          old_poss: TODO
          broadcast: TODO

        Returns:

        """
        assert len(new_axes) == len(old_poss)

        full_sizes = []
        full_strides = []

        def old_info(axis, old_pos):
            """
            TODO.

            Arguments:
              axis: TODO
              old_pos: TODO

            Returns:

            """
            if old_pos == -1:
                full_length = axis.axes.full_lengths\
                    if isinstance(axis, FlattenedAxis) else axis.length
                return full_length, 0
            else:
                return self.full_sizes[old_pos], self.full_strides[old_pos]

        for axis, old_pos in zip(new_axes, old_poss):
            if isinstance(axis, FlattenedAxis):
                sub_sizes = []
                sub_strides = []
                for sub, sub_pos in zip(axis.axes, old_pos):
                    assert not isinstance(sub, FlattenedAxis)
                    fsi, fst = old_info(sub, sub_pos)
                    sub_sizes.append(fsi)
                    sub_strides.append(fst)
                full_sizes.append(tuple(sub_sizes))
                full_strides.append(tuple(sub_strides))
            else:
                fsi, fst = old_info(axis, old_pos)
                full_sizes.append(fsi)
                full_strides.append(fst)

        new_axes, full_strides, full_sizes\
            = self.maybe_collapse_numerics(
                new_axes, full_strides, full_sizes
            )

        return TensorDescription(new_axes,
                                 base=self.base,
                                 dtype=self.dtype,
                                 full_strides=tuple(full_strides),
                                 full_sizes=tuple(full_sizes),
                                 offset=self.offset)

    def cast(self, new_axes):
        """
        Return a tensor desciption for a view of the tensor.

        Arguments:
            new_axes: The axes for the view.

        Returns:
            The tensor description.

        """
        return TensorDescription(
            new_axes,
            base=self.base,
            dtype=self.dtype,
            full_strides=self.full_strides,
            full_sizes=self.full_sizes,
            offset=self.offset
        )

    def maybe_collapse_numerics(self, axes, full_strides, full_sizes):
        """
        TODO.

        Arguments:
          axes: TODO
          full_strides: TODO
          full_sizes: TODO

        Returns:

        """
        def all_numeric(axes):
            """
            TODO.

            Arguments:
              axes: TODO

            Returns:

            """
            return all([isinstance(axis, NumericAxis) for axis in axes])

        new_axes = []
        new_strides = []
        new_sizes = []
        for axis, st, si in zip(axes, full_strides, full_sizes):
            if isinstance(axis, FlattenedAxis) and all_numeric(axis.axes):
                new_axes.append(NumericAxis(reduce_nested(
                    axis.axes.lengths, 1, operator.mul
                )))
                new_strides.append(int(reduce_nested(st, float('inf'), min)))
                new_sizes.append(reduce_nested(si, 1, operator.mul))
            else:
                new_axes.append(axis)
                new_strides.append(st)
                new_sizes.append(si)
        return Axes(new_axes), tuple(new_strides), tuple(new_sizes)

    def slice(self, slices, new_axes):
        """
        Return a tensor description for a slice view of this tensor.

        Arguments:
          slices: TODO
          new_axes: TODO

        Returns:
            The tensor description for the slice.
        """
        slices = list(slices)
        while len(slices) < self.ndim:
            slices.append(slice(None))

        offset = self.offset
        full_strides = []
        full_sizes = []
        new_index = 0

        # check new_axes for the correct length
        num_dimensions_out = len([s for s in slices if isinstance(s, slice)])
        if len(new_axes) != num_dimensions_out:
            raise ValueError((
                'in a slice operation, the number of axes pass in to '
                'new_axes ({num_new_axes}) must be the same as the number of '
                'slice objects in slices ({num_slices}).'
            ).format(
                num_new_axes=len(new_axes),
                num_slices=num_dimensions_out,
            ))

        for s, axis, stride, size in zip(slices, self.axes, self.strides, self.sizes):
            if isinstance(s, slice):
                # only increment new_axis when the input slice is a slice and
                # not a integer
                new_axis = new_axes[new_index]
                new_index += 1

                # ensure slice is of the kind we support
                _validate_slice(s)

                # ensure new_axis has the correct length
                _check_sliced_axis_length(s, axis, new_axis)

                start, stop, step = s.indices(axis.length)

                full_strides.append(stride * step)
                full_sizes.append(size)

                idx = start
            else:
                # this is a simple integer slice, ex: y = x[1]
                idx = s

            # TODO: write a test that fails if abs() is removed
            offset += idx * abs(stride)

        return TensorDescription(new_axes,
                                 base=self.base,
                                 dtype=self.dtype,
                                 full_strides=tuple(full_strides),
                                 full_sizes=tuple(full_sizes),
                                 offset=offset)

    @property
    def shape(self):
        """

        Returns: The shape of the tensor.

        """
        return self.axes.lengths

    @property
    def strides(self):
        """The strides of the tensor."""
        return reduce_strides(self.full_strides)

    @property
    def sizes(self):
        """The allocated sizes for each axis."""
        return tuple(reduce_nested(_, 1, operator.mul)
                     for _ in self.full_sizes)

    @property
    def base(self):
        """The viewed tensor description or None if not a view."""
        return self.__base or self

    @property
    def buffer(self):
        """The description of the underlying storage."""
        return self.base.__buffer

    @buffer.setter
    def buffer(self, value):
        """
        TODO.

        Arguments:
          value: TODO

        Returns:

        """
        self.base.__buffer = value

    @property
    def value(self):
        """A device handle to the value."""
        return self.__value

    def is_base(self):
        """This tensor provides its own storage."""
        return self.__base is None

    def initialize(self, transformer):
        """Called by transformer to set up value."""
        assert self.__value is None
        self.transformer = transformer
        # If the TensorDescription requires heap storage
        if self.buffer is not None:
            if self.buffer.data is None:
                self.buffer.data = self.transformer.device_buffer_storage(
                    self.buffer.size, self.dtype, self.name
                )
            self.__value = self.buffer.data.device_tensor(self)


def linear_map_axes(in_axes, out_axes):
    """
    For tensors ``out = dot(T, in)`` determines the axes ``T`` must have.

    Arguments:
      in_axes: The axes of ``in``.
      out_axes: The axes of ``out``.

    Returns:

    """
    in_axes = Axes.as_axes(in_axes)
    out_axes = Axes.as_axes(out_axes)
    in_axis_ids, out_axis_ids = in_axes.as_axis_ids(), out_axes.as_axis_ids()
    return (
        (out_axis_ids + in_axis_ids) -
        AxisIDTuple.intersect(in_axis_ids, out_axis_ids)
    ).as_axes()
