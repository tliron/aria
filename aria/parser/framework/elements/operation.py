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

import copy

from ...uri_data_reader import uri_exists
from ...exceptions import DSLParsingLogicException
from ... import constants
from ...interfaces.utils import operation, workflow_operation, no_op_operation
from .data_types import Schema
from .version import ToscaDefinitionsVersion
from . import DictElement, Element, Leaf, Dict


class OperationImplementation(Element):
    schema = Leaf(obj_type=str)

    def parse(self):
        return self.initial_value if self.initial_value is not None else ''


class OperationExecutor(Element):
    schema = Leaf(obj_type=str)
    valid_executors = (constants.LOCAL_AGENT,)

    def parse(self, **kwargs):
        return (super(OperationExecutor, self).parse(**kwargs)
                or constants.LOCAL_AGENT)

    def validate(self, **kwargs):
        if self.initial_value is None:
            return
        if self.initial_value in self.valid_executors:
            return
        full_operation_name = '{0}.{1}'.format(
            self.ancestor(Interface).name,
            self.ancestor(Operation).name)
        raise DSLParsingLogicException(
            28, "Operation '{0}' has an illegal executor value '{1}'. "
                "valid values are {2}".format(
                    full_operation_name,
                    self.initial_value,
                    self.valid_executors))


class NodeTemplateOperationInputs(Element):
    schema = Leaf(obj_type=dict)

    def parse(self):
        return self.initial_value or {}


class OperationMaxRetries(Element):
    schema = Leaf(obj_type=int)
    requires = {
        ToscaDefinitionsVersion: ['version'],
        'inputs': ['validate_version'],
    }

    def validate(self, **kwargs):
        value = self.initial_value
        if value is None:
            return
        if value < -1:
            raise ValueError(
                "'{0}' value must be either -1 to specify "
                "unlimited retries or a non negative number but "
                "got {1}."
                .format(self.name, value))


class OperationRetryInterval(Element):
    schema = Leaf(obj_type=(int, float, long))
    requires = {
        ToscaDefinitionsVersion: ['version'],
        'inputs': ['validate_version'],
    }

    def validate(self, **kwargs):
        value = self.initial_value
        if value is None:
            return
        if value is not None and value < 0:
            raise ValueError(
                "'{0}' value must be a non negative number but "
                "got {1}.".format(self.name, value))


class Operation(Element):
    def parse(self):
        if isinstance(self.initial_value, basestring):
            return {
                'implementation': self.initial_value,
                'executor': constants.LOCAL_AGENT,
                'inputs': {},
                'max_retries': None,
                'retry_interval': None,
            }
        return self.build_dict_result()


class NodeTypeOperation(Operation):
    schema = [
        Leaf(obj_type=str),
        {
            'implementation': OperationImplementation,
            'inputs': Schema,
            'executor': OperationExecutor,
            'max_retries': OperationMaxRetries,
            'retry_interval': OperationRetryInterval,
        },
    ]


class NodeTemplateOperation(Operation):
    schema = [
        Leaf(obj_type=str),
        {
            'implementation': OperationImplementation,
            'inputs': NodeTemplateOperationInputs,
            'executor': OperationExecutor,
            'max_retries': OperationMaxRetries,
            'retry_interval': OperationRetryInterval,
        }
    ]


class Interface(DictElement):
    pass


class NodeTemplateInterface(Interface):
    schema = Dict(obj_type=NodeTemplateOperation)


class NodeTemplateInterfaces(DictElement):
    schema = Dict(obj_type=NodeTemplateInterface)


class NodeTypeInterface(Interface):
    schema = Dict(obj_type=NodeTypeOperation)


class NodeTypeInterfaces(DictElement):
    schema = Dict(obj_type=NodeTypeInterface)


def process_interface_operations(
        interface,
        plugins,
        error_code,
        partial_error_message,
        resource_base):
    return [process_operation(plugins=plugins,
                              operation_name=operation_name,
                              operation_content=operation_content,
                              error_code=error_code,
                              partial_error_message=partial_error_message,
                              resource_base=resource_base)
            for operation_name, operation_content in interface.items()]


def process_operation(  # pylint: disable=too-many-branches
        plugins,
        operation_name,
        operation_content,
        error_code,
        partial_error_message,
        resource_base,
        is_workflows=False):
    operation_mapping = operation_content[
        'mapping' if is_workflows else 'implementation']
    operation_payload = operation_content[
        'parameters' if is_workflows else 'inputs']
    operation_executor = (
        operation_content.get('executor') or constants.LOCAL_AGENT)
    operation_max_retries = operation_content.get('max_retries', None)
    operation_retry_interval = operation_content.get('retry_interval', None)

    if not operation_mapping:
        if is_workflows:
            raise RuntimeError('Illegal state. workflow mapping should always'
                               'be defined (enforced by schema validation)')
        return no_op_operation(operation_name=operation_name)

    candidate_plugins = [
        p for p in plugins.keys()
        if operation_mapping.startswith('{0}.'.format(p))]
    if candidate_plugins:
        if len(candidate_plugins) > 1:
            raise DSLParsingLogicException(
                91,
                'Ambiguous operation mapping. [operation={0}, '
                'plugins={1}]'.format(operation_name, candidate_plugins))
        plugin_name = candidate_plugins[0]
        if is_workflows:
            return workflow_operation(
                plugin_name=plugin_name,
                workflow_mapping=operation_mapping[len(plugin_name) + 1:],
                workflow_parameters=operation_payload)
        if any((not operation_executor,
                operation_executor == constants.LOCAL_AGENT)):
            operation_executor = (
                plugins[plugin_name].get('executor') or constants.LOCAL_AGENT)

        return operation(
            name=operation_name,
            plugin_name=plugin_name,
            mapping=operation_mapping[len(plugin_name) + 1:],
            operation_inputs=operation_payload,
            executor=operation_executor,
            max_retries=operation_max_retries,
            retry_interval=operation_retry_interval)
    elif resource_base and _resource_exists(resource_base, operation_mapping):
        operation_payload = copy.deepcopy(operation_payload or {})
        if constants.SCRIPT_PATH_PROPERTY in operation_payload:
            raise DSLParsingLogicException(
                60, "Cannot define '{0}' property in '{1}' for {2} '{3}'".format(
                    constants.SCRIPT_PATH_PROPERTY,
                    operation_mapping,
                    'workflow' if is_workflows else 'operation',
                    operation_name))
        script_path = operation_mapping
        if is_workflows:
            operation_mapping = constants.SCRIPT_PLUGIN_EXECUTE_WORKFLOW_TASK
            operation_payload.update({
                constants.SCRIPT_PATH_PROPERTY: {
                    'default': script_path,
                    'description': 'Workflow script executed by the script'
                                   ' plugin'
                }
            })
        else:
            operation_mapping = constants.SCRIPT_PLUGIN_RUN_TASK
            operation_payload[constants.SCRIPT_PATH_PROPERTY] = script_path
        if constants.SCRIPT_PLUGIN_NAME not in plugins:
            raise DSLParsingLogicException(
                61,
                "Script plugin is not defined but it is required for"
                " mapping '{0}' of {1} '{2}'"
                .format(
                    operation_mapping,
                    'workflow' if is_workflows else 'operation',
                    operation_name))

        if is_workflows:
            return workflow_operation(
                plugin_name=constants.SCRIPT_PLUGIN_NAME,
                workflow_mapping=operation_mapping,
                workflow_parameters=operation_payload)
        if any((not operation_executor, operation_executor == constants.LOCAL_AGENT)):
            operation_executor = plugins[constants.SCRIPT_PLUGIN_NAME].get(
                'executor', constants.LOCAL_AGENT)
        return operation(
            name=operation_name,
            plugin_name=constants.SCRIPT_PLUGIN_NAME,
            mapping=operation_mapping,
            operation_inputs=operation_payload,
            executor=operation_executor,
            max_retries=operation_max_retries,
            retry_interval=operation_retry_interval)
    else:
        # This is an error for validation done somewhere down the
        # current stack trace
        raise DSLParsingLogicException(
            error_code,
            "Could not extract plugin from {2} mapping '{0}', "
            "which is declared for {2} '{1}'. {3}".format(
                operation_mapping,
                operation_name,
                'workflow' if is_workflows else 'operation',
                partial_error_message))


def _resource_exists(resource_base, resource_name):
    if isinstance(resource_base, basestring):
        return uri_exists('{0}/{1}'.format(resource_base, resource_name))
    return any(
        uri_exists('{0}/{1}'.format(directory, resource_name))
        for directory in resource_base
    )
