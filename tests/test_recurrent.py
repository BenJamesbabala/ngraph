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
"""
This test compares the NEON recurrent layer against a numpy reference recurrent
implementation and compares the NEON recurrent bprop deltas to the gradients
estimated by finite differences.
The numpy reference recurrent layer contains static methods for forward pass
and backward pass.
The test runs a SINGLE layer of recurrent layer and compare numerical values
The reference model handles batch_size as 1 only

The following are made sure to be the same in both recurrent layers
    -   initial h values (all zeros)
    -   initial W, b (ones or random values)
    -   input data (random data matrix)
    -   input error (random data matrix)
    -   the data shape inside recurrent_ref is seq_len, input_size, 1
    -   the data shape inside recurrent (neon) is feature, seq_len * batch_size
"""

import itertools as itt
import numpy as np

from neon import NervanaObject

import ngraph as ng
from ngraph.frontends.neon.axis import ax

from ngraph.frontends.neon import *  # noqa
from ngraph.frontends.neon.recurrent import Recurrent

from neon import logger as neon_logger
from neon.initializers.initializer import Uniform, Gaussian

from recurrent_ref import Recurrent as RefRecurrent

from ngraph.util.utils import executor
from ngraph.util.utils import raise_all_numpy_errors
from ngraph.util.utils import RandomTensorGenerator

rng = RandomTensorGenerator(0, np.float32)

def pytest_generate_tests(metafunc):
    bsz_rng = [1]

    if 'refgruargs' in metafunc.fixturenames:
        fargs = []
        seq_rng = [3]
        inp_rng = [5]
        out_rng = [10]
        fargs = itt.product(seq_rng, inp_rng, out_rng, bsz_rng)
        metafunc.parametrize('refgruargs', fargs)

    if 'gradgruargs' in metafunc.fixturenames:
        fargs = []
        if metafunc.config.option.all:
            seq_rng = [2, 3]
            inp_rng = [5, 10]
            out_rng = [3, 5, 10]
        else:
            seq_rng = [3]
            inp_rng = [5]
            out_rng = [10]
        fargs = itt.product(seq_rng, inp_rng, out_rng, bsz_rng)
        metafunc.parametrize('gradgruargs', fargs)

def test_ref_compare_ones(transformer_factory, refgruargs):
    # run comparison with reference code
    # for all ones init
    seq_len, input_size, hidden_size, batch_size = refgruargs
    from neon.backends import gen_backend
    be = gen_backend(backend='dataloader')
    check_rnn(seq_len, input_size, hidden_size,
              batch_size, Constant(val=1.0))

def test_ref_compare_rand(transformer_factory, refgruargs):
    # run comparison with reference code
    # for Gaussian random init
    seq_len, input_size, hidden_size, batch_size = refgruargs
    from neon.backends import gen_backend
    be = gen_backend(backend='dataloader')
    check_rnn(seq_len, input_size, hidden_size, batch_size,
              Gaussian())


# compare neon RNN to reference RNN implementation
def check_rnn(seq_len, input_size, hidden_size,
              batch_size, init_func):
    # init_func is the initializer for the model params
    assert batch_size == 1, "the recurrent reference implementation only support batch size 1"

    # ========== neon model ==========
    Cin = ng.Axis(input_size)
    REC = ng.Axis(seq_len, recurrent=True)
    N = ng.Axis(batch_size, batch=True)

    rnn_ng = Recurrent(hidden_size, init_func, activation=Tanh(),
                    time_axis=REC)

    inp_ng = ng.placeholder(axes=ng.Axes([Cin, REC, N]))

    # fprop graph
    out_ng = rnn_ng.configure(inp_ng)
    out_ng.input = True

    # bprop graph
    dWxh_ng = ng.deriv(out_ng, rnn_ng.W_input)
    dWhh_ng = ng.deriv(out_ng, rnn_ng.W_recur)

    # fprop on random inputs
    input_value = rng.uniform(-1, 1, inp_ng.axes)

    fprop_neon = executor(out_ng, inp_ng)(input_value)

    # after the rnn graph has been executed, can get the W values
    Wxh_neon = rnn_ng.W_input.value.get(None)
    Whh_neon = rnn_ng.W_recur.value.get(None)
    bh_neon = rnn_ng.b.value.get(None)

    # bprop on random errors
    error_value = rng.uniform(-1, 1, out_ng.axes)

    dWxh_neon = executor(dWxh_ng, out_ng)(error_value)
    dWhh_neon = executor(dWhh_ng, out_ng)(error_value)

    # ========= reference model ==========
    input_shape = (input_size, seq_len * batch_size)
    output_shape = (hidden_size, seq_len * batch_size)

    # generate random deltas tensor
    deltas = np.random.randn(*output_shape)

    # the reference code expects these shapes:
    # input_shape: (seq_len, input_size, batch_size)
    # output_shape: (seq_len, hidden_size, batch_size)
    deltas_ref = deltas.copy().T.reshape(
        seq_len, batch_size, hidden_size).swapaxes(1, 2)

    inp_ref = input_value.transpose([1, 0, 2])

    # reference numpy RNN
    rnn_ref = RefRecurrent(input_size, hidden_size)
    rnn_ref.Wxh[:] = Wxh_neon
    rnn_ref.Whh[:] = Whh_neon
    rnn_ref.bh[:] = bh_neon.reshape(rnn_ref.bh.shape)

    (dWxh_ref, dWhh_ref, db_ref, h_ref_list,
     dh_ref_list, d_out_ref) = rnn_ref.lossFun(inp_ref, deltas_ref)

    # comparing outputs
    neon_logger.display('====Verifying hidden states====')
    np.testing.assert_allclose(fprop_neon[:,:,0], h_ref_list, rtol=0.0, atol=1.0e-5)
    neon_logger.display('fprop is verified')

    return


if __name__ == '__main__':
    from neon.backends import gen_backend
    be = gen_backend(backend='dataloader')

    seq_len, input_size, hidden_size, batch_size = (5, 3, 6, 1)
    init = Uniform(low=-0.08, high=0.08)
    check_rnn(seq_len, input_size, hidden_size, batch_size, init)
