from neon.util.argparser import NeonArgparser
from neon.data import ImageLoader
import geon.backends.graph.dataloaderbackend

import geon.backends.graph.defmod as be
import geon.backends.graph.graph as graph
import geon.backends.graph.evaluation as evaluation
import numpy as np


# noinspection PyPep8Naming
def L2(x):
    return be.dot(x, x)


class MyRnn(be.Model):

    def __init__(self, **kargs):
        super(MyRnn, self).__init__(**kargs)
        # g: graph node root namespace
        g = self.graph

        # Define the axes
        g.N = be.Axis()
        g.T = be.Axis(dependents=(g.N,))
        g.X = be.Axis()
        g.Y = be.Axis()
        g.H = be.Axis()

        # Define the inputs.
        g.x = be.Tensor(axes=(g.X, g.T, g.N))
        # This would only be used for training or evaluation
        g.y_ = be.Tensor(axes=(g.Y, g.T, g.N))

        # Recursive computation of the hidden state.
        # Axes for defining position roles
        h = be.RecursiveTensor(axes=(g.H, g.T, g.N))
        h[:, 0] = be.Parameter(axes=(g.H,))
        HWh = be.Parameter(axes=(g.H, g.H))
        HWx = be.Parameter(axes=(g.X, g.H))
        Hb = be.Parameter(axes=(g.H,))

        g.t = be.Variable(g.T)
        h[:, g.t+1] = be.sig(be.dot(h[:, g.t], HWh)+be.dot(g.x[g.T], HWx)+Hb)

        YW = be.Parameter(axes=(g.H, g.Y))
        Yb = be.Parameter(axes=(g.Y))
        # This is what we would want for inference
        g.y = be.tanh(be.dot(h, YW)+Yb)

        e = g.y-g.y_
        # This is what we want for training, perhaps added to a parameter regularization
        g.error = be.dot(e, e)/e.size

        # L2 regularizer of parameters
        reg = None
        for param in be.find_all(types=be.Parameter, used_by=g.error):
            l2 = L2(param)
            if reg is None:
                reg = l2
            else:
                reg = reg + l2
        g.loss = g.error + .01 * reg

    @be.with_graph_context
    @be.with_environment
    def dump(self):
        for _ in be.get_all_defs():
            print(_)


MyRnn().dump()