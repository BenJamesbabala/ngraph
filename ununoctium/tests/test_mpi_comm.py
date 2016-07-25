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

import os
import numpy as np
from subprocess import Popen, PIPE

'''
Test the usage of transformer.allreduce

'''
import geon.backends.graph.funs as be
from geon.backends.graph.mpihandle import MPIHandle


def test_mpi_allreduce():
    with be.bound_environment():
        a = np.array([[4, 1, 2, -3, 4],
                      [5, -6, 7, -8, 9]], dtype=np.float32)

        handle = MPIHandle()
        result = handle.allreduceAvg(a)

        assert(np.array_equal(a, result))

        print("pass mpi allreduce test")


def test_mpi_reduce():
    pass


def test_mpi_reduce_avg():
    pass


def test_mpi_scatter():
    pass


def test_mpi_scatterv():
    pass


def test_mpi_gattherv():
    pass


parent_info = os.popen("ps -p %d" % os.getppid()).read().strip().split('\n')
parent_cmd = (parent_info[-1].split())[-1]

if parent_cmd == 'mpirun':
    test_mpi_allreduce()

else:
    cmd = "mpirun -n 2 python /home/yashar/gitlab/graphiti/ununoctium/tests/test_allreduce.py"
    proc = Popen(cmd, stdout=PIPE, stderr=PIPE, shell=True)
    proc.wait()
    proc_out, proc_err = proc.communicate()
