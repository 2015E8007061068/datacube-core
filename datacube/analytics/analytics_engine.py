# ------------------------------------------------------------------------------
# Name:       analytics_engine.py
# Purpose:    Analytical Engine
#
# Author:     Peter Wang
#
# Created:    14 July 2015
# Copyright:  2015 Commonwealth Scientific and Industrial Research Organisation
#             (CSIRO)
# License:    This software is open source under the Apache v2.0 License
#             as provided in the accompanying LICENSE file or available from
#             https://github.com/data-cube/agdc-v2/blob/master/LICENSE
#             By continuing, you acknowledge that you have read and you accept
#             and will abide by the terms of the License.
#
# Updates:
# 7/10/2015:  Initial Version.
#
# ------------------------------------------------------------------------------

from __future__ import absolute_import
from __future__ import print_function
import sys
import numpy as np
import numexpr as ne
import copy
import logging
from pprint import pprint

from datacube.api import API

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class OPERATION_TYPE:
    Get_Data, Expression, Cloud_Mask, Bandmath, Reduction = range(5)


class AnalyticsEngine(object):

    SUPPORTED_OUTPUT_TYPES = ['netcdf-cf', 'geotiff']

    OPERATORS_SENSOR_SPECIFIC_BANDMATH = \
        {
            'ndvi':
            {
                'sensors':
                {
                    'LANDSAT 5': {'input': ['band_40', 'band_30'], 'function': 'ndvi'},
                    'LANDSAT 7': {'input': ['band_40', 'band_30'], 'function': 'ndvi'},
                },
                'functions':
                {
                    'ndvi': '((array1 - array2) / (array1 + array2))'
                }
            }
        }
    OPERATORS_REDUCTION = \
        {
            'median': 'median(array1)'
        }

    def __init__(self):
        logger.debug('Initialise Analytics Module.')
        self.plan = []
        self.plan_dict = {}

        self.api = API()

    def task(self, name):
        """Retrieve a task"""

        return self.plan[self.plan_dict[name]]

    def add_to_plan(self, name, task):
        """Add the task to the plan"""

        self.plan.append({name: task})
        size = len(self.plan)
        self.plan_dict[name] = size-1

        return self.plan[size-1]

    def create_array(self, storage_type, variables, dimensions, name):
        """Creates an array descriptor with metadata about what the data will look like"""

        # construct query descriptor

        query_parameters = {}
        query_parameters['storage_type'] = storage_type
        query_parameters['dimensions'] = dimensions
        query_parameters['variables'] = ()

        for array in variables:
            query_parameters['variables'] += (array,)

        query_parameters['platform'] = storage_type[0]
        query_parameters['product'] = storage_type[1]
        arrayDescriptors = self.api.get_descriptor(query_parameters)

        # stopgap until storage_units are filtered based on descriptors
        arrayDescriptors[arrayDescriptors.keys()[0]]['storage_units'] = {}

        arrayResults = []

        storage_type_key = arrayDescriptors.keys()[0]
        for variable in variables:
            if variable not in arrayDescriptors[storage_type_key]['variables']:
                raise AssertionError(variable, "not present in", storage_type_key, "descriptor")

            logger.debug('variable = %s', variable)

            arrayResult = {}
            arrayResult['storage_type'] = storage_type_key
            arrayResult['platform'] = storage_type[0]
            arrayResult['product'] = storage_type[1]
            arrayResult['variable'] = variable
            arrayResult['dimensions_order'] = arrayDescriptors[storage_type_key]['dimensions']
            arrayResult['dimensions'] = dimensions
            arrayResult['result_max'] = arrayDescriptors[storage_type_key]['result_max']
            arrayResult['result_min'] = arrayDescriptors[storage_type_key]['result_min']
            arrayResult['shape'] = arrayDescriptors[storage_type_key]['result_shape']
            arrayResult['data_type'] = arrayDescriptors[storage_type_key]['variables'][variable]['datatype_name']
            arrayResult['no_data_value'] = arrayDescriptors[storage_type_key]['variables'][variable]['nodata_value']

            arrayResults.append({variable: arrayResult})

        task = {}
        task['array_input'] = arrayResults
        task['array_output'] = copy.deepcopy(arrayResult)
        task['array_output']['variable'] = name
        task['function'] = 'get_data'
        task['orig_function'] = 'get_data'
        task['expression'] = 'none'
        task['operation_type'] = OPERATION_TYPE.Get_Data

        return self.add_to_plan(name, task)

    def apply_cloud_mask(self, arrays, mask, name):
        """
        Create a task descriptor of performing cloud masking
        Will be deprecated - currently kept for backwards compatibility
        """

        size = len(arrays)
        if size == 0:
            raise AssertionError("Input array is empty")

        task = {}
        task['array_input'] = []
        for array in arrays.keys():
            task['array_input'].append(array)

        task['array_mask'] = mask.keys()[0]
        task['orig_function'] = 'apply_cloud_mask'
        task['function'] = 'apply_cloud_mask'
        task['expression'] = 'none'
        task['array_output'] = copy.deepcopy(arrays.values()[0]['array_output'])
        task['array_output']['variable'] = name
        task['operation_type'] = OPERATION_TYPE.Cloud_Mask

        return self.add_to_plan(name, task)

    def apply_expression(self, arrays, function, name):
        """Create a task descriptor of performing an expression"""

        # Arrays is a list
        # output Array is same shape as input array
        size = len(arrays)
        if size == 0:
            raise AssertionError("Input array is empty")

        variables = []

        if not isinstance(arrays, list):
            arrays = [arrays]
        for array in arrays:
            variables.append(array.keys()[0])

        orig_function = function
        logger.debug('function before = %s', function)
        count = 1
        for variable in variables:
            function = function.replace('array'+str(count), variable)
            count += 1
        logger.debug('function after = %s', function)

        task = {}

        task['array_input'] = []

        for array in arrays:
            task['array_input'].append(array.keys()[0])

        task['orig_function'] = orig_function
        task['function'] = function
        task['expression'] = function
        task['array_output'] = copy.deepcopy(arrays[0].values()[0]['array_output'])
        task['array_output']['variable'] = name
        task['operation_type'] = OPERATION_TYPE.Expression

        return self.add_to_plan(name, task)

    # generic version
    def apply_bandmath(self, arrays, function, name):
        """
        Create a task descriptor of performing band math
        Will be deprecated - currently kept for backwards compatibility
        """

        # Arrays is a list
        # output Array is same shape as input array
        size = len(arrays)
        if size == 0:
            raise AssertionError("Input array is empty")

        variables = []
        if size == 1:  # 1 input
            if arrays.values()[0]['function'] == 'get_data':

                # check shape is same for all input arrays
                shape = arrays.values()[0]['array_input'][0].values()[0]['shape']
                for variable in arrays.values()[0]['array_input']:
                    if shape != variable.values()[0]['shape']:
                        raise AssertionError("Shape is different")
                    variables.append(variable.keys()[0])
            else:
                variables.append(arrays.keys()[0])

            orig_function = function
            logger.debug('function before = %s', function)
            count = 1
            for variable in variables:
                function = function.replace('array'+str(count), variable)
                count += 1
            logger.debug('function after = %s', function)

            task = {}

            task['array_input'] = []
            task['array_input'].append(arrays.keys()[0])
            task['orig_function'] = orig_function
            task['function'] = function
            task['expression'] = 'none'
            task['array_output'] = copy.deepcopy(arrays.values()[0]['array_output'])
            task['array_output']['variable'] = name
            task['operation_type'] = OPERATION_TYPE.Bandmath

            return self.add_to_plan(name, task)

        else:  # multi-dependencies
            for array in arrays:
                variables.append(array.keys()[0])

            orig_function = function
            logger.debug('function before = %s', function)
            count = 1
            for variable in variables:
                function = function.replace('array'+str(count), variable)
                count += 1
            logger.debug('function after = %s', function)

            task = {}

            task['array_input'] = []

            for array in arrays:
                task['array_input'].append(array.keys()[0])

            task['orig_function'] = orig_function
            task['function'] = function
            task['expression'] = 'none'
            task['array_output'] = copy.deepcopy(arrays[0].values()[0]['array_output'])
            task['array_output']['variable'] = name
            task['operation_type'] = OPERATION_TYPE.Bandmath

            return self.add_to_plan(name, task)

    # sensor specific version
    def apply_sensor_specific_bandmath(self, storage_types, product, function, dimensions, name_data, name_result):
        """
        Create a task descriptor of performing sensor specific bandmath
        """

        variables = self.get_predefined_inputs(storage_types, function)
        function_text = self.get_predefined_function(storage_types, function)

        arrays = self.create_array((storage_types, product), variables, dimensions, name_data)

        return self.apply_bandmath(arrays, function_text, name_result)

    def apply_reduction(self, array1, dimensions, function, name):
        """
        Create a task descriptor of performing dimension reduction
        Will be deprecated - currently kept for backwards compatibility
        """

        function = self.OPERATORS_REDUCTION.get(function)
        return self.apply_generic_reduction_function(array1, dimensions, function, name)

    def apply_generic_reduction(self, arrays, dimensions, function, name):
        """
        Create a task descriptor of performing generic dimension reduction
        Will be deprecated - currently kept for backwards compatibility
        """

        size = len(arrays)
        if size != 1:
            raise AssertionError("Input array should be 1")

        if arrays.values()[0]['function'] == 'get_data':

            variable = arrays.values()[0]['array_input'][0].values()[0]['variable']
            orig_function = function
            logger.debug('function before = %s', function)
            function = function.replace('array1', variable)
            logger.debug('function after = %s', function)

            task = {}

            task['array_input'] = []
            task['array_input'].append(arrays.keys()[0])
            task['orig_function'] = orig_function
            task['function'] = function
            task['expression'] = 'none'
            task['dimension'] = copy.deepcopy(dimensions)

            task['array_output'] = copy.deepcopy(arrays.values()[0]['array_output'])
            task['array_output']['variable'] = name
            task['array_output']['dimensions_order'] = \
                self.diff_list(arrays.values()[0]['array_input'][0].values()[0]['dimensions_order'], dimensions)

            for item in task['dimension']:
                if item in task['array_output']['dimensions']:
                    del task['array_output']['dimensions'][item]
            result = ()
            for value in task['array_output']['dimensions_order']:
                input_task = self.task(task['array_input'][0])
                index = input_task.values()[0]['array_output']['dimensions_order'].index(value)
                value = input_task.values()[0]['array_output']['shape'][index]
                result += (value,)
            task['array_output']['shape'] = result
            task['operation_type'] = OPERATION_TYPE.Reduction

            return self.add_to_plan(name, task)
        else:
            variable = arrays.keys()[0]
            orig_function = function
            logger.debug('function before = %s', function)
            function = function.replace('array1', variable)
            logger.debug('function after = %s', function)

            task = {}

            task['array_input'] = []
            task['array_input'].append(variable)
            task['orig_function'] = orig_function
            task['function'] = function
            task['expression'] = 'none'
            task['dimension'] = copy.deepcopy(dimensions)

            task['array_output'] = copy.deepcopy(arrays.values()[0]['array_output'])
            task['array_output']['variable'] = name
            task['array_output']['dimensions_order'] = \
                self.diff_list(arrays.values()[0]['array_output']['dimensions_order'], dimensions)

            result = ()
            for value in task['array_output']['dimensions_order']:
                input_task = self.task(task['array_input'][0])
                index = input_task.values()[0]['array_output']['dimensions_order'].index(value)
                value = input_task.values()[0]['array_output']['shape'][index]
                result += (value,)
            task['array_output']['shape'] = result
            task['operation_type'] = OPERATION_TYPE.Reduction

            return self.add_to_plan(name, task)

    def diff_list(self, list1, list2):
        """find items in list1 that are not in list2"""
        list2 = set(list2)
        return [result for result in list1 if result not in list2]

    def get_predefined_inputs(self, storage_type, function):
        """Helper function to retrieve predefined inputs from look up table"""
        return self.OPERATORS_SENSOR_SPECIFIC_BANDMATH.get(function).get('sensors').get(storage_type).get('input')

    def get_predefined_function(self, storage_type, function):
        """Helper function to retrieve predefined functions from look up table"""
        function_id = self.OPERATORS_SENSOR_SPECIFIC_BANDMATH.get(function) \
            .get('sensors').get(storage_type).get('function')
        return self.OPERATORS_SENSOR_SPECIFIC_BANDMATH.get(function).get('functions').get(function_id)
