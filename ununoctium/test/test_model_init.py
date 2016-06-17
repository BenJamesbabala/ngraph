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
# epoch: -1 time: 0.70s train_error: 0.00 test_error: 89.29 loss: 0.000
# epoch: 0 time: 5.81s train_error: 72.14 test_error: 68.75 train_loss: 2.923
# epoch: 1 time: 5.84s train_error: 67.30 test_error: 65.87 train_loss: 2.760
# epoch: 2 time: 6.08s train_error: 66.15 test_error: 65.61 train_loss: 2.718
# epoch: 3 time: 6.11s train_error: 65.32 test_error: 64.88 train_loss: 2.695
# epoch: 4 time: 7.40s train_error: 64.84 test_error: 64.37 train_loss: 2.673
# epoch: 5 time: 5.96s train_error: 64.21 test_error: 63.67 train_loss: 2.646
# epoch: 6 time: 5.94s train_error: 63.59 test_error: 63.57 train_loss: 2.633
# epoch: 7 time: 5.89s train_error: 63.42 test_error: 63.36 train_loss: 2.617
# epoch: 8 time: 6.36s train_error: 62.89 test_error: 64.12 train_loss: 2.606
# epoch: 9 time: 5.81s train_error: 62.86 test_error: 63.13 train_loss: 2.594


from neon.util.argparser import NeonArgparser
from neon.data import ImageLoader
from neon.initializers import Uniform, Constant

import geon.backends.graph.funs as be
import geon.backends.graph.graph as graph
import geon.backends.graph.evaluation as evaluation
import geon.backends.graph.dataloaderbackend

import numpy as np
from timeit import default_timer

# parse the command line arguments (generates the backend)
parser = NeonArgparser(__doc__)
parser.set_defaults(backend='dataloader')
parser.add_argument('--subset_pct', type=float, default=100,
                    help='subset of training dataset to use (percentage)')
args = parser.parse_args()

@be.with_name_scope
def linear(ns, x, axes, init=None, bias=None):
    ns.weights = be.Parameter(axes=be.linear_map_axes(be.sample_axes(x.axes), be.sample_axes(axes)), init=init)
    result = be.dot(ns.weights, x)
    if bias is not None:
        ns.bias = be.Parameter(axes=result.axes.sample, init=bias)
        result = result + ns.bias
    return result

def affine(x, activation, **kargs):
    return activation(linear(x, **kargs))


@be.with_name_scope
def mlp(ns, x, activation, shape_spec, axes, **kargs):
    value = x
    with be.name_scope_list('L') as name_scopes:
        for hidden_activation, hidden_axes, hidden_shapes in shape_spec:
            for shape in hidden_shapes:
                with be.next_name_scope(name_scopes) as nns:
                    nns.axes = tuple(be.AxisVar(like=axis, length=length) for axis, length in zip(hidden_axes, shape))
                    value = affine(value, activation=hidden_activation, axes=nns.axes, **kargs)
        with be.next_name_scope(name_scopes):
            value = affine(value, activation=activation, axes=axes, **kargs)
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

        g.C = be.AxisVar()
        g.H = be.AxisVar()
        g.W = be.AxisVar()
        g.N = be.AxisVar()
        g.Y = be.AxisVar()

        be.set_batch_axes([g.N])

        g.x = be.input(axes=(g.C, g.H, g.W, g.N))
        g.y = be.input(axes=(g.Y, g.N))

        layers = [(be.tanh, (g.Y,), [(200,)])]

        uni = Uniform(-0.1, 0.1)
        g.value = mlp(g.x, activation=be.softmax, shape_spec=layers, axes=g.y.axes, init=uni)

        g.loss = cross_entropy(g.value, g.y)

    @be.with_graph_scope
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

    @be.with_graph_scope
    def train(self, train, test):
        with be.bound_environment() as env:
            graph = self.graph
            graph.N.length = train.bsz
            c, h, w = train.shape
            graph.C.length = c
            graph.H.length = h
            graph.W.length = w
            graph.Y.length = train.nclasses

            learning_rate = be.input(axes=())
            graph.params = graph.loss.parameters()
            derivs = [be.deriv(graph.loss, param) for param in graph.params]

            updates = be.doall(
                all=[be.decrement(param, learning_rate * deriv) for param, deriv in zip(graph.params, derivs)])

            enp = evaluation.NumPyEvaluator(results=[self.graph.value, graph.loss, updates] + derivs + graph.params)
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
                learning_rate.value = .1 / (1 + epoch) / train.bsz
                for mb_idx, (xraw, yraw) in enumerate(train):
                    graph.x.value = xraw.array
                    graph.y.value = yraw.array

                    vals = enp.evaluate()

                    train_loss += vals[graph.loss] / train.bsz
                    train_error += np.sum(np.not_equal(np.argmax(vals[graph.value], axis=0),
                                                       np.argmax(yraw.array, axis=0))) / float(train.bsz)
                    n_bs += 1
                    nprocessed += xraw.array.shape[1]
                    # print(str(mb_idx) + " " + str(nprocessed) + " " + str(train.bsz))

                train_loss /= n_bs
                train_error = train_error / n_bs * 100
                test_error = self.test(env, test)

                print('epoch: {:d} time: {:.2f}s train_error: {:.2f} test_error: {:.2f} train_loss: {:.3f}'.format(
                    epoch, default_timer() - start_train, float(train_error), test_error, float(train_loss)))
                train.reset()

    @be.with_graph_scope
    def test(self, env, test, printParam=False):
        graph = self.graph
        with be.bound_environment(env):
            enp = evaluation.NumPyEvaluator(results=[self.graph.value] + graph.params)

            test_error = 0
            n_bs = 0
            for mb_idx, (xraw, yraw) in enumerate(test):
                # TODO: need to fix that the processed data does not equal to the actual number of the data
                graph.x.value = xraw.array
                graph.y.value = yraw.array
                vals = enp.evaluate()

                if printParam and mb_idx == 0:
                    for para in graph.params:
                        # if "bias" not in para.name and vals[para].array.shape[0] == 10:

                        print(para.name)
                        print(vals[para].shape)
                        print(vals[para])

                    # print(g.x.value[0][0][0])
                    # print(g.y.value.shape)
                    # print(g.y.value[:,1])

                test_error += np.sum(np.not_equal(np.argmax(vals[graph.value], axis=0),
                                                  np.argmax(yraw.array, axis=0)))
                n_bs += 1

            return float(test_error / float(test.bsz) / n_bs * 100)

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
