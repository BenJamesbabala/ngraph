# ----------------------------------------------------------------------------
# Copyright 2016 Nervana Systems Inc.
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

from __future__ import print_function

from ngraph.op_graph.axes_ops import dimshuffle
from ngraph.op_graph.axes import makeAxisRole, makeAxis, makeAxes, Axis, Axes
from ngraph.op_graph.convolution import convolution
from ngraph.op_graph.pooling import pooling
from ngraph.op_graph.debug import PrintOp
from ngraph.op_graph.op_graph import *
from ngraph.op_graph.op_graph import cast_axes
from ngraph.transformers.nptransform import NumPyTransformer
from ngraph.util.names import makeNameScope

__all__ = [
    'cast_axes',
    'makeAxes',
    'makeAxis',
    'makeAxisRole',
    'makeNameScope',
    'AssignableOp',
    'Axis',
    'AxisRole',
    'Axes',
    'Op',
    'TensorOp',
]


try:
    from ngraph.transformers.gputransform import GPUTransformer
except ImportError:
    pass
