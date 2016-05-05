from contextlib import contextmanager
import weakref

import threading

__thread_data = threading.local()

def get_thread_data():
    return __thread_data


get_thread_data().naming = [None]


def get_thread_naming():
    return get_thread_data().naming


get_thread_data().environment = [None]


def get_thread_environment():
    return get_thread_data().environment


def get_current_environment():
    return get_thread_environment()[-1]


def push_current_environmnet(environmnet):
    get_thread_environment().append(environment)


def set_current_environment(environment):
    get_thread_environment()[-1] = environment


@contextmanager
def bound_environment(environment=None, create=True):
    if environment is None and create:
        environment = Environment(parent=get_current_environment())

    try:
        get_thread_environment().append(environment)
        yield(environment)
    finally:
        get_thread_environment().pop()


class Environment(object):
    def __init__(self, parent=None, **kargs):
        super(Environment, self).__init__(**kargs)
        self.parent = parent
        self.axis_values = weakref.WeakKeyDictionary()
        self.node_axes = weakref.WeakKeyDictionary()
        self.node_values = weakref.WeakKeyDictionary()

    def _chained_search(self, attr, key):
        env = self
        while True:
            try:
                return env.__getattribute__(attr)[key]
            except KeyError:
                env = env.parent
                if env is None:
                    raise

    def set_axis_value(self, axis, value):
        self.axis_values[axis] = value

    def get_axis_value(self, axis):
        return self._chained_search('axis_values', axis)

    def get_cached_node_axes(self, node):
        return self._chained_search('node_axes', node)

    def set_cached_node_axes(self, node, axes):
        self.node_axes[node] = axes

    def get_node_axes(self, node):
        try:
            return self.get_cached_node_axes(node)
        except KeyError:
            axes = node.axes.resolve(self)
            self.set_cached_node_axes(node, axes)
            return axes

    def get_node_value(self, node):
        return self._chained_search('node_values', node)

    def set_node_value(self, node, value):
        self.node_values[node] = value




