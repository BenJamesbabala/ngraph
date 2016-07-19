from builtins import range, zip
from geon.backends.graph.funs import *
from geon.backends.graph.analysis import *

import mxnet as mx
import mxnet.symbol as sym

class GraphitiMLP(Model):
    def __init__(self, L, BS, bprop=True, **kargs):


        super(GraphitiMLP, self).__init__(**kargs)
        #Axes
        L = [AxisVar(length=N, name='L%d'% i) for i, N in enumerate(L)]
        BS = AxisVar(length=BS, name='BS')

        #Builds Network
        activations = [tanh for i in range(len(L)-2)] + [softmax]
        X = placeholder(axes=(L[0],BS), name = 'X')
        Y = placeholder(axes=(L[-1],), name = 'Y')
        W = [Variable(axes=(L_np1, L_n), name = 'W%d'%i) for i,(L_np1, L_n) in enumerate(zip(L[1:], L[:-1]))]
        A = []
        for i, f in enumerate(activations):
            Aim1 = A[i-1] if i>0 else X
            A.append(f(dot(W[i], Aim1)))
        Error = cross_entropy_multi(A[-1], Y)
        dW = [deriv(Error, w) for w in W]

        #Fusion analysis
        dataflow = DataFlowGraph(dW if bprop else [Error])
        fused = KernelFlowGraph(dataflow)
        #Liveness analysis
        liveness = fused.liveness()
        #Memory planing
        interference = InterferenceGraph(liveness)
        self.memory = color(interference)
        self.dataflow = dataflow
        fused.view()
        #interference.render('interference')

class MXNetMLP(Model):

    def __init__(self, L, BS, bprop=True, **kwargs):
        #Builds Network
        activations = ['tanh' for i in range(len(L)-2)]
        X = sym.Variable('X', shape=(BS, L[0]))
        Y = sym.Variable('Y', shape=(BS,))

        fc, act = [], [X]
        for i, nhid in enumerate(L[1:]):
            fc.append(sym.FullyConnected(data = act[-1], num_hidden = nhid))
            if i==len(L) - 2:
                act.append(sym.Activation(data = fc[-1], act_type = 'relu'))
            else:
                act.append(sym.SoftmaxOutput(data = fc[-1], label=Y, name = 'softmax'))
        net = act[-1]
        plan = net.simple_bind(ctx=mx.cpu(), grad_req='write' if bprop else 'null')
        
        #Memory internally allocated by MXNet
        #Casted to int internally (rounded down)
        #in average ~.5 smaller than the truth
        bias = .5
        self.memory = (int(plan.debug_str().split('\n')[-3].split()[1]) + bias)*1024**2
        #Memory required by arguments
        args = plan.arg_arrays
        if plan.grad_arrays: 
            args += plan.grad_arrays
        for x in args:
            self.memory += reduce(mul, x.shape, 1)*4
        
    
    
    

layers = [1024, 1200, 100]
batch = 32000
bprop = True

graphiti = GraphitiMLP(layers, batch, bprop)
mxnet = MXNetMLP(layers, batch, bprop)

print 'Graphiti: {:.2f} MiB'.format(graphiti.memory*1024**-2)
print 'MXNet:    {:.2f} MiB (+- 0.5)'.format(mxnet.memory*1024**-2)

