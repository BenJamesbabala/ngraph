import numpy as np

from geon.backends.graph.names import NameableValue, name_scope
from geon.backends.graph.environment import bound_environment, captured_ops
from geon.backends.graph.graph import GraphComponent
import geon.backends.graph.axis as ax
from geon.backends.graph.container import Sequential, Tree, SingleOutputTree
import geon.backends.graph.funs as be



class Model(GraphComponent):
    def __init__(self, layers, name=None, optimizer=None, **kargs):
        super(Model, self).__init__(**kargs)
        self.initialized = False
        self.name = name

        self.optimizer = optimizer

        graph = self.graph

        # Wrap the list of layers in a Sequential container if a raw list of layers
        if type(layers) in (Sequential, Tree, SingleOutputTree):
            self.layers = layers
        else:
            self.layers = Sequential(layers)


    def initialize(self, dataset, cost=None):
        """
        Propagate shapes through the layers to configure, then allocate space.

        Arguments:
            dataset (NervanaDataIterator): Dataset iterator to perform initialization on
            cost (Cost): Defines the function which the model is minimizing based
                         on the output of the last layer and the input labels.
        """
        if self.initialized:
            return

        # Propagate shapes through the layers to configure
        output = self.layers.configure(dataset)

        if cost is not None:
            self.graph.cost = cost.get_cost(output, self.graph.target)

        self.initialized = True
        return output


    def fit(self, dataset, input_axes, target_axes, cost, optimizer, num_epochs, callbacks):
        """
        Trains the model parameters on a dataset by minimizing the cost function through
        gradient descent and updates the layer weights according to a learning rule
        defined in optimizer.

        Arguments:
            dataset (NervanaDataIterator): An iterable of minibatches where each
                element is a (x, y) tuple where x is the input data and y are the labels.
                x is of dimension (feature_size, batch_size)
                y is of dimension (label_size, batch_size)
                Length of the iterator is num_batches which is num_data / batch_size.
            cost (Cost): Defines the function which the model is minimizing based
                         on the output of the last layer and the input labels.
            optimizer (Optimizer): Defines the learning rule for updating the model parameters.
            num_epochs: Number of times to iterate over the dataset.
            callbacks (Callbacks): Defines callbacks to run at the end of each mini-batch / epoch.
        """
        self.nbatches = dataset.nbatches
        self.ndata = dataset.ndata
        self.optimizer = optimizer



        with bound_environment(environment=self.environment):
            with name_scope(name_scope=self.graph):
                self.ops = []
                with captured_ops(self.ops):
                    # TODO Move this axis initialization into a util
                    batch_input_axes = input_axes + (ax.N,)
                    batch_target_axes = target_axes + (ax.N,)
                    be.set_batch_axes([ax.N])
                    self.graph.input = be.placeholder(axes=batch_input_axes)
                    self.graph.target = be.placeholder(axes=batch_target_axes)
                    for axis, length in zip(input_axes, dataset.shape):
                        axis.length = length
                    for axis, length in zip(target_axes, (dataset.nclasses,)):
                        axis.length = length
                    ax.N.length = dataset.bsz

                    self.initialize(self.graph.input, cost)


        # TODO finish this
        if False:
            callbacks.on_train_begin(num_epochs)
            while self.epoch_index < num_epochs and not self.finished:
                self.nbatches = dataset.nbatches

                callbacks.on_epoch_begin(self.epoch_index)

                self._epoch_fit(dataset, callbacks)

                callbacks.on_epoch_end(self.epoch_index)

                self.epoch_index += 1

            callbacks.on_train_end()

    def _epoch_fit(self, dataset, callbacks):
        """
        Helper function for fit which performs training on a dataset for one epoch.

        Arguments:
            dataset (NervanaDataIterator): Dataset iterator to perform fit on
        """
        epoch = self.epoch_index
        self.total_cost[:] = 0
        # iterate through minibatches of the dataset
        for mb_idx, (x, t) in enumerate(dataset):
            callbacks.on_minibatch_begin(epoch, mb_idx)
            self.be.begin(Block.minibatch, mb_idx)

            x = self.fprop(x)

            self.total_cost[:] = self.total_cost + self.cost.get_cost(x, t)

            # deltas back propagate through layers
            # for every layer in reverse except the 0th one
            delta = self.cost.get_errors(x, t)

            self.bprop(delta)
            self.optimizer.optimize(self.layers_to_optimize, epoch=epoch)

            self.be.end(Block.minibatch, mb_idx)
            callbacks.on_minibatch_end(epoch, mb_idx)

        # now we divide total cost by the number of batches,
        # so it was never total cost, but sum of averages
        # across all the minibatches we trained on
        self.total_cost[:] = self.total_cost / dataset.nbatches


    def fprop(self, x, inference=False):
        """
        Forward propagates a minibatch x through the model.

        Arguments:
            x (Tensor): Input minibatch data.
            inference (bool): Flag for performing training or inference
                Only affects batch norm and dropout layers.

        Returns:
            Tensor: the output of the final layer in the model
        """
        return self.layers.fprop(x, inference)
