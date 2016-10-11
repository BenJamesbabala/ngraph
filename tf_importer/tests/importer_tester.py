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

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf
import numpy as np
import os
from tf_importer.tf_importer.importer import TFImporter
import ngraph.transformers as ngt
import pytest


@pytest.mark.usefixtures("transformer_factory")
class ImporterTester(object):
    """
    Tester class for py.test
    """

    @pytest.fixture(autouse=True)
    def build_transformer(self, transformer_factory):
        pass

    @classmethod
    def setup_class(self):
        self.pb_txt_path = "temp_graph.txt"

    def setup_method(self, method):
        self.sess = tf.Session()

    def teardown_method(self, method, delete_dump=True):
        # close session - doesn't work
        self.sess.close()

        # clear sess.graph_def
        tf.reset_default_graph()

        # remove dumped protobuf
        if delete_dump:
            try:
                os.remove(self.pb_txt_path)
            except:
                print("test dump does not exist")  # disable capturing to print

    def run(self, tf_target_node, tf_init_op=None, tf_feed_dict=None,
            print_tf_result=False, print_ng_result=False, verbose=False):
        """
        Performs test with optional feed_dicts, compares result of TF and ngraph

        Args:
            target_op: the targeting TF
            tf_feed_dict: TF feed dict for tensorflow placeholders

        TODO: standardize naming of op and node
        """
        # run TF
        tf_result = self.tf_run(tf_target_node=tf_target_node,
                                tf_init_op=tf_init_op,
                                tf_feed_dict=tf_feed_dict,
                                print_tf_result=print_ng_result)

        # run NG
        ng_result = self.ng_run(tf_target_node=tf_target_node,
                                tf_feed_dict=tf_feed_dict,
                                print_ng_result=print_ng_result,
                                verbose=verbose)

        # assert
        assert np.allclose(tf_result, ng_result)

    def ng_run(self, tf_target_node, tf_feed_dict=None, print_ng_result=False,
               verbose=False):

        # init importer, transformer
        importer = TFImporter(self.pb_txt_path, verbose=verbose)
        # transformer = ng.NumPyTransformer()
        # transformer = self.transformer_factory()
        transformer = ngt.Transformer.make_transformer()

        # set target node
        ng_target_node = importer.name_to_op[tf_target_node.name[:-2]]

        # evaluate ngraph
        if tf_feed_dict is not None:
            # get targeting nodes for ng, convert tf's feed dict to list
            tf_placeholder_nodes = [node for (node, _) in tf_feed_dict.items()]
            tf_placeholder_names = [node.name for node in tf_placeholder_nodes]
            ng_placeholder_nodes = [importer.name_to_op[name[:-2]]
                                    for name in tf_placeholder_names]
            ng_placeholder_vals = [val for (_, val) in tf_feed_dict.items()]

            # evaluate ngraph result
            ng_result_comp = transformer.computation([ng_target_node],
                                                     *ng_placeholder_nodes)
            if importer.init_ops:
                init_comp = transformer.computation(importer.init_ops)
                init_comp()

            ng_result = ng_result_comp(*ng_placeholder_vals)[0]
        else:
            ng_result_comp = transformer.computation([ng_target_node])
            if importer.init_ops:
                init_comp = transformer.computation(importer.init_ops)
                init_comp()
            ng_result = ng_result_comp()[0]
        if print_ng_result:
            print(ng_result)

        return ng_result

    def tf_run(self, tf_target_node, tf_init_op=None, tf_feed_dict=None,
               print_tf_result=False):
        """
        Runs TF on graph
        """
        # init
        if tf_init_op:
            self.sess.run(tf_init_op)

        # get tensorflow result
        tf_result = self.sess.run(tf_target_node, feed_dict=tf_feed_dict)
        if print_tf_result:
            print(tf_result)

        # write to protobuf
        tf.train.write_graph(self.sess.graph_def, "./", self.pb_txt_path, True)

        return tf_result
