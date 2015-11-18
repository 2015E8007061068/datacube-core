#    Copyright 2015 Geoscience Australia
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.


from __future__ import absolute_import, division, print_function
from collections import namedtuple

import sys

from functools import reduce as reduce_
import numpy

from .indexing import make_index, index_shape, normalize_index, Range

try:
    from xray import DataArray
except ImportError:
    from .ghetto import DataArray

Coordinate = namedtuple('Coordinate', ('dtype', 'begin', 'end', 'length'))
Variable = namedtuple('Variable', ('dtype', 'nodata', 'dimensions', 'units'))


def is_consistent_coords(coord1, coord2):
    return coord1.dtype == coord2.dtype and (coord1.begin > coord1.end) == (coord2.begin > coord2.end)


def comp_dict(d1, d2, p):
    return len(d1) == len(d2) and all(k in d2 and p(d1[k], d2[k]) for k in d1)


def is_consistent_coord_set(coords1, coords2):
    return comp_dict(coords1, coords2, is_consistent_coords)


class StorageUnitBase(object):
    """
    :type coordinates: dict[str, Coordinate]
    :type variables: dict[str, Variable]
    """

    def get(self, name, dest=None, **kwargs):
        """
        Return portion of a variable data as a DataArray
        Slice is defined by specifying keyword arguments with coordinate names
        Use builtin slice object is used for integer indexing,
        User indexing.Range object for labels indexing

        Example:
          su.get('B2', time=slice(3,6), longitude=Range(151.5, 151.7), latitude=Range(-29.5, -29.2))

        :param name: name of the variable
        :param dest: where to put the data
        :type name: str
        :type dest: numpy.array
        :rtype: DataArray
        """
        var = self.variables[name]
        coords, index = zip(*[self.get_coord(dim, kwargs.get(dim)) for dim in var.dimensions])
        shape = index_shape(index)

        if dest is None:
            dest = numpy.empty(shape, dtype=var.dtype)
        else:
            dest = dest[tuple(slice(c) for c in shape)]
        self._fill_data(name, index, dest)

        return DataArray(dest, coords=coords, dims=var.dimensions)

    def coord_slice(self, dim, range_=None):
        """
        Convert label index into integer index for a specific coordinate

        :param dim: name of the dimension
        :param range_: range of coordinate labest
        :type dim: str
        :type range_: Range
        :rtype: slice
        """
        assert isinstance(range_, Range)
        return self.get_coord(dim, range_)[1]

    def get_coord(self, dim, index=None):
        """
        Return portion of the coordinate data
        Slice is defined by specifying keyword arguments with coordinate names
        Use builtin slice object is used for integer indexing,
        User indexing.Range object for labels indexing

        :param dim: name of the dimension
        :param index: index
        :type dim: str
        :type index: slice | Range
        :rtype: numpy.array
        """
        coord = self._get_coord(dim)
        index = make_index(coord, index)
        return coord[index], index

    def _get_coord(self, name):
        """
        :return coordinate labels
        :param name: name of the coordinate
        :type name: str
        :rtype numpy.array
        """
        raise RuntimeError("should override get_coord unless you know what you're doing")

    def _fill_data(self, name, index, dest):
        """
        :param name: name of the variable
        :param index: slice description
        :param dest: where to put the data
        :type name: str
        :type index: tuple[slice]
        :type dest: numpy.array
        """
        raise NotImplementedError()


class StorageUnitVariableProxy(StorageUnitBase):
    """
    Proxy remapping variable names
    """
    def __init__(self, storage_unit, varmap):
        """
        :param storage_unit: storage unit to proxy
        :param varmap: dictionary mapping new names to old ones
        :type storage_unit: StorageUnitBase
        :type varmap: dict[str, str]
        """
        # TODO: check _storage_unit has all the vars in varmap
        self._storage_unit = storage_unit
        self._new2old = varmap
        self._old2new = {name: key for key, name in varmap.items()}

    @property
    def coordinates(self):
        return self._storage_unit.coordinates

    @property
    def variables(self):
        return {self._old2new[name]: value
                for name, value in self._storage_unit.variables.items()
                if name in self._old2new}

    def coord_slice(self, dim, range_=None):
        return self._storage_unit.coord_slice(dim, range_)

    def get_coord(self, dim, index=None):
        return self._storage_unit.get_coord(dim, index)

    def _fill_data(self, name, index, dest):
        self._storage_unit._fill_data(self._new2old[name], index, dest)  # pylint: disable=protected-access


class StorageUnitDimensionProxy(StorageUnitBase):
    """
    Proxy adding extra dimensions
    """
    def __init__(self, storage_unit, *coords):
        """
        :param storage_unit: storage unit to proxy
        :param coords: list of name: value pairs for the new dimensions
        :type storage_unit: StorageUnitBase
        :type coords: list[str, T]
        """
        self._storage_unit = storage_unit
        self._dimensions = tuple(name for name, value in coords)
        self.coordinates = {name: Coordinate(getattr(value, 'dtype', numpy.dtype(type(value))), value, value, 1)
                            for name, value in coords}
        self.coordinates.update(storage_unit.coordinates)

        def expand_var(var):
            return Variable(var.dtype, var.nodata, self._dimensions + var.dimensions, var.units)
        self.variables = {name: expand_var(var) for name, var in storage_unit.variables.items()}

    def coord_slice(self, dim, range_=None):
        if dim in self._dimensions:
            return self.get_coord(dim, range_)[1]
        else:
            return self._storage_unit.coord_slice(dim, range_)

    def get_coord(self, dim, index=None):
        if dim in self._dimensions:
            data = numpy.array([self.coordinates[dim].begin], dtype=self.coordinates[dim].dtype)
            index = make_index(data, index)
            return data[index], index
        else:
            return self._storage_unit.get_coord(dim, index)

    def _fill_data(self, name, index, dest):
        shape = index_shape(index)
        ndims = len(self._dimensions)
        if any(i == 0 for i in shape[:ndims]):
            return dest
        self._storage_unit._fill_data(name, index[ndims:], dest[(0,)*ndims])  # pylint: disable=protected-access


class StorageUnitStack(StorageUnitBase):
    """
    Proxy stacking multiple storage units along a dimension
    """
    def __init__(self, storage_units, stack_dim):
        """
        :param storage_units: storage unit to stack
        :param stack_dim: name of the dimension to stack along
        :type storage_units: list[StorageUnitBase]
        :type stack_dim: str
        """
        for a, b in zip(storage_units[:-1], storage_units[1:]):
            if a.coordinates[stack_dim].begin >= b.coordinates[stack_dim].begin:
                raise RuntimeError("source storage units must be sorted")
            if a.coordinates[stack_dim].end > b.coordinates[stack_dim].begin:
                raise RuntimeError("overlapping coordinates are not supported yet")
        StorageUnitStack.check_consistent(storage_units, stack_dim)

        self._stack_dim = stack_dim
        self._storage_units = storage_units
        self.coordinates = storage_units[0].coordinates.copy()
        self.coordinates[stack_dim] = Coordinate(storage_units[0].coordinates[stack_dim].dtype,
                                                 storage_units[0].coordinates[stack_dim].begin,
                                                 storage_units[-1].coordinates[stack_dim].end,
                                                 sum(su.coordinates[stack_dim].length for su in storage_units))
        self.variables = reduce_(lambda a, b: a.update(b) or a, (su.variables for su in storage_units), {})

    def _get_coord_index(self, index):
        idx = 0
        data = []
        for su in self._storage_units:
            length = su.coordinates[self._stack_dim].length
            if idx < index.stop and idx+length > index.start:
                slice_ = slice(max(0, index.start-idx), min(length, index.stop-idx), index.step)
                data.append(su.get_coord(self._stack_dim, slice_)[0])
            idx += length
            if idx >= index.stop:
                break
        return numpy.concatenate(data), index

    def _get_coord_range(self, range_):
        idx = 0
        data = []
        index = slice(sys.maxsize, 0, 1)
        for su in self._storage_units:
            coord = su.coordinates[self._stack_dim]
            if coord.begin <= coord.end:
                if range_.begin <= coord.end and range_.end >= coord.begin:
                    d = su.get_coord(self._stack_dim, Range(max(range_.begin, coord.begin), min(range_.end, coord.end)))
                    data.append(d[0])
                    index = slice(min(index.start, idx+d[1].start), max(index.stop, idx+d[1].stop), 1)
                if range_.begin > coord.end:
                    break
            else:  # decreasing coord
                if range_.begin <= coord.begin and range_.end >= coord.end:
                    d = su.get_coord(self._stack_dim, Range(max(range_.begin, coord.end), min(range_.end, coord.begin)))
                    data.append(d[0])
                    index = slice(min(index.start, idx+d[1].start), max(index.stop, idx+d[1].stop), 1)
                if range_.end < coord.begin:
                    break
            idx += coord.length
        return numpy.concatenate(data), index

    def get_coord(self, dim, index=None):
        if dim != self._stack_dim:
            return self._storage_units[0].get_coord(dim, index)
        coord = self.coordinates[dim]
        index = normalize_index(coord, index)
        if isinstance(index, Range):
            return self._get_coord_range(index)
        else:
            return self._get_coord_index(index)

    def _fill_data(self, name, index, dest):
        idx = 0
        for su in self._storage_units:
            length = su.coordinates[self._stack_dim].length
            if idx < index[0].stop and idx+length > index[0].start:
                slice_ = slice(max(0, index[0].start-idx), min(length, index[0].stop-idx), index[0].step)
                su_index = (slice_,) + index[1:]
                dest_index = slice(idx+slice_.start-index[0].start, idx+slice_.stop-index[0].start)
                su._fill_data(name, su_index, dest[dest_index])  # pylint: disable=protected-access
            idx += length
            if idx >= index[0].stop:
                break

    @staticmethod
    def check_consistent(storage_units, stack_dim):
        first_coord = storage_units[0].coordinates
        all_vars = dict()

        if stack_dim not in first_coord:
            raise KeyError("dimension to stack along is missing")

        for su in storage_units:
            if (len(su.coordinates) != len(first_coord) or
                    any(k not in su.coordinates or su.coordinates[k] != first_coord[k]
                        for k in first_coord if k != stack_dim)):
                raise RuntimeError("inconsistent coordinates")

            for var in all_vars:
                if var in su.variables and all_vars[var] != su.variables[var]:
                    raise RuntimeError("inconsistent variables")

            all_vars.update(su.variables)
