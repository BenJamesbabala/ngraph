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
from __future__ import print_function

from functools import wraps
from operator import itemgetter
# These are indirectly used by the generated code
import numpy as np  # noqa
import itertools as itt
from ngraph.op_graph import axes  # noqa

from ngraph.util.pygen import PyGen, indenting
from ngraph.util.generics import generic_method

from ngraph.op_graph.op_graph import absolute, AddOneDim, AddZeroDim, Argmax, Argmin, cos, \
    DivideOneDim, DivideZeroDim, DotOneDimensional, DotTwoDimensional, DotTwoByOne, \
    EqualOneDim, EqualZeroDim, exp, \
    GreaterOneDim, GreaterZeroDim, GreaterEqualOneDim, GreaterEqualZeroDim, \
    LessOneDim, LessZeroDim, \
    LessEqualOneDim, LessEqualZeroDim, log, Max, MaximumOneDim, MaximumZeroDim, Min, \
    MinimumOneDim, MinimumZeroDim, \
    MultiplyOneDim, MultiplyZeroDim, \
    negative, NotEqualOneDim, NotEqualZeroDim, Onehot, Power, reciprocal, \
    SetItemOneDim, sign, sin, sqrt, square, \
    SubtractOneDim, SubtractZeroDim, \
    Sum, tanh, tensor_size, Fill, TensorDescription, Unslice, Stack, Dimshuffle
from ngraph.op_graph.convolution import convolution, update_conv, bprop_conv
from ngraph.op_graph.pooling import pooling, bprop_pool
from ngraph.op_graph.debug import PrintOp

from ngraph.transformers.base import Transformer, DeviceBufferStorage, DeviceBufferReference, \
    DeviceTensor


class NumPyConvEngine(object):
    @staticmethod
    def xprop():
        return """
        K, _, _, _, N = O.shape
        for (m, mS), (p, pS), (q, qS) in itt.product(enumerate(mSlice),
                                                     enumerate(pSlice),
                                                     enumerate(qSlice)):
            sliceT, sliceD, _ = mS
            sliceR, sliceH, _ = pS
            sliceS, sliceW, _ = qS
            slicedF = F[:, sliceT, sliceR, sliceS, :].reshape((-1, K))
            slicedI = I[:, sliceD, sliceH, sliceW, :].reshape((-1, N))
            O[:, m, p, q, :] = np.dot(slicedF.T, slicedI)
        """

    @staticmethod
    def fprop_conv():
        pycode = """
        I = {I}
        F = {F}
        O = {O}
        mSlice, pSlice, qSlice, _, _, _ = self.conv_slices[{index}]
        """ + NumPyConvEngine.xprop()

        return pycode

    @staticmethod
    def bprop_conv():
        pycode = """
        I = {E}
        F = {F}
        O = {gI}
        _, _, _, mSlice, pSlice, qSlice = self.conv_slices[{index}]
        F = np.transpose(F[:, ::-1, ::-1, ::-1, :], (4, 1, 2, 3, 0)).copy()
        """ + NumPyConvEngine.xprop()

        return pycode

    @staticmethod
    def update_conv():
        pycode = """
        I = {I}
        E = {E}
        U = {U}
        mSlice, pSlice, qSlice, _, _, _ = self.conv_slices[{index}]
        C, _, _, _, K = U.shape
        U.fill(0.0)
        for (m, mS), (p, pS), (q, qS) in itt.product(enumerate(mSlice),
                                                     enumerate(pSlice),
                                                     enumerate(qSlice)):
            sliceT, sliceD, tlen = mS
            sliceR, sliceH, rlen = pS
            sliceS, sliceW, slen = qS
            slicedI = I[:, sliceD, sliceH, sliceW, :].reshape((-1, N))
            slicedE = E[:, m, p, q, :]
            update = np.dot(slicedI, slicedE.T).reshape((C, tlen, rlen, slen, K))
            U[:, sliceT, sliceR, sliceS, :] += update
        """
        return pycode

    @staticmethod
    def get_slices(I, F, O, conv_dims):
        C, D, H, W, _ = I.tensor_description.axes.lengths
        C, T, R, S, K = F.tensor_description.axes.lengths
        K, M, P, Q, _ = O.tensor_description.axes.lengths
        pad_d, pad_h, pad_w = itemgetter(*('pad_' + s for s in ('d', 'h', 'w')))(conv_dims)
        str_d, str_h, str_w = itemgetter(*('str_' + s for s in ('d', 'h', 'w')))(conv_dims)
        mSlice = [NumPyConvEngine.fprop_slice(m, T, D, pad_d, str_d) for m in range(M)]
        pSlice = [NumPyConvEngine.fprop_slice(p, R, H, pad_h, str_h) for p in range(P)]
        qSlice = [NumPyConvEngine.fprop_slice(q, S, W, pad_w, str_w) for q in range(Q)]
        dSlice = [NumPyConvEngine.bprop_slice(d, T, M, pad_d, str_d) for d in range(D)]
        hSlice = [NumPyConvEngine.bprop_slice(h, R, P, pad_h, str_h) for h in range(H)]
        wSlice = [NumPyConvEngine.bprop_slice(w, S, Q, pad_w, str_w) for w in range(W)]

        return (mSlice, pSlice, qSlice, dSlice, hSlice, wSlice)

    @staticmethod
    def fprop_slice(q, S, X, padding, strides):
        firstF = 0
        lastF = S - 1
        qs = q * strides - padding
        x2 = qs + lastF
        if qs < 0:
            firstF = -qs
            qs = 0
        if x2 >= X:
            dif = x2 - X + 1
            lastF -= dif
            x2 -= dif
        return (slice(firstF, lastF + 1), slice(qs, x2 + 1), lastF - firstF + 1)

    @staticmethod
    def bprop_slice(x, S, Q, padding, strides):
        qs = x - (S - padding - 1)
        firstF = None
        for s in range(S):  # TODO remove loop logic here.
            q = qs + s
            if q % strides == 0:
                q //= strides
                if q >= 0 and q < Q:
                    if firstF is None:
                        firstF = s
                        firstE = q
                    lastF = s
                    lastE = q
        if firstF is None:
            return (slice(0, 0, 1), slice(0, 0, 1), 0)
        return (slice(firstF, lastF + 1, strides), slice(firstE, lastE + 1, 1), 0)


class NumPyPoolEngine(object):

    @staticmethod
    def fprop_pool():
        pycode = """
        arrI = {I}
        arrO = {O}
        kSlice, mSlice, pSlice, qSlice, arrA = self.pool_slices[{index}]
        op = self.pool_params[{index}]['op']
        K, M, P, Q, N = arrO.shape
        for (k, kS), (m, mS), (p, pS), (q, qS) in itt.product(enumerate(kSlice),
                                                              enumerate(mSlice),
                                                              enumerate(pSlice),
                                                              enumerate(qSlice)):
            sliceI = arrI[kS[0], mS[0], pS[0], qS[0], :].reshape((-1, N))
            if op == "max":
                arrA[k, m, p, q, :] = np.argmax(sliceI, axis=0)
                arrO[k, m, p, q, :] = np.max(sliceI, axis=0)
            elif op == "avg":
                arrO[k, m, p, q, :] = np.mean(sliceI, axis=0)
            elif op == "l2":
                arrO[k, m, p, q, :] = np.sqrt(np.sum(np.square(sliceI), axis=0))
        """
        return pycode

    @staticmethod
    def bprop_pool():
        pycode = """
        arrE = {I}
        arrD = {O}
        kSlice, mSlice, pSlice, qSlice, arrA = self.pool_slices[{index}]
        op = self.pool_params[{index}]['op']
        K, M, P, Q, N = arrE.shape
        for (k, kS), (m, mS), (p, pS), (q, qS) in itt.product(enumerate(kSlice),
                                                              enumerate(mSlice),
                                                              enumerate(pSlice),
                                                              enumerate(qSlice)):
            sliceC, clen = kS
            sliceD, dlen = mS
            sliceH, hlen = pS
            sliceW, wlen = qS

            patch_in = (sliceC, sliceD, sliceH, sliceW, slice(None))
            patch_out = (k, m, p, q, slice(None))
            sliceB = arrD[patch_in].reshape((-1, N))
            if op == "max":
                max_n = arrA[patch_out]
                sliceB[max_n, list(range(N))] += arrE[patch_out]
            elif op == "avg":
                sliceB += arrE[patch_out] * (1.0 / sliceB.shape[0])
            else:
                raise NotImplementedError
            arrD[patch_in] = sliceB.reshape((clen, dlen, hlen, wlen, N))
        """
        return pycode

    @staticmethod
    def get_slices(I, O, pool_params):
        C, D, H, W, _ = I.tensor_description.axes.lengths
        K, M, P, Q, N = O.tensor_description.axes.lengths

        J, T, R, S, op = itemgetter(*('J', 'T', 'R', 'S', 'op'))(pool_params)
        p_c, p_d, p_h, p_w = itemgetter(*('pad_' + s for s in ('c', 'd', 'h', 'w')))(pool_params)
        s_c, s_d, s_h, s_w = itemgetter(*('str_' + s for s in ('c', 'd', 'h', 'w')))(pool_params)

        kSlice = [NumPyPoolEngine.pool_slice(k, J, C, p_c, s_c) for k in range(K)]
        mSlice = [NumPyPoolEngine.pool_slice(m, T, D, p_d, s_d) for m in range(M)]
        pSlice = [NumPyPoolEngine.pool_slice(p, R, H, p_h, s_h) for p in range(P)]
        qSlice = [NumPyPoolEngine.pool_slice(q, S, W, p_w, s_w) for q in range(Q)]
        array_argmax = np.empty((K, M, P, Q, N), dtype=np.uint8) if op == "max" else None

        return (kSlice, mSlice, pSlice, qSlice, array_argmax)

    @staticmethod
    def pool_slice(q, S, X, padding, strides):
        qs = q * strides - padding
        firstI = None
        for s in range(S):
            x = qs + s
            if x >= 0 and x < X:
                if firstI is None:
                    firstI = x
                lastI = x
        return (slice(firstI, lastI + 1), lastI - firstI + 1)


class NumPyDeviceBufferStorage(DeviceBufferStorage):
    def __init__(self, transformer, bytes, dtype, **kwargs):
        super(NumPyDeviceBufferStorage, self).__init__(transformer, bytes, dtype, **kwargs)
        self.storage = None

    def create_device_tensor(self, tensor_description):
        shape_str = "_".join((str(_) for _ in tensor_description.shape))
        return NumPyDeviceTensor(self.transformer, self, tensor_description,
                                 name="{}_v_{}_{}".format(self.name,
                                                          tensor_description.name,
                                                          shape_str))

    @property
    def alloc_name(self):
        """
        :return: Name for allocation method.
        """
        return "alloc_" + self.name

    @property
    def update_name(self):
        """
        :return: name for update method.
        """
        return "update_" + self.name

    @property
    def ref_str(self):
        """
        :return: name to reference variable.
        """
        return "self." + self.name

    def transform_allocate(self):
        self.transformer.init_code.append("{} = None", self.ref_str)
        self.transformer.allocate_storage_code.append("def {}(self):", self.alloc_name)
        with indenting(self.transformer.allocate_storage_code):
            elts = self.bytes // self.dtype.itemsize
            self.transformer.allocate_storage_code.append(
                """
                self.{}(np.empty({}, dtype=np.dtype('{}')))
                """,
                self.update_name, elts, self.dtype.name)
            self.transformer.allocate_storage_code.endl()

        self.transformer.allocate_storage_code.append("def {}(self, buffer):",
                                                      self.update_name)
        with indenting(self.transformer.allocate_storage_code):
            self.transformer.allocate_storage_code.append("{} = buffer", self.ref_str)
            self.transform_allocate_views()
        self.transformer.allocate_storage_code.endl()

        self.transformer.allocate_code.append("self.{}()", self.alloc_name)


class NumPyDeviceBufferReference(DeviceBufferReference):
    def __init__(self, transformer, **kwargs):
        super(NumPyDeviceBufferReference, self).__init__(transformer, **kwargs)


class NumPyDeviceTensor(DeviceTensor):
    def __init__(self, transformer, device_buffer, tensor_description, **kwargs):
        super(NumPyDeviceTensor, self).__init__(transformer, device_buffer, tensor_description,
                                                **kwargs)
        self.__tensor = None

    @property
    def tensor(self):
        if self.__tensor is None:
            self.__tensor = getattr(self.transformer.model, self.name)
        return self.__tensor

    @property
    def ref_str(self):
        """
        :return: name to reference variable.
        """
        return "self." + self.name

    def transform_allocate(self):
        tensor_description = self.tensor_description
        self.transformer.init_code.append("{} = None", self.ref_str)
        self.transformer.allocate_storage_code.append(
            """
            {ref} = np.ndarray(
                shape={shape},
                dtype=np.{dtype},
                buffer=buffer,
                offset={offset},
                strides={strides})
            """,
            ref=self.ref_str,
            shape=tensor_description.shape,
            dtype=tensor_description.dtype,
            offset=tensor_description.offset,
            strides=tensor_description.strides)

    def get(self, tensor):
        if tensor is None:
            return self.tensor
        tensor[:] = self.tensor

    def __getitem__(self, key):
        return self.tensor.__getitem__(key)

    def __setitem__(self, key, value):
        # Temporary hack to interoperate with neon cpu backend.
        if hasattr(value, '_tensor'):
            value = value._tensor
        self.tensor.__setitem__(key, value)


def get_tensors(f):
    def tensor(x):
        if isinstance(x, NumPyDeviceTensor):
            return x.tensor
        return x

    @wraps(f)
    def helper(*args):
        return f(*(tensor(arg) for arg in args))

    return helper


class NumPyCodeGenerator(PyGen):
    def __init__(self, **kwargs):
        super(NumPyCodeGenerator, self).__init__(**kwargs)
        self.conv_dims = []
        self.conv_slices = []
        self.pool_params = []
        self.pool_slices = []

    def name(self, x):
        if isinstance(x, NumPyDeviceBufferStorage):
            return x.ref_str
        if isinstance(x, NumPyDeviceTensor):
            return x.ref_str
        return x

    @generic_method
    def generate_op(self, op, *args):
        if op.is_device_op:
            raise ValueError((
                "{class_name} doesn't have a generate_op method for op: {op}. "
                "In order to fix this, add a method generate_op decorated with "
                "@generate_op.on_type({op}) to class {class_name}."
            ).format(
                class_name=self.__class__.__name__,
                op=op.__class__.__name__,
            ))

    @generate_op.on_type(absolute)
    def generate_op(self, op, out, x):
        self.append("np.abs({}, out={}", x, out)

    @generate_op.on_type(AddOneDim)
    def generate_op(self, op, out, x, y):
        self.append("np.add({}, {}, out={})", x, y, out)

    @generate_op.on_type(AddZeroDim)
    def generate_op(self, op, out, x, y):
        self.append("np.add({}, {}, out={})", x, y, out)

    @generate_op.on_type(Argmax)
    def generate_op(self, op, out, x):
        self.append("np.ndarray.argmax({}, 0, out={})", x, out)

    @generate_op.on_type(Argmin)
    def generate_op(self, op, out, x):
        self.append("np.ndarray.argmin({}, 0, out={})", x, out)

    @generate_op.on_type(convolution)
    def generate_op(self, op, outputs, inputs, filters):
        self.conv_dims.append(op.convdict)
        self.conv_slices.append(NumPyConvEngine.get_slices(inputs, filters, outputs, op.convdict))
        self.append(
            NumPyConvEngine.fprop_conv(),
            index=op.index,
            I=inputs,
            F=filters,
            O=outputs
        )

    @generate_op.on_type(bprop_conv)
    def generate_op(self, op, outputs, delta, filters):
        self.append(
            NumPyConvEngine.bprop_conv(),
            index=op.index,
            E=delta,
            F=filters,
            gI=outputs
        )

    @generate_op.on_type(update_conv)
    def generate_op(self, op, outputs, delta, inputs):
        self.append(
            NumPyConvEngine.update_conv(),
            index=op.index,
            I=inputs,
            E=delta,
            U=outputs
        )

    @generate_op.on_type(pooling)
    def generate_op(self, op, outputs, inputs):
        self.pool_params.append(op.pool_params)
        self.pool_slices.append(NumPyPoolEngine.get_slices(inputs, outputs, op.pool_params))
        self.append(
            NumPyPoolEngine.fprop_pool(),
            index=op.index,
            I=inputs,
            O=outputs
        )

    @generate_op.on_type(bprop_pool)
    def generate_op(self, op, outputs, delta):
        self.append(
            NumPyPoolEngine.bprop_pool(),
            index=op.index,
            I=delta,
            O=outputs
        )

    @generate_op.on_type(cos)
    def generate_op(self, op, out, x):
        self.append("np.cos({}, out={})", x, out)

    @generate_op.on_type(Dimshuffle)
    def generate_op(self, op, out, x):
        self.append(
            "{}[()] = np.transpose({}, {})",
            out, x, op.old_axis_positions
        )

    @generate_op.on_type(DivideOneDim)
    def generate_op(self, op, out, x, y):
        self.append("np.divide({}, {}, out={})", x, y, out)

    @generate_op.on_type(DivideZeroDim)
    def generate_op(self, op, out, x, y):
        self.append("np.divide({}, {}, out={})", x, y, out)

    @generate_op.on_type(DotOneDimensional)
    def generate_op(self, op, out, x, y):
        self.append("""np.dot({}, {}, out={})""", x, y, out)

    @generate_op.on_type(DotTwoDimensional)
    def generate_op(self, op, out, x, y):
        self.append("""np.dot({}, {}, out={})""", x, y, out)

    @generate_op.on_type(DotTwoByOne)
    def generate_op(self, op, out, x, y):
        self.append("""np.dot({}, {}, out={})""", x, y, out)

    @generate_op.on_type(EqualOneDim)
    def generate_op(self, op, out, x, y):
        self.append("np.equal({}, {}, out={})", x, y, out)

    @generate_op.on_type(EqualZeroDim)
    def generate_op(self, op, out, x, y):
        self.append("np.equal({}, {}, out={})", x, y, out)

    @generate_op.on_type(exp)
    def generate_op(self, op, out, x):
        self.append("np.exp({}, out={})", x, out)

    @generate_op.on_type(Fill)
    def generate_op(self, op, out, x):
        self.append("{}.fill({})", x, op.scalar)

    @generate_op.on_type(GreaterOneDim)
    def generate_op(self, op, out, x, y):
        self.append("np.greater({}, {}, out={})", x, y, out)

    @generate_op.on_type(GreaterZeroDim)
    def generate_op(self, op, out, x, y):
        self.append("np.greater({}, {}, out={})", x, y, out)

    @generate_op.on_type(GreaterEqualOneDim)
    def generate_op(self, op, out, x, y):
        self.append("np.greater_equal({}, {}, out={})", x, y, out)

    @generate_op.on_type(GreaterEqualZeroDim)
    def generate_op(self, op, out, x, y):
        self.append("np.greater_equal({}, {}, out={})", x, y, out)

    @generate_op.on_type(LessOneDim)
    def generate_op(self, op, out, x, y):
        self.append("np.less({}, {}, out={})", x, y, out)

    @generate_op.on_type(LessZeroDim)
    def generate_op(self, op, out, x, y):
        self.append("np.less({}, {}, out={})", x, y, out)

    @generate_op.on_type(LessEqualOneDim)
    def generate_op(self, op, out, x, y):
        self.append("np.less_equal({}, {}, out={})", x, y, out)

    @generate_op.on_type(LessEqualZeroDim)
    def generate_op(self, op, out, x, y):
        self.append("np.less_equal({}, {}, out={})", x, y, out)

    @generate_op.on_type(log)
    def generate_op(self, op, out, x):
        self.append("np.log({}, out={})", x, out)

    @generate_op.on_type(Max)
    def generate_op(self, op, out, x):
        self.append("np.max({}, 0, out={})", x, out)

    @generate_op.on_type(MaximumOneDim)
    def generate_op(self, op, out, x, y):
        self.append("np.maximum({}, {}, out={})", x, y, out)

    @generate_op.on_type(MaximumZeroDim)
    def generate_op(self, op, out, x, y):
        self.append("np.maximum({}, {}, out={})", x, y, out)

    @generate_op.on_type(Min)
    def generate_op(self, op, out, x):
        self.append("np.min({}, 0, out={})", x, out)

    @generate_op.on_type(MinimumOneDim)
    def generate_op(self, op, out, x, y):
        self.append("np.minimum({}, {}, out={})", x, y, out)

    @generate_op.on_type(MinimumZeroDim)
    def generate_op(self, op, out, x, y):
        self.append("np.minimum({}, {}, out={})", x, y, out)

    @generate_op.on_type(MultiplyOneDim)
    def generate_op(self, op, out, x, y):
        self.append("np.multiply({}, {}, out={})", x, y, out)

    @generate_op.on_type(MultiplyZeroDim)
    def generate_op(self, op, out, x, y):
        self.append("np.multiply({}, {}, out={})", x, y, out)

    @generate_op.on_type(negative)
    def generate_op(self, op, out, x):
        self.append("np.negative({}, out={})", x, out)

    @generate_op.on_type(NotEqualOneDim)
    def generate_op(self, op, out, x, y):
        self.append("np.not_equal({}, {}, out={})", x, y, out)

    @generate_op.on_type(NotEqualZeroDim)
    def generate_op(self, op, out, x, y):
        self.append("np.not_equal({}, {}, out={})", x, y, out)

    @generate_op.on_type(Onehot)
    def generate_op(self, op, out, x):
        self.append("""
        o = {o}
        x = {x}
        o[:] = 0
        for i in range(len(x)):
            o[x[i], i] = 1
        """, x=x, o=out)

    @generate_op.on_type(Power)
    def generate_op(self, op, out, x, y):
        self.append("np.power({}, {}, out={}", x, y, out)

    @generate_op.on_type(PrintOp)
    def generate_op(self, op, out, x):
        if op.prefix is not None:
            self.append("""
                print({prefix} + ':', {x})
                {out}[()] = {x}
            """, out=out, x=x, prefix=repr(op.prefix))
        else:
            self.append("""
                print({x})
                {out}[()] = {x}
            """, out=out, x=x)

    @generate_op.on_type(reciprocal)
    def generate_op(self, op, out, x):
        self.append("np.reciprocal({}, out={})", x, out)

    @generate_op.on_type(SetItemOneDim)
    def generate_op(self, op, out, tensor, value):
        self.append("{}.__setitem__({}, {})", tensor, op.item, value)

    @generate_op.on_type(sign)
    def generate_op(self, op, out, x):
        self.append("np.sign({}, out=out)", x, out)

    @generate_op.on_type(sin)
    def generate_op(self, op, out, x):
        self.append("np.sin({}, out={})", x, out)

    @generate_op.on_type(sqrt)
    def generate_op(self, op, out, x):
        self.append("np.sqrt({}, out={})", x, out)

    @generate_op.on_type(square)
    def generate_op(self, op, out, x):
        self.append("np.square({}, out={})", x, out)

    @generate_op.on_type(SubtractOneDim)
    def generate_op(self, op, out, x, y):
        self.append("np.subtract({}, {}, out={})", x, y, out)

    @generate_op.on_type(SubtractZeroDim)
    def generate_op(self, op, out, x, y):
        self.append("np.subtract({}, {}, out={})", x, y, out)

    @generate_op.on_type(Sum)
    def generate_op(self, op, out, x):
        self.append("np.sum({}, axis=0, out={})", x, out)

    @generate_op.on_type(tanh)
    def generate_op(self, op, out, x):
        self.append("np.tanh({}, out={})", x, out)

    @generate_op.on_type(tensor_size)
    def generate_op(self, op, out):
        self.append("{}.fill({})", out, op.reduction_axes.size)

    @generate_op.on_type(Unslice)
    def generate_op(self, op, out, out_sliced, x):
        self.append("{}.fill(0)", out)
        self.append("{}.__setitem__((), {})", out_sliced, x)

    @generate_op.on_type(Stack)
    def generate_op(self, op, out, *args):
        # TODO: we may want to have the inputs write into slices of a
        # preallocated buffer for this op.
        # We cannot use the numpy stack function as it is unavailable in
        # older versions.
        self.append("o={}", out)
        slices = [slice(None)] * len(op.axes)
        for i, arg in enumerate(args):
            slices[op.pos] = i
            self.append("o.__setitem__({s}, {x})", s=tuple(slices), x=arg)


class NumPyTransformer(Transformer):
    """
    Transformer for executing graphs on a CPU, backed by numpy.

    Given a list of ops you want to compute the results of, this transformer
    will compile the graph required to compute those results and exposes an
    evaluate method to execute the compiled graph.
    """

    transformer_name = "numpy"

    def __init__(self, **kwargs):
        super(NumPyTransformer, self).__init__(**kwargs)
        self.conv_engine = NumPyConvEngine()
        self.init_code = NumPyCodeGenerator()
        self.allocate_storage_code = NumPyCodeGenerator()
        self.allocate_code = NumPyCodeGenerator()
        self.compute_code = NumPyCodeGenerator()
        self.code = NumPyCodeGenerator()
        self.model = None
        self.n_computations = 0
        self.use_pinned_mem = False
        self.rng_seed = None

    def device_buffer_storage(self, bytes, dtype, name):
        """
        Make a DeviceBuffer.

        Arguments:
            bytes: Size of buffer.
            alignment: Alignment of buffer.

        Returns: A DeviceBuffer.
        """
        return NumPyDeviceBufferStorage(self, bytes, dtype, name="a_" + name)

    def device_buffer_reference(self):
        """
        Make a DeviceBufferReference.

        Returns: A DeviceBufferReference.
        """
        return NumPyDeviceBufferReference(self)

    def start_transform_allocate(self):
        self.init_code.append("""def __init__(self):""")
        self.init_code.indent(1)
        self.allocate_code.append("""def allocate(self):""")
        self.allocate_code.indent(1)

    def finish_transform_allocate(self):
        pass

    def transform_ordered_ops(self, ordered_ops, name):
        if name is None:
            name = "c_" + str(self.n_computations)
        self.n_computations += 1
        self.compute_code.append("def {}(self):", name)
        code = self.compute_code.code

        def tensor_description_value(x):
            if isinstance(x, TensorDescription):
                return x.value
            return x

        with indenting(self.compute_code):
            for op in ordered_ops:
                out = tensor_description_value(op.tensor_description())
                call_info = (tensor_description_value(_) for _ in op.call_info())
                self.compute_code.generate_op(op, out, *call_info)
            if code is self.compute_code.code:
                self.compute_code.append("pass")
        self.compute_code.endl()
        return name

    def finish_transform(self):
        if self.model is not None:
            return

        self.code.append(" class Model(object):")
        with indenting(self.code):
            if len(self.device_buffers) == 0:
                self.init_code.append("pass")
            self.code.append(self.init_code.code)
            self.code.endl()
            self.code.append(self.allocate_storage_code.code)
            self.code.endl()
            if len(self.device_buffers) == 0:
                self.allocate_code.append("pass")
            self.code.append(self.allocate_code.code)
            self.code.endl(2)
            self.code.append(self.compute_code.code)

            # print(self.code.code)
            # print(self.code.filename)

        r = self.code.compile("op", globals())
        self.model = r['Model']()
        self.model.conv_dims = self.compute_code.conv_dims
        self.model.pool_params = self.compute_code.pool_params
        self.model.conv_slices = self.compute_code.conv_slices
        self.model.pool_slices = self.compute_code.pool_slices

        for computation in self.computations:
            executor = getattr(self.model, computation.name)
            computation.executor = executor

    def allocate_storage(self):
        self.model.allocate()

    def consume(self, buf_index, hostlist, devlist):
        '''
        This is currently used for Aeon dataloading -- need to set things up to do actual
        device buffer allocation
        '''
        assert 0 <= buf_index < 2, 'Can only double buffer'
        hb = np.rollaxis(hostlist[buf_index], 0, hostlist[buf_index].ndim)
        if devlist[buf_index] is None:
            devlist[buf_index] = np.empty_like(hb)
        devlist[buf_index][:] = hb

Transformer.set_transformer_factory(
    Transformer.make_transformer_factory(NumPyTransformer.transformer_name))
