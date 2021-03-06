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


class Requirement(object):  # pylint: disable=too-few-public-methods
    def __init__(self,
                 name,
                 parsed=False,
                 multiple_results=False,
                 required=True,
                 predicate=None):
        self.name = name
        self.parsed = parsed
        self.multiple_results = multiple_results
        self.required = required
        self.predicate = predicate

    def __repr__(self):
        return (
            '{cls.__name__}('
            'name={self.name}, parsed={self.parsed}, '
            'multiple_results={self.multiple_results}, '
            'required={self.required}, predicate={self.predicate})'
            .format(cls=self.__class__, self=self))


class Value(Requirement):  # pylint: disable=too-few-public-methods
    def __init__(self,
                 name,
                 multiple_results=False,
                 required=True,
                 predicate=None):
        super(Value, self).__init__(
            name,
            parsed=True,
            multiple_results=multiple_results,
            required=required,
            predicate=predicate)


def sibling_predicate(source, target):
    return source.parent() == target.parent()
