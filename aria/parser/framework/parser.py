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

from collections import defaultdict
import networkx

from ..exceptions import (
    DSLParsingException, DSLParsingFormatException,
    DSLParsingLogicException, DSLParsingSchemaAPIException,
    ERROR_CODE_CYCLE,
)
from .elements import (
    Element, ElementType, UnknownElement,
    UnknownSchema, Dict, Leaf, List,
)
from . import Requirement


def parse(value,
          element_cls,
          element_name='root',
          inputs=None,
          strict=True):
    validate_schema_api(element_cls)
    context = Context(
        value=value,
        element_cls=element_cls,
        element_name=element_name,
        inputs=inputs)
    for element in context.elements_graph_topological_sort():
        try:
            _validate_element_schema(element, strict=strict)
            _process_element(element)
        except DSLParsingException as exc:
            if not exc.element:
                exc.element = element
            raise
    return context.parsed_value


class Context(object):
    def __init__(self,
                 value,
                 element_cls,
                 element_name,
                 inputs):
        self.inputs = inputs or {}
        self.element_type_to_elements = defaultdict(list)
        self._root_element = None
        self._element_tree = networkx.DiGraph()
        self._element_graph = networkx.DiGraph()
        self._traverse_element_cls(
            element_cls=element_cls,
            name=element_name,
            value=value,
            parent_element=None)
        self._calculate_element_graph()

    @property
    def parsed_value(self):
        return self._root_element.value if self._root_element else None

    def child_elements_iter(self, element):
        return self._element_tree.successors_iter(element)

    def ancestors_iter(self, element):
        current_element = element
        while True:
            predecessors = self._element_tree.predecessors(current_element)
            if not predecessors:
                return
            if len(predecessors) > 1:
                raise DSLParsingFormatException(
                    1, 'More than 1 parent found for {0}'.format(element))
            current_element = predecessors[0]
            yield current_element

    def descendants(self, element):
        return networkx.descendants(self._element_tree, element)

    def _add_element(self, element, parent=None):
        element_type = type(element)
        self.element_type_to_elements[element_type].append(element)

        self._element_tree.add_node(element)
        if parent:
            self._element_tree.add_edge(parent, element)
        else:
            self._root_element = element

    def _traverse_element_cls(self,
                              element_cls,
                              name,
                              value,
                              parent_element):
        element = element_cls(name=name,
                              initial_value=value,
                              context=self)
        self._add_element(element, parent=parent_element)
        self._traverse_schema(schema=element_cls.schema,
                              parent_element=element)

    def _traverse_schema(self, schema, parent_element):
        if isinstance(schema, dict):
            self._traverse_dict_schema(schema=schema,
                                       parent_element=parent_element)
        elif isinstance(schema, ElementType):
            self._traverse_element_type_schema(
                schema=schema,
                parent_element=parent_element)
        elif isinstance(schema, list):
            self._traverse_list_schema(schema=schema,
                                       parent_element=parent_element)
        elif isinstance(schema, UnknownSchema):
            pass
        else:
            raise ValueError('Illegal state should have been identified'
                             ' by schema API validation')

    def _traverse_dict_schema(self, schema, parent_element):
        if not isinstance(parent_element.initial_value, dict):
            return

        parsed_names = set()
        for name, element_cls in schema.items():
            if name not in parent_element.initial_value_holder:
                value = None
            else:
                name, value = \
                    parent_element.initial_value_holder.get_item(name)
                parsed_names.add(name.value)
            self._traverse_element_cls(element_cls=element_cls,
                                       name=name,
                                       value=value,
                                       parent_element=parent_element)
        for k_holder, v_holder in parent_element.initial_value_holder.value.\
                iteritems():
            if k_holder.value not in parsed_names:
                self._traverse_element_cls(element_cls=UnknownElement,
                                           name=k_holder, value=v_holder,
                                           parent_element=parent_element)

    def _traverse_element_type_schema(self, schema, parent_element):
        if isinstance(schema, Leaf):
            return

        element_cls = schema.type
        if isinstance(schema, Dict):
            if not isinstance(parent_element.initial_value, dict):
                return
            for name_holder, value_holder in parent_element.\
                    initial_value_holder.value.items():
                self._traverse_element_cls(element_cls=element_cls,
                                           name=name_holder,
                                           value=value_holder,
                                           parent_element=parent_element)
        elif isinstance(schema, List):
            if not isinstance(parent_element.initial_value, list):
                return
            for index, value_holder in enumerate(
                    parent_element.initial_value_holder.value):
                self._traverse_element_cls(element_cls=element_cls,
                                           name=index,
                                           value=value_holder,
                                           parent_element=parent_element)
        else:
            raise ValueError('Illegal state should have been identified'
                             ' by schema API validation')

    def _traverse_list_schema(self, schema, parent_element):
        for schema_item in schema:
            self._traverse_schema(schema=schema_item,
                                  parent_element=parent_element)

    def _calculate_element_graph(self):
        self.element_graph = networkx.DiGraph(self._element_tree)
        for element_type, elements in self.element_type_to_elements.items():
            requires = element_type.requires
            for requirement, requirement_values in requires.items():
                requirement, requirement_values = _requirements_setup(
                    requirement, requirement_values, element_type)
                if requirement == 'inputs':
                    continue
                dependencies = self.element_type_to_elements[requirement]
                for dependency in dependencies:
                    for element in elements:
                        predicates = [
                            r.predicate
                            for r in requirement_values
                            if r.predicate is not None]

                        add_dependency = (
                            not predicates
                            or all(predicate(element, dependency)
                                   for predicate in predicates))

                        if add_dependency:
                            self.element_graph.add_edge(element, dependency)
        # we reverse the graph because only netorkx 1.9.1 has the reverse
        # flag in the topological sort function, it is only used by it
        # so this should be good
        self.element_graph.reverse(copy=False)

    def elements_graph_topological_sort(self):
        try:
            return networkx.topological_sort(self.element_graph)
        except networkx.NetworkXUnfeasible:
            # Cycle detected
            cycle = networkx.recursive_simple_cycles(self.element_graph)[0]
            names = [str(e.name) for e in cycle]
            names.append(str(names[0]))
            ex = DSLParsingLogicException(
                ERROR_CODE_CYCLE,
                'Parsing failed. Circular dependency detected: {0}'
                .format(' --> '.join(names)))
            ex.circular_dependency = names
            raise ex


def validate_schema_api(element_cls):
    try:
        if not issubclass(element_cls, Element):
            raise DSLParsingSchemaAPIException(1)
    except TypeError:
        raise DSLParsingSchemaAPIException(1)
    _traverse_schema(element_cls.schema)


def _traverse_schema(schema, list_nesting=0):
    if isinstance(schema, dict):
        for key, value in schema.items():
            if not isinstance(key, basestring):
                raise DSLParsingSchemaAPIException(1)
            validate_schema_api(value)

    elif isinstance(schema, list):
        if list_nesting > 0 or len(schema) == 0:
            raise DSLParsingSchemaAPIException(1)
        for value in schema:
            _traverse_schema(value, list_nesting + 1)

    elif isinstance(schema, ElementType):
        if isinstance(schema, Leaf):
            if not isinstance(schema.type, (type, list, tuple)):
                raise DSLParsingSchemaAPIException(1)
            # TODO: need to clean up
            if (isinstance(schema.type, (list, tuple))
                    and (not schema.type or not all(
                        isinstance(cls, type) for cls in schema.type))):
                raise DSLParsingSchemaAPIException(1)

        elif isinstance(schema, (Dict, List)):
            validate_schema_api(schema.type)

        else:
            raise DSLParsingSchemaAPIException(1)

    else:
        raise DSLParsingSchemaAPIException(1)


def _validate_element_schema(element, strict):
    value = element.initial_value
    if element.required and value is None:
        raise DSLParsingFormatException(
            1, "'{0}' key is required but it is currently missing".format(element.name))

    if value is None:
        return
    if not isinstance(element.schema, list):
        _validate_schema(element.schema, strict, value, element)
        return

    last_error = None
    for schema_item in element.schema:
        try:
            _validate_schema(schema_item, strict, value, element)
        except DSLParsingFormatException as exc:
            last_error = exc
        else:
            break
    else:
        raise last_error or ValueError(
            'Illegal state should have been '
            'identified by schema API validation')


def _validate_schema(schema, strict, value, element):
    if isinstance(schema, (dict, Dict)):
        if not isinstance(value, dict):
            raise DSLParsingFormatException(
                1, _expected_type_message(value, dict))
        for key in value.keys():
            if not isinstance(key, basestring):
                raise DSLParsingFormatException(
                    1,
                    "Dict keys must be strings but found '{0}' of type '{1}'".format(
                        key, _py_type_to_user_type(type(key))))

    if strict and isinstance(schema, dict):
        for key in value:
            if key not in schema:
                ex = DSLParsingFormatException(
                    1,
                    "'{0}' is not in schema. Valid schema values: {1}".format(
                        key, schema.keys()))
                for child_element in element.children():
                    if child_element.name == key:
                        ex.element = child_element
                        break
                raise ex

    if isinstance(schema, List) and not isinstance(value, list):
        raise DSLParsingFormatException(
            1, _expected_type_message(value, list))

    if isinstance(schema, Leaf) and not isinstance(value, schema.type):
        raise DSLParsingFormatException(
            1, _expected_type_message(value, schema.type))


def _process_element(element):
    required_args = _extract_element_requirements(element)
    element.validate(**required_args)
    if required_args.get('validate_version'):
        try:
            version = required_args['version'].definitions_version
        except AttributeError:
            version = required_args['version']
        element.validate_version(version)

    element.value = element.parse(**required_args)
    element.provided = element.calculate_provided(**required_args)


def _extract_element_requirements(element):
    context = element.context
    required_args = {}
    for required_type, requirements in element.requires.items():
        required_type, requirements = _requirements_setup(
            required_type, requirements, type(element))

        if not requirements:
            # only set required type as a logical dependency
            continue

        if required_type == 'inputs':
            _inputs_required_handler(required_args, requirements, context)
            continue

        for requirement in requirements:
            result = []
            _search_for_requirements(
                result,
                context.element_type_to_elements[required_type],
                requirement,
                element)
            result = _sort_requirements_result(result, requirement)
            required_args[requirement.name] = result

    return required_args


def _requirements_setup(required_type, requirements, element_type):
    required_type = element_type if required_type == 'self' else required_type
    try:
        required_type = required_type.extend or required_type
    except AttributeError:
        pass
    return required_type, [
        Requirement(requirement) if isinstance(requirement, basestring)
        else requirement
        for requirement in requirements]


def _search_for_requirements(
        result,
        required_type_elements,
        requirement,
        element):
    for required_element in required_type_elements:
        if requirement.predicate and not requirement.predicate(element, required_element):
            continue
        if requirement.parsed:
            result.append(required_element.value)
            continue
        if requirement.name not in required_element.provided:
            if not requirement.required:
                continue
            raise DSLParsingFormatException(
                1,
                "Required value '{0}' is not "
                "provided by '{1}'. Provided values "
                "are: {2}".format(
                    requirement.name,
                    required_element.name,
                    required_element.provided.keys()))
        result.append(required_element.provided[requirement.name])


def _sort_requirements_result(result, requirement):
    if requirement.multiple_results:
        return result

    if len(result) != 1:
        if requirement.required:
            raise DSLParsingFormatException(
                1,
                "Expected exactly one result for requirement '{0}' but found {1}".format(
                    requirement.name, 'none' if not result else result))
        if not result:
            return None
        raise ValueError('Illegal state')

    return result[0]


def _inputs_required_handler(required_args, requirements, context):
    for input_element in requirements:
        if input_element.name not in context.inputs and input_element.required:
            raise DSLParsingFormatException(
                1,
                "Missing required input '{0}'. "
                "Existing inputs: ".format(input_element.name))
        required_args[input_element.name] = context.inputs.get(input_element.name)


def _expected_type_message(value, expected_type):
    return ("Expected '{0}' type but found '{1}' type".format(
        _py_type_to_user_type(expected_type),
        _py_type_to_user_type(type(value))))


def _py_type_to_user_type(_type):
    if isinstance(_type, tuple):
        return list(set(_py_type_to_user_type(t) for t in _type))
    elif issubclass(_type, basestring):
        return 'string'
    elif issubclass(_type, bool):
        return 'boolean'
    elif issubclass(_type, int) or issubclass(_type, long):
        return 'integer'
    elif issubclass(_type, float):
        return 'float'
    elif issubclass(_type, dict):
        return 'dict'
    elif issubclass(_type, list):
        return 'list'
    else:
        raise ValueError('Unexpected type: {0}'.format(_type))
