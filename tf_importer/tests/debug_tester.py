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

from tf_importer.tests.importer_tester import ImporterTester
from tf_importer.tf_importer.utils import tensor_shape_to_tuple
import tensorflow as tf
import numpy as np
import os
import re
import time
import atexit

cmd_kill = 'pid=`lsof -t -i:6006`; if [ $pid ] ; then kill -9 $pid; fi'
cmd_browser = 'open http://0.0.0.0:6006/#graphs'
cmd_start_tensorboard = 'tensorboard --logdir=.'


def remove_event_dump(dir='./', pattern='events.out.tfevents.*'):
    for f in os.listdir(dir):
        if re.search(pattern, f):
            target_file = os.path.join(dir, f)
            os.remove(target_file)
            print("Removed event dump: %s" % target_file)


def clean_up():
    os.system(cmd_kill)
    remove_event_dump()


def start_tensorboard():
    """
    Start tensorboard on current directory
    """
    os.system(cmd_kill)
    os.system(cmd_browser)
    os.system(cmd_start_tensorboard)


class DebugTester(ImporterTester):
    """
    Run tester directly for debugging without py.test
    """

    def __init__(self):
        pass

    def setup(self):
        remove_event_dump()
        self.setup_class()
        self.setup_method(None)

    def run(self, tf_target_node, tf_init_op=None, tf_feed_dict=None,
            print_tf_result=True, print_ng_result=True, verbose=False):
        super(DebugTester, self).run(tf_target_node=tf_target_node,
                                     tf_init_op=tf_init_op,
                                     tf_feed_dict=tf_feed_dict,
                                     print_tf_result=print_ng_result,
                                     verbose=verbose)
        # dump graph for tensorboard
        tf.train.SummaryWriter('./', self.sess.graph)

    def tf_run(self, tf_target_node, tf_init_op=None, tf_feed_dict=None,
               print_tf_result=True):
        super(DebugTester, self).tf_run(tf_target_node=tf_target_node,
                                        tf_init_op=tf_init_op,
                                        tf_feed_dict=tf_feed_dict,
                                        print_tf_result=print_tf_result)
        # dump graph for tensorboard
        tf.train.SummaryWriter('./', self.sess.graph)

    def teardown(self, delete_dump=False):
        self.teardown_method(None, delete_dump=delete_dump)
        if delete_dump:
            time.sleep(0.5)
            remove_event_dump()


def def_target_feed_dict():
    """
    Define computation and feed dict here
    """

    # tf placeholder
    a = tf.constant(np.random.randn(1, 10).astype(np.float32),
                    dtype=tf.float32)
    b = tf.constant(np.ones((10, 1)).astype(np.float32),
                    dtype=tf.float32)
    f = tf.matmul(tf.nn.relu(a), b)
    a_grad = tf.gradients(f, a)[0]

    # value
    feed_dict = {}

    # return
    return a_grad, feed_dict, None


if __name__ == '__main__':
    # remove event dump at exit
    atexit.register(clean_up)

    # init
    tester = DebugTester()
    tester.setup()

    # get target node and feed_dict
    target, feed_dict, init_op = def_target_feed_dict()

    # run & teardown
    tester.tf_run(target, tf_init_op=init_op,
                  tf_feed_dict=feed_dict, print_tf_result=True)
    tester.ng_run(target, tf_feed_dict=feed_dict, print_ng_result=True,
                  verbose=False)
    tester.teardown(delete_dump=False)

    # start tensorboard (optional)
    # start_tensorboard()
