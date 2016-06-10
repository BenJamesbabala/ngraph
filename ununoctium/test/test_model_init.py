#!/usr/bin/env python
# ----------------------------------------------------------------------------
# Copyright 2015 Nervana Systems Inc.
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
# run the example:
#
# test_model_init.py -r 0
#
# should produce sth like this:
#
# epoch: -1 time: 8.49s train_error: 0.00 test_error: 89.48 loss: 0.000
# epoch: 0 time: 59.21s train_error: 72.90 test_error: 68.41 train_loss: 2.940
# epoch: 1 time: 57.59s train_error: 67.16 test_error: 66.04 train_loss: 2.754
# epoch: 2 time: 57.65s train_error: 65.62 test_error: 65.07 train_loss: 2.704
# epoch: 3 time: 58.83s train_error: 64.68 test_error: 64.20 train_loss: 2.671
# epoch: 4 time: 58.53s train_error: 63.87 test_error: 64.12 train_loss: 2.648
# epoch: 5 time: 57.59s train_error: 63.62 test_error: 63.00 train_loss: 2.636
# epoch: 6 time: 58.80s train_error: 63.35 test_error: 63.39 train_loss: 2.621
# epoch: 7 time: 57.68s train_error: 63.06 test_error: 63.28 train_loss: 2.609
# epoch: 8 time: 57.64s train_error: 62.72 test_error: 62.29 train_loss: 2.595
# epoch: 9 time: 58.53s train_error: 62.56 test_error: 62.92 train_loss: 2.588

from neon.util.argparser import NeonArgparser
from neon.data import ImageLoader
import geon.backends.graph.dataloaderbackend
from neon.initializers import Uniform, Constant

import geon.backends.graph.funs as be
import geon.backends.graph.graph as graph
import geon.backends.graph.evaluation as evaluation

import numpy as np
from timeit import default_timer

# parse the command line arguments (generates the backend)
parser = NeonArgparser(__doc__)
parser.set_defaults(backend='dataloader')
parser.add_argument('--subset_pct', type=float, default=100,
                    help='subset of training dataset to use (percentage)')
args = parser.parse_args()

@be.with_name_context
def linear(params, x, x_axes, axes, batch_axes=(), init=None, bias=None):
    params.weights = be.Parameter(axes=axes + x_axes - batch_axes, init=init)
    result = be.dot(params.weights, x)
    if bias is not None:
        params.bias = be.Parameter(axes=axes, init=bias)
        result = result + params.bias
    return result

def affine(x, activation, batch_axes=None, **kargs):
    return activation(linear(x, batch_axes=batch_axes, **kargs), batch_axes=batch_axes)


@be.with_name_context
def mlp(params, x, activation, x_axes, shape_spec, axes, **kargs):
    value = x
    last_axes = x_axes
    with be.layers_named('L') as layers:
        for hidden_activation, hidden_axes, hidden_shapes in shape_spec:
            for shape in hidden_shapes:
                with be.next_layer(layers) as layer:
                    layer.axes = tuple(be.Axis(like=axis) for axis in hidden_axes)
                    for axis, length in zip(layer.axes, shape):
                        axis.length = length
                    value = affine(value, activation=hidden_activation, x_axes=last_axes, axes=layer.axes, **kargs)
                    last_axes = value.axes
        with be.next_layer(layers):
            value = affine(value, activation=activation, x_axes=last_axes, axes=axes, **kargs)
    return value

def cross_entropy(pred, t):
    """
    :param pred:  Estimate
    :param t: Actual 1-hot data
    :return:
    """
    return -be.sum(be.log(pred) / np.log(2.0) * t)


class MyTest(be.Model):
    def __init__(self, **kargs):
        super(MyTest, self).__init__(**kargs)
        g = self.graph

        g.C = be.Axis()
        g.H = be.Axis()
        g.W = be.Axis()
        g.N = be.Axis()
        g.Y = be.Axis()

        g.x = be.input(axes=(g.C, g.H, g.W, g.N))
        g.y = be.input(axes=(g.Y, g.N))

        layers = [(be.tanh, (g.Y,), [(200,)])]

        uni = Uniform(-0.1, 0.1)
        g.value = mlp(g.x, activation=be.softmax, x_axes=g.x.axes, shape_spec=layers, axes=g.y.axes, batch_axes=(g.N,),
                      init=uni)

        g.loss = cross_entropy(g.value, g.y)

    @be.with_graph_context
    def get_initial_params(self, train, test):
        with be.bound_environment() as env:
            g = self.graph
            g.N.length = train.bsz
            c, h, w = train.shape
            g.C.length = c
            g.H.length = h
            g.W.length = w
            g.Y.length = train.nclasses

            g.params = g.value.parameters()

            enp = evaluation.NumPyEvaluator(results=[self.graph.value] + g.params)
            enp.initialize()

            for mb_idx, (xraw, yraw) in enumerate(train):
                g.x.value = be.ArrayWithAxes(xraw.array, shape=(train.shape, train.bsz), axes=(g.C, g.H, g.W, g.N))
                g.y.value = be.ArrayWithAxes(yraw.array, shape=(train.nclasses, train.bsz), axes=(g.Y, g.N))
                vals = enp.evaluate()
                break

            for para in g.params:
                # if "bias" not in para.name and vals[para].array.shape[0] == 10:
                # if vals[para].array.shape[1] == 10:
                print(para.name)
                print(vals[para].array.shape)
                print(vals[para].array)

    @be.with_graph_context
    def train(self, train, test):
        with be.bound_environment() as env:
            g = self.graph
            g.N.length = train.bsz
            c, h, w = train.shape
            g.C.length = c
            g.H.length = h
            g.W.length = w
            g.Y.length = train.nclasses

            learning_rate = be.input(axes=())
            g.params = g.loss.parameters()
            derivs = [be.deriv(g.loss, param) for param in g.params]

            updates = be.doall(
                all=[be.decrement(param, learning_rate * deriv) for param, deriv in zip(g.params, derivs)])

            enp = evaluation.NumPyEvaluator(results=[self.graph.value, g.loss, updates] + derivs + g.params)
            enp.initialize()

            start_test = default_timer()
            test_error = self.test(env, test, True)
            print('epoch: {:d} time: {:.2f}s train_error: {:.2f} test_error: {:.2f} loss: {:.3f}'.
                  format(-1, default_timer() - start_test, 0, test_error, 0))

            for epoch in range(args.epochs):
                # TODO: need to fix that the processed data does not equal to the actual number of the data

                start_train = default_timer()

                train_loss = 0
                train_error = 0
                n_bs = 0
                nprocessed = 0
                learning_rate.value = be.ArrayWithAxes(.01/128, shape=(), axes=())
                for mb_idx, (xraw, yraw) in enumerate(train):
                    g.x.value = be.ArrayWithAxes(xraw.array, shape=(train.shape, train.bsz), axes=(g.C, g.H, g.W, g.N))
                    g.y.value = be.ArrayWithAxes(yraw.array, shape=(train.nclasses, train.bsz), axes=(g.Y, g.N))

                    vals = enp.evaluate()

                    train_loss += vals[g.loss].array / train.bsz
                    train_error += np.sum(np.not_equal(np.argmax(vals[g.value].array, axis=0),
                                                       np.argmax(yraw.array, axis=0))) / float(train.bsz)
                    n_bs += 1
                    nprocessed += xraw.array.shape[1]
                    # print(str(mb_idx) + " " + str(nprocessed) + " " + str(train.bsz))

                train_loss /= n_bs
                train_error = train_error / n_bs * 100
                test_error = self.test(env, test)

                print('epoch: {:d} time: {:.2f}s train_error: {:.2f} test_error: {:.2f} train_loss: {:.3f}'.format(
                    epoch, default_timer() - start_train, train_error, test_error, train_loss))
                train.reset()

    @be.with_graph_context
    def test(self, env, test, printParam=False):
        g = self.graph
        with be.bound_environment(env):
            enp = evaluation.NumPyEvaluator(results=[self.graph.value] + g.params)

            test_error = 0
            n_bs = 0
            for mb_idx, (xraw, yraw) in enumerate(test):
                # TODO: need to fix that the processed data does not equal to the actual number of the data
                g.x.value = be.ArrayWithAxes(xraw.array, shape=(test.shape, test.bsz),
                                             axes=(g.C, g.H, g.W, g.N))
                g.y.value = be.ArrayWithAxes(yraw.array, shape=(test.nclasses, test.bsz), axes=(g.Y, g.N))
                vals = enp.evaluate()

                if printParam and mb_idx == 0:
                    for para in g.params:
                        # if "bias" not in para.name and vals[para].array.shape[0] == 10:

                        print(para.name)
                        print(vals[para].array.shape)
                        print(vals[para].array)

                    print(g.x.value.array[0][0][0])
                    print(g.y.value.array.shape)
                    print(g.y.value.array[:,1])

                test_error += np.sum(np.not_equal(np.argmax(vals[g.value].array, axis=0),
                                                  np.argmax(yraw.array, axis=0)))
                n_bs += 1

            return test_error / float(test.bsz) / n_bs * 100

# data provider
imgset_options = dict(inner_size=32, scale_range=40, aspect_ratio=110,
                      repo_dir=args.data_dir, subset_pct=args.subset_pct)
train = ImageLoader(set_name='train', shuffle=False, do_transforms=False, **imgset_options)
test = ImageLoader(set_name='validation', shuffle=False, do_transforms=False, **imgset_options)

print(train.ndata)
print(train.shape)

args.epochs = 10     # set epochs to zero, just test the initial value

geon_model = MyTest()
# geon_model.get_initial_params(train, test)
geon_model.train(train, test)
