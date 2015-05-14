# neural net based on http://deeplearning.net/tutorial/code/mlp.py

import theano
import numpy as np
import theano.tensor as T

theano.config.openmp = False  # they say that using openmp becomes efficient only with "very large scale convolution"
theano.config.floatX = 'float32'


class Layer(object):
    def __init__(self, input, n_inputs, n_nodes):
        """
        Initialize a neural network layer.

        :param input: inputs from previous layer of shape (batch_size, n_inputs)
        :type input: theano.tensor.dmatrix

        :param n_inputs: number of inputs to single neuron (number of nodes in
            previous layer)
        :type n_inputs: int

        :param n_nodes: number of nodes in the layer. Also the size of output
        :type n_nodes: int
        """
        self.input = input
        # from RMSProp
        weight_bound = np.sqrt(6. / (n_inputs + n_nodes))
        # weights matrix of size n_inputs * n_nodes
        # each column (total: n_nodes) represents the weights from the input
        # units to the i-th unit
        weights_values = np.asarray(np.random.uniform(
            high=weight_bound,
            low=-weight_bound,
            size=(n_inputs, n_nodes)
        ), dtype=theano.config.floatX)
        self.weights = theano.shared(
            value=weights_values,
            name='weights',
            borrow=True,  # use "reference", not copy (http://deeplearning.net/software/theano/tutorial/aliasing.html#borrowing-when-creating-shared-variables)
        )
        # bias term
        bias_values = np.zeros((n_nodes,), dtype=theano.config.floatX)
        self.bias = theano.shared(value=bias_values, name='bias', borrow=True)
        # all the variables that can change during learning
        self.params = [self.weights, self.bias]

        # output
        # dot - returns inner product of params
        # For 2-D arrays it is equivalent to matrix multiplication
        # http://www.deeplearning.net/software/theano/library/tensor/basic.html#theano.tensor.dot
        # http://en.wikipedia.org/wiki/Matrix_multiplication#Inner_product
        self.output = T.dot(self.input, self.weights) + self.bias

    def errors(self, y):
        """
        Return the error made in predicting the output value
        :param y: vector that gives for each node the value we wished to obtain
        :type y: theano.tensor.TensorType
        """
        return T.mean(np.abs(self.output - y))


class RectifiedLayer(Layer):
    """
    Layer with minimum values of output equal to 0.
    """
    def __init__(self, *args, **kwargs):
        super(RectifiedLayer, self).__init__(*args, **kwargs)
        self.threshold = 0
        # Output is rectified
        self.output = self.rectify(self.output)

    def rectify(self, result):
        """
        Return max of result and threshold.
        """
        self._lin_output = result
        above_threshold = result > self.threshold
        return above_threshold * (result - self.threshold)


class OutputLayer(Layer):
    pass


class NeuralNet(object):
    discount_factor = 0.95
    learning_rate = 0.0001
    l1_weight = 0.0
    l2_weight = 0.0001

    # RMSprop params
    rmsprop_rho = 0.9
    rmsprop_epsilon = 1e-6

    # type of x (input) variable
    x_type = T.fmatrix
    y_type = T.fmatrix

    def __init__(
        self,
        n_inputs,  # number of inputs to neural net
        architecture,
        **kwargs
    ):
        for k, v in kwargs.iteritems():
            setattr(self, k, v)
        # create theano variables corresponding to input_batch (x) and output
        # of the network (y)
        x = self.x_type('x')
        y = self.y_type('y')

        self.layers = []
        self.params = []
        prev_layer = None
        prev_layer_size = None

        # create layers based on architecture
        for i, layer_size in enumerate(architecture):
            # params: inputs, number of inputs for single neuron, number of neurons
            layer_type = OutputLayer if i == len(architecture) - 1 else RectifiedLayer
            layer = layer_type(
                prev_layer.output if prev_layer else x,
                prev_layer_size or n_inputs,
                layer_size
            )
            self.layers.append(layer)
            prev_layer = layer
            prev_layer_size = layer_size
            self.params.extend(layer.params)

        self.output_layer = layer

        # define regularization terms, for some reason we only take in count
        # the weights, not biases) linear regularization term, useful for
        # having many weights zero
        self.l1 = sum([abs(l.weights).sum() for l in self.layers])

        # square regularization term, useful for forcing small weights
        self.l2_sqr = sum([(l.weights ** 2).sum() for l in self.layers])

        # define the cost function
        self.cost = (
            self.l1_weight * self.l1 +
            self.l2_weight * self.l2_sqr +
            self.output_layer.errors(y)
        )

        updates = self._get_updates()

        # we need another set of theano variables (other than x and y) to use
        # in train and predict functions
        temp_x = self.x_type('temp_x')
        temp_y = self.y_type('temp_y')

        # define the training operation as applying the updates calculated
        # given temp_x and temp_y
        self.train = theano.function(
            inputs=[temp_x, temp_y],
            outputs=[self.cost],
            updates=updates,
            givens={  # specific substitutions to make in the computation graph
               x: temp_x,  # temp_x will replace x
               y: temp_y,  # temp_y will replace y
            },
        )

        self.predict = theano.function(
            inputs=[temp_x],
            outputs=[self.output_layer.output],
            givens={
                x: temp_x,
            },
        )

    def _get_updates(self):
        """
        Calculate params updates using RMSProp

        Based on:
        http://nbviewer.ipython.org/github/udibr/Theano-Tutorials/blob/master/notebooks/4_modern_net.ipynb
        https://www.youtube.com/watch?v=O3sxAc4hxZU
        """
        # define gradient calculation
        grads = T.grad(self.cost, self.params)

        # Define how much we need to change the parameter values
        # actual RMSProp
        updates = []
        for param_i, gparam_i in zip(self.params, grads):
            # acc is allocated for each parameter (param_i) with 0 values with the shape of p
            acc = theano.shared(param_i.get_value() * 0.)
            acc_new = self.rmsprop_rho * acc + (1 - self.rmsprop_rho) * gparam_i ** 2
            gradient_scaling = T.sqrt(acc_new + self.rmsprop_epsilon)
            gparam_i = gparam_i / gradient_scaling
            updates.append((acc, acc_new))
            updates.append((param_i, param_i - self.learning_rate * gparam_i))
        return updates

    def train_minibatch(self, minibatch):
        """
        Train minibatch using Q-learning
        """
        prestates, actions, rewards, poststates, terminals = minibatch

        # predict Q-values for prestates, so we can keep Q-values for other
        # actions unchanged
        qvalues = self.predict(prestates)[0]
        # predict Q-values for poststates
        post_qvalues = self.predict(poststates)[0]
        # take maximum Q-value of all actions
        max_qvalues = np.max(post_qvalues, axis=1)
        # update the Q-values for the actions we actually performed
        for i, action in enumerate(actions):
            qvalues[i][action] = rewards[i] + self.discount_factor * max_qvalues[i]
        cost = self.train(prestates, qvalues)[0]
        return cost

    def predict_best_action(self, state):
        """
        Returns the action with the highest Q-value
        """
        q_values = self.predict([state])[0]
        return np.argmax(q_values)