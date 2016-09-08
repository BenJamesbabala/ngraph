from __future__ import division, print_function

import geon as ng
import gendata

ax = ng.NameScope(name="ax")

ax.W = ng.Axis()
ax.H = ng.Axis()
ax.N = ng.Axis()

X = ng.placeholder(axes=ng.Axes([ax.W, ax.H, ax.N]))
Y = ng.placeholder(axes=ng.Axes([ax.N]))
alpha = ng.placeholder(axes=ng.Axes())

W = ng.Variable(axes=ng.Axes([ax.W, ax.H]), initial_value=0)
b = ng.Variable(axes=ng.Axes(), initial_value=0)

Y_hat = ng.sigmoid(ng.dot(W, X) + b)
L = ng.cross_entropy_binary(Y_hat, Y) / ng.tensor_size(Y_hat)

updates = [ng.assign(v, v - alpha * ng.deriv(L, v) / ng.tensor_size(Y_hat))
           for v in L.variables()]

all_updates = ng.doall(updates)

ax.W.length = 4
ax.H.length = 1
ax.N.length = 128

g = gendata.MixtureGenerator([.5, .5], (ax.W.length, ax.H.length))
XS, YS = g.gen_data(ax.N.length, 10)
EVAL_XS, EVAL_YS = g.gen_data(ax.N.length, 4)

transformer = ng.NumPyTransformer()
update_fun = transformer.computation([L, W, b, all_updates], alpha, X, Y)
eval_fun = transformer.computation(L, X, Y)

for i in range(10):
    for xs, ys in zip(XS, YS):
        loss_val, w_val, b_val, _ = update_fun(5.0 / (1 + i), xs, ys)
        print("W: %s, b: %s, loss %s" % (w_val, b_val, loss_val))

total_loss = 0
for xs, ys in zip(EVAL_XS, EVAL_YS):
    loss_val = eval_fun(xs, ys)
    total_loss += loss_val
print("Loss: {}".format(total_loss / len(xs)))
