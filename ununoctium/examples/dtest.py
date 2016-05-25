import geon.backends.graph.defmod as nm


class Uniform(object):
    def __init__(self, low=0.0, high=1.0):
        self.low = low
        self.high = high

    def __call__(self, evaluator, value):
        evaluator.uniform(value, self.low, self.high)


@nm.with_name_context
def linear(m, x, x_axes, axes, batch_axes=(), init=None):
    m.weights = nm.Parameter(axes=axes + x_axes - batch_axes, init=init, tags='parameter')
    m.bias = nm.Parameter(axes=axes, init=init, tags='parameter')
    return nm.dot(m.weights, x) + m.bias


def affine(x, activation, batch_axes=None, **kargs):
    return activation(linear(x, batch_axes=batch_axes, **kargs), batch_axes=batch_axes)


@nm.with_name_context
def mlp(params, x, activation, x_axes, shape_spec, axes, **kargs):
    value = x
    last_axes = x_axes
    with nm.layers_named('L') as layers:
        for hidden_activation, hidden_axes, hidden_shapes in shape_spec:
            for layer, shape in zip(layers, hidden_shapes):
                layer.axes = tuple(nm.Axis(like=axis) for axis in hidden_axes)
                for axis, length in zip(layer.axes, shape):
                    axis.length = length
                value = affine(value, activation=hidden_activation, x_axes=last_axes, axes=layer.axes, **kargs)
                last_axes = value.axes
        layers.next()
        value = affine(value, activation=activation, x_axes=last_axes, axes=axes, **kargs)
    return value


# noinspection PyPep8Naming
def L2(x):
    return nm.dot(x, x)


def cross_entropy(y, t):
    """

    :param y:  Estimate
    :param t: Actual 1-hot data
    :return:
    """
    return -nm.sum(nm.log(y) * t)


class MyTest(nm.Model):
    def __init__(self, **kargs):
        super(MyTest, self).__init__(**kargs)

        uni = Uniform(-.01, .01)

        g = self.graph

        g.C = nm.Axis()
        g.H = nm.Axis()
        g.W = nm.Axis()
        g.N = nm.Axis()
        g.Y = nm.Axis()

        g.x = nm.Tensor(axes=(g.C, g.H, g.W, g.N))
        g.y = nm.Tensor(axes=(g.Y, g.N))

        layers = [(nm.tanh, (g.H, g.W), [(16, 16)] * 1 + [(4, 4)])]

        g.value = mlp(g.x, activation=nm.softmax, x_axes=g.x.axes, shape_spec=layers, axes=g.y.axes, batch_axes=(g.N,),
                      init=uni)

        g.error = cross_entropy(g.value, g.y)

        # L2 regularizer of parameters
        reg = None
        for param in nm.find_all(types=nm.Parameter, tags='parameter', used_by=g.value):
            l2 = L2(param)
            if reg is None:
                reg = l2
            else:
                reg = reg + l2
        g.loss = g.error + .01 * reg

    @nm.with_graph_context
    @nm.with_environment
    def dump(self):
        for _ in nm.get_all_defs():
            print('{s} # File "{filename}", line {lineno}'.format(s=_, filename=_.filename, lineno=_.lineno))


MyTest().dump()
