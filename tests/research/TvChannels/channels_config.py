# -*-coding: utf-8 -*-
"""
.. invisible:
     _   _ _____ _     _____ _____
    | | | |  ___| |   |  ___/  ___|
    | | | | |__ | |   | |__ \ `--.
    | | | |  __|| |   |  __| `--. \
    \ \_/ / |___| |___| |___/\__/ /
     \___/\____/\_____|____/\____/

Created on Nov 14, 2014

███████████████████████████████████████████████████████████████████████████████

Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.

███████████████████████████████████████████████████████████████████████████████
"""


import numpy
import os

from veles.config import root

root.channels.update({
    "decision": {"fail_iterations": 50,
                 "max_epochs": numpy.iinfo(numpy.uint32).max},
    "downloader": {
        "url":
        "https://s3-eu-west-1.amazonaws.com/veles.forge/"
        "TvChannels/channels_train.tar",
        "directory": root.common.dirs.datasets,
        "files": ["channels_train"]},
    "snapshotter": {"prefix": "channels", "interval": 1, "time_interval": 0},
    "image_saver": {"out_dirs":
                    [os.path.join(root.common.dirs.cache, "tmp/test"),
                     os.path.join(root.common.dirs.cache, "tmp/validation"),
                     os.path.join(root.common.dirs.cache, "tmp/train")]},
    "loader": {"minibatch_size": 30,
               "force_numpy": True,
               "validation_ratio": 0.15,
               "shuffle_limit": numpy.iinfo(numpy.uint32).max,
               "normalization_type": "mean_disp",
               "add_sobel": True,
               "file_subtypes": ["png", "jpeg"],
               "background_image":
               numpy.zeros([224, 224, 4], dtype=numpy.uint8),
               "mirror": False,
               "color_space": "HSV",
               "scale": (224, 224),
               "background_color": (0, 0, 0, 0),
               "scale_maintain_aspect_ratio": True,
               "train_paths":
               [os.path.join(root.common.dirs.datasets, "channels_train")]},
    "decision_name": "decision_gd",
    "evaluator_name": "evaluator_softmax_channels",
    "loader_name": "auto_label_file_image",
    "layers": [{"name": "fc_tanh1",
                "type": "all2all_tanh",
                "<-": {"learning_rate": 0.01, "weights_decay": 0.00005},
                "->": {"output_sample_shape": 100}},
               {"name": "fc_softmax2",
                "type": "softmax",
                "->": {"output_sample_shape": 9},
                "<-": {"learning_rate": 0.01, "weights_decay": 0.00005}}]})
