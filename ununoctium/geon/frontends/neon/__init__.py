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

# commonly used modules.  Should these still be imported in neon frontend?
import geon.op_graph as be
import geon.frontends.base.axis as ax

# neon frontend modules
from geon.frontends.neon.callbacks import *
from geon.frontends.neon.layer import *
from geon.frontends.neon.optimizer import *
from geon.frontends.neon.model import Model
from geon.frontends.neon.cost import CrossEntropyBinary, CrossEntropyMulti, SumSquared, \
    Misclassification
from geon.frontends.neon.activation import Rectlin, Identity, Explin, Normalizer, Softmax, Tanh, \
    Logistic

# include Axes here because old 2.0 code needs to be updated to include Axes
# annotations in the call to model.fit.
# TODO: depricate this Axes, you should just use be.Axes instead
from geon.op_graph import Axes

# old neon code which hasn't changed but should be available in this namespace
# TODO: there are a lot of classes which are similar to the ones listed here,
# but are not listed here and probably should be.
from neon.util.argparser import NeonArgparser
from neon.data import ImageLoader
from neon.initializers import Uniform
from neon.optimizers.optimizer import Schedule, StepSchedule, PowerSchedule, ExpSchedule, \
    PolySchedule
