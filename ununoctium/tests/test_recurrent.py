import numpy as np
import pytest
import unittest

from geon.util.utils import ExecutorFactory
import geon as be
import geon.frontends.base.axis as ax

delta = 1e-3


class RecursionTest(object):
    def setUpHelper(
        self, x_np, axes, axes_lengths,
        timesteps=10, init=None, deriv_error=1e-2
    ):
        self.x_np = x_np
        self.x = be.placeholder(axes=axes)
        self.axes_lengths = axes_lengths
        self.timesteps = timesteps
        self.init = init
        self.deriv_error = deriv_error

    def i_to_h(self, x):
        raise NotImplementedError

    def h_to_h(self, h):
        raise NotImplementedError

    def i_to_h_np(self, x_np):
        raise NotImplementedError

    def h_to_h_np(self, h_np):
        raise NotImplementedError

    @property
    def _i_to_h(self):
        return lambda x: self.i_to_h(x)

    @property
    def _h_to_h(self):
        return lambda h: self.h_to_h(h)

    def np_rec(self, x):
        h = self.i_to_h_np(x)
        hs = [h]
        for i in range(self.timesteps - 1):
            h = self.h_to_h_np(h)
            hs.append(h)
        return np.array(hs, dtype=x.dtype)

    def test_rnn(self):
        for axis, length in self.axes_lengths.items():
            axis.length = length
        if self.init is not None:
            self.init()
        ax.T.length = self.timesteps

        ex = ExecutorFactory()
        sym_h = be.recurrent(
            self.x, self._i_to_h, self._h_to_h, ax.T, stack_pos=0
        )
        sym_fun = ex.executor(sym_h, self.x)
        sym_deriv_fun = ex.derivative(sym_h, self.x)
        num_deriv_fun = ex.numeric_derivative(sym_h, self.x, delta)

        np.testing.assert_allclose(
            sym_fun(self.x_np),
            self.np_rec(self.x_np),
            err_msg="{} values".format(self.__class__.__name__)
        )
        np.testing.assert_allclose(
            sym_deriv_fun(self.x_np),
            num_deriv_fun(self.x_np),
            rtol=self.deriv_error,
            err_msg="{} deriv".format(self.__class__.__name__)
        )


class T1(RecursionTest, unittest.TestCase):
    def setUp(self):
        self.setUpHelper(
            x_np=np.array([2, 4, 6], dtype='float32'),
            axes=(ax.C,),
            axes_lengths={ax.C: 3}
        )

    def i_to_h(self, x):
        return be.sum(x)

    def h_to_h(self, h):
        return h + 2

    def i_to_h_np(self, x):
        return np.sum(x)

    def h_to_h_np(self, h):
        return h + 2


class T2(RecursionTest, unittest.TestCase):
    def setUp(self):
        def init():
            self.W1_np = np.ones((2, 3, 4), dtype='float32')
            self.W1 = be.NumPyTensor(self.W1_np, axes=(ax.C, ax.D, ax.H))
            self.W2_np = np.ones((4, 4), dtype='float32')
            self.W2 = be.NumPyTensor(self.W2_np, axes=(ax.H, ax.H))

        self.setUpHelper(
            x_np=np.array([[2, 4, 6], [3, 4, 6]], dtype='float32'),
            axes=(ax.C, ax.D),
            axes_lengths={ax.C: 2, ax.D: 3, ax.H: 4},
            init=init,
            deriv_error=1e-1,
            timesteps=5
        )

    def i_to_h(self, x):
        return be.dot(x, self.W1)

    def h_to_h(self, h):
        return be.dot(h, self.W2)

    def i_to_h_np(self, x):
        return x.flatten().dot(self.W1_np.reshape((6, 4)))

    def h_to_h_np(self, h):
        return h.dot(self.W2_np)


if __name__ == '__main__':
    pytest.main(__file__)
