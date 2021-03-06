# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from .. import Value, Requirement
from .data_types import Schema
from .plugins import Plugins
from .operation import process_operation
from . import DictElement, Element, Leaf, Dict


class WorkflowMapping(Element):
    required = True
    schema = Leaf(obj_type=str)


class Workflow(Element):
    required = True
    schema = [
        Leaf(obj_type=str),
        {'mapping': WorkflowMapping, 'parameters': Schema},
    ]
    requires = {
        'inputs': [Requirement('resource_base', required=False)],
        Plugins: [Value('plugins')],
    }

    def parse(self, plugins, resource_base, **_):
        if isinstance(self.initial_value, str):
            operation_content = {
                'mapping': self.initial_value,
                'parameters': {},
            }
        else:
            operation_content = self.build_dict_result()
        return process_operation(
            plugins=plugins,
            operation_name=self.name,
            operation_content=operation_content,
            error_code=21,
            partial_error_message='',
            resource_base=resource_base,
            is_workflows=True)


class Workflows(DictElement):
    schema = Dict(obj_type=Workflow)
    requires = {Plugins: [Value('plugins')]}
    provides = ['workflow_plugins_to_install']

    def calculate_provided(self, plugins, **_):
        workflow_plugins = []
        workflow_plugin_names = set()
        for op_struct in self.value.itervalues():  # pylint: disable=no-member
            if op_struct['plugin'] not in workflow_plugin_names:
                plugin_name = op_struct['plugin']
                workflow_plugins.append(plugins[plugin_name])
                workflow_plugin_names.add(plugin_name)
        return {'workflow_plugins_to_install': workflow_plugins}
