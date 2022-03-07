from collections import namedtuple
from typing import List
import numpy as np
import ctypes

from ._c_api import aml_labels_t


class Labels(np.ndarray):
    """
    This is a small wrapper around a 2D ``numpy.ndarray`` that adds a ``names``
    attribute containing the names of the columns.

    .. py:attribute:: name
        :type: Tuple[str]

        name of each column in this labels array
    """

    def __new__(cls, names: List[str], values: np.ndarray):
        if not isinstance(values, np.ndarray):
            raise ValueError("values parameter must be a numpy ndarray")

        if len(values.shape) != 2:
            raise ValueError("values parameter must be a 2D array")

        names = tuple(str(n) for n in names)

        if len(names) != values.shape[1]:
            raise ValueError(
                "names parameter must have an entry for each column of the array"
            )

        if values.dtype != np.int32:
            raise ValueError("values parameter must be an array of 32-bit integers")

        values = np.ascontiguousarray(values)
        dtype = [(name, np.int32) for name in names]

        if values.shape[1] != 0:
            values = values.view(dtype=dtype).reshape((values.shape[0],))

            if len(np.unique(values)) != len(values):
                raise ValueError("values in Labels must be unique")

        obj = values.view(cls)

        return obj

    @property
    def names(self):
        return self.dtype.names or []

    @staticmethod
    def empty(names):
        assert len(names) > 0
        return Labels(
            names=names, values=np.empty(shape=(0, len(names)), dtype=np.int32)
        )

    @staticmethod
    def single():
        return Labels(
            names=["single_entry"], values=np.zeros(shape=(1, 1), dtype=np.int32)
        )

    def as_namedtuples(self):
        named_tuple_class = namedtuple("LabelTuple", self.names)
        named_tuple_class.as_dict = named_tuple_class._asdict

        for entry in self:
            yield named_tuple_class(*entry)

    def _as_aml_labels_t(self):
        aml_labels = aml_labels_t()

        names = ctypes.ARRAY(ctypes.c_char_p, len(self.names))()
        for i, n in enumerate(self.names):
            names[i] = n.encode("utf8")

        aml_labels.names = names
        aml_labels.size = len(names)
        aml_labels.values = self.ctypes.data_as(ctypes.POINTER(ctypes.c_int32))
        aml_labels.count = self.shape[0]

        return aml_labels

    @staticmethod
    def _from_aml_labels_t(labels):
        names = []
        for i in range(labels.size):
            names.append(labels.names[i].decode("utf8"))

        if labels.count != 0:
            shape = (labels.count, labels.size)
            values = _ptr_to_ndarray(ptr=labels.values, shape=shape, dtype=np.int32)
            values.flags.writeable = False
            return Labels(names, values)
        else:
            return Labels.empty(names)


def _is_namedtuple(x):
    t = type(x)
    b = t.__bases__
    if len(b) != 1 or b[0] != tuple:
        return False
    f = getattr(t, "_fields", None)
    if not isinstance(f, tuple):
        return False
    return all(type(n) == str for n in f)


def _ptr_to_ndarray(ptr, shape, dtype):
    assert len(shape) == 2
    assert shape[1] != 0 and ptr is not None
    array = np.ctypeslib.as_array(ptr, shape=shape)
    assert array.dtype == dtype
    return array