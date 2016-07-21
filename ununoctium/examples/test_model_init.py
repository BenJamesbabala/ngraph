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

from __future__ import division, print_function
from builtins import range, zip
from geon.backends.graph.graphneon import *  # noqa

import numpy as np
from timeit import default_timer

# parse the command line arguments (generates the backend)
parser = NeonArgparser(__doc__)
parser.set_defaults(backend='dataloader')
parser.add_argument('--subset_pct', type=float, default=100,
                    help='subset of training dataset to use (percentage)')
# MPI flag
parser.add_argument('-mpi_flag', action='store_true')

args = parser.parse_args()


@be.with_name_scope
def linear(ns, x, axes, init=None, bias=None):
    ns.weights = be.Variable(axes=be.linear_map_axes(
        be.sample_axes(x.axes), be.sample_axes(axes)), init=init)
    result = be.dot(ns.weights, x)
    if bias is not None:
        ns.bias = be.Variable(axes=result.axes.sample, init=bias)
        result = result + ns.bias
    return result


@be.with_name_scope
def mlp(ns, x, y):
    nns_axes = (be.AxisVar(like=ax.Y, length=200),)
    value = be.tanh(linear(x, axes=nns_axes, init=Uniform(-0.1, 0.1)))
    value = be.softmax(linear(value, axes=y.axes, init=Uniform(-0.1, 0.1)))

    return value


class MyTest(be.Model):

    def __init__(self, **kargs):
        super(MyTest, self).__init__(**kargs)
        g = self.graph

        be.set_batch_axes([ax.N])
        be.set_phase_axes([ax.Phi])

        g.x = be.placeholder(axes=(ax.C, ax.H, ax.W, ax.N))
        g.y = be.placeholder(axes=(ax.Y, ax.N))

        g.value = mlp(g.x, g.y)

        g.loss = be.cross_entropy_multi(g.value, g.y)

    @be.with_graph_scope
    def train(self, train, test):
        with be.bound_environment() as env:
            graph = self.graph
            ax.N.length = train.bsz
            c, h, w = train.shape
            ax.C.length = c
            ax.H.length = h
            ax.W.length = w
            ax.Y.length = train.nclasses

            # TODO: learning_rate might be a variable rather than placeholder.
            learning_rate = be.placeholder(axes=())
            graph.params = graph.loss.parameters()
            derivs = [be.deriv(graph.loss, param) for param in graph.params]
            # check for the mpi_flag
            # if the flag is set, we add an AllReduce node after each derivs
            # node to synch up
            synced_derivs = []
            if args.mpi_flag:
                synced_derivs = [be.AllReduce(deriv) for deriv in derivs]
            else:
                synced_derivs = derivs

            updates = be.doall(
                all=[
                    be.assign(
                        param,
                        param -
                        learning_rate *
                        deriv) for param,
                    deriv in zip(
                        graph.params,
                        synced_derivs)])

            enp = be.NumPyTransformer(
                results=[
                    self.graph.value,
                    graph.loss,
                    updates] +
                synced_derivs +
                graph.params)

            for epoch in range(args.epochs):
                # TODO: need to fix that the processed data does not equal to
                # the actual number of the data
                start_train = default_timer()

                train_loss = 0
                train_error = 0
                n_bs = 0
                nprocessed = 0
                learning_rate.value = .1 / (1 + epoch) / train.bsz
                for mb_idx, (xraw, yraw) in enumerate(train):
                    graph.x.value = xraw
                    graph.y.value = yraw

                    vals = enp.evaluate()

                    train_loss += vals[graph.loss] / float(train.bsz)
                    train_error += np.sum(np.not_equal(np.argmax(
                        vals[graph.value], axis=0), np.argmax(yraw, axis=0))) / float(train.bsz)
                    n_bs += 1
                    nprocessed += xraw.shape[1]

                train_loss /= n_bs
                train_error = train_error / n_bs * 100
                test_error = self.test(env, test)

                print('epoch: {:d} time: {:.2f}s train_error: {:.2f} test_error: {:.2f} '.format(
                    epoch, default_timer() - start_train, float(train_error), test_error))

                # TODO: figure out why train_loss is not scalar

                train.reset()

    @be.with_graph_scope
    def test(self, env, test, printParam=False):
        graph = self.graph
        with be.bound_environment(env):
            enp = be.NumPyTransformer(
                results=[self.graph.value] + graph.params)

            test_error = 0
            n_bs = 0
            for mb_idx, (xraw, yraw) in enumerate(test):
                # TODO: need to fix that the processed data does not equal to
                # the actual number of the data
                graph.x.value = xraw
                graph.y.value = yraw
                vals = enp.evaluate()

                test_error += np.sum(
                    np.not_equal(
                        np.argmax(
                            vals[
                                graph.value], axis=0), np.argmax(
                            yraw, axis=0)))
                n_bs += 1

            return float(test_error / float(test.bsz) / n_bs * 100)

# data provider
imgset_options = dict(inner_size=32, scale_range=40, aspect_ratio=110,
                      repo_dir=args.data_dir, subset_pct=args.subset_pct)
train = ImageLoader(set_name='train', shuffle=False,
                    do_transforms=False, **imgset_options)
test = ImageLoader(set_name='validation', shuffle=False,
                   do_transforms=False, **imgset_options)


geon_model = MyTest()
geon_model.train(train, test)
