import numbers
import weakref
import collections
from contextlib import contextmanager
from functools import wraps

from geon.backends.graph.errors import NameException
from geon.backends.graph.environment import get_current_environment, get_current_naming, get_thread_naming


class NameableValue(object):
    """A value with a name that can be set."""
    def __init__(self, name=None, **kargs):
        super(NameableValue, self).__init__(**kargs)
        self.__name = name

    @property
    def name(self):
        return self.__name

    @name.setter
    def name(self, name):
        self.__name = name


class Naming(NameableValue):
    def __init__(self, **kargs):
        super(Naming, self).__init__(**kargs)
        pass

    def __setattr__(self, name, value):
        super(Naming, self).__setattr__(name, value)
        if isinstance(value, NameableValue):
            myname = self.name
            value.name = myname + '.' + name

        elif isinstance(value, tuple):
            for v in value:
                if isinstance(v, NameableValue):
                    vname = v.name[v.name.rfind('.')+1:]
                    self.__setattr__(vname, v)




@contextmanager
def name_context(name):
    try:
        naming = Naming()
        tnaming = get_thread_naming()
        tnaming[-1].__setattr__(name, naming)
        tnaming.append(naming)
        yield(naming)
    finally:
        tnaming.pop()


class NamedList(NameableValue, list):
    def __init__(self, **kargs):
        super(NamedList, self).__init__(**kargs)

class NamedListExtender(object):
    def __init__(self, namelist):
        self.namelist = namelist

    def __iter__(self):
        return self

    def next(self):
        namelist = self.namelist
        val = Naming(name=namelist.name + '[{len}]'.format(len=len(namelist)))
        if len(namelist) == 0:
            get_thread_naming().append(val)
        namelist.append(val)
        return val


@contextmanager
def layers_named(name):
    try:
        naming = NamedList()
        tnaming = get_thread_naming()
        length = len(tnaming)
        tnaming[-1].__setattr__(name, naming)
        tnaming.append(naming)
        yield(NamedListExtender(naming))
    finally:
        while len(tnaming) > length:
            tnaming.pop()


def with_name_context(fun, name=None):
    cname = name
    if cname is None:
        cname = fun.__name__

    @wraps(fun)
    def wrapper(*args, **kargs):
        myname = cname
        if 'name' in kargs:
            myname = kargs['name']
            del kargs['name']

        with name_context(myname) as ctx:
            return fun(ctx, *args, **kargs)

    return wrapper


class NamedValueGenerator(NameableValue):
    """Accessing attributes generates objects."""
    def __init__(self, generator, name="", **kargs):
        super(NamedValueGenerator, self).__init__(name=name, **kargs)
        self.__generator = generator

    def __setattr__(self, name, value):
        if name.startswith('_'):
            return super(NamedValueGenerator, self).__setattr__(name, value)
        else:
            raise NameException()

    def __getattr__(self, name):
        if not name.startswith('_'):
            named_value = self.__generator(name=self.name+"."+name)
            super(NamedValueGenerator, self).__setattr__(name, named_value)
            return named_value
        return super(NamedValueGenerator, self).__getattr__(name)


class VariableBlock(object):
    def __setattr__(self, name, value):
        """Tell value that it is being assigned to name"""
        value.name = name
        super(VariableBlock, self).__setattr__(name, value)


class AxisGenerator(NamedValueGenerator):
    def __init__(self, name, **kargs):
        super(AxisGenerator, self).__init__(name=name, generator=Axis, **kargs)


class Axis(NameableValue):
    def __init__(self, depth=0, parent=None, **kargs):
        super(Axis, self).__init__(**kargs)
        self.depth = depth
        self.parent = parent

    def __getitem__(self, item):
        get_current_environment().set_axis_value(self, item)
        return self

    @property
    def value(self):
        return get_current_environment().get_axis_value(self)

    def like(self):
        return Axis(parent=self, name=self.name)

    def size(self):
        if isinstance(self.value, numbers.Integral):
            return int(self.value)
        if isinstance(self.value, tuple):
            return len(self.value)
        return 1

    def __repr__(self):
        val = None
        try:
            val = self.value
        except:
            pass
        return '{name}:Axis[{value}]'.format(value=val, name=self.name)


