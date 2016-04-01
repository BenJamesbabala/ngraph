import geon.backends.graph.graph as graph

absolute = graph.absolute
add = graph.add
cos = graph.cos
divide = graph.divide
dot = graph.dot
empty = graph.empty
exp = graph.exp
log = graph.log
maximum = graph.maximum
minimum = graph.minimum
multiply = graph.multiply
negative = graph.negative
ones = graph.ones
reciprocal = graph.reciprocal
reshape = graph.reshape
sig = graph.sig
sin = graph.sin
sqrt = graph.sqrt
square = graph.square
subtract = graph.subtract
tanh = graph.tanh
transpose = graph.transpose
zeros = graph.zeros


deriv = graph.deriv
input = graph.input
range = graph.range

def relu(x,out):
    maximum(x, 0, out)

iterate = graph.iterate


