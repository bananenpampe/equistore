import copy
import ctypes
import sys
from typing import Dict, List, Sequence, Tuple, Union


if (sys.version_info.major >= 3) and (sys.version_info.minor >= 8):
    from pickle import PickleBuffer

import numpy as np

from ._c_api import c_uintptr_t, eqs_block_t, eqs_labels_t
from ._c_lib import _get_library
from .block import TensorBlock
from .labels import Labels, LabelsEntry
from .status import _check_pointer


class TensorMap:
    """
    A TensorMap is the main user-facing class of this library, and can store any kind of
    data used in atomistic machine learning similar to a Python :py:class:`dict`.

    A tensor map contains a list of :py:class:`TensorBlock`, each one associated with a
    key. A blocks can either accessed one by one with the :py:func:`TensorMap.block`
    function, or by iterating over the tensor map itself:

    .. code-block:: python

        for block in tensor:
            ...

    The corresponding keys can be included in the loop by using the ``items()`` method
    of a :py:func:`TensorMap`:

    .. code-block:: python

        for key, block in tensor.items():
            ...

    A tensor map provides functions to move some of these keys to the samples or
    properties labels of the blocks, moving from a sparse representation of the data to
    a dense one.
    """

    def __init__(self, keys: Labels, blocks: Sequence[TensorBlock]):
        """
        :param keys: keys associated with each block
        :param blocks: set of blocks containing the actual data
        """
        assert isinstance(keys, Labels)

        self._lib = _get_library()

        blocks_array_t = ctypes.POINTER(eqs_block_t) * len(blocks)
        blocks_array = blocks_array_t(*[block._ptr for block in blocks])

        for block in blocks:
            if block._parent is not None:
                raise ValueError(
                    "can not use blocks from another tensor map in a new one, "
                    "use TensorBlock.copy() to make a copy of each block first"
                )

        # all blocks are moved into the tensor map, assign NULL to `block._ptr` to
        # prevent accessing invalid data from Python and double free
        for block in blocks:
            block._move_ptr()

        self._ptr = self._lib.eqs_tensormap(
            keys._as_eqs_labels_t(), blocks_array, len(blocks)
        )
        _check_pointer(self._ptr)

        for block in blocks:
            block._is_inside_map = True

    @staticmethod
    def _from_ptr(ptr):
        """Create a tensor map from a pointer owning its data"""
        _check_pointer(ptr)
        obj = TensorMap.__new__(TensorMap)
        obj._lib = _get_library()
        obj._ptr = ptr
        obj._blocks = []
        return obj

    @classmethod
    def _from_pickle(cls, buffer: Union[bytes, bytearray]):
        """
        Passed to pickler to reconstruct TensorMap from bytes object
        """
        from .io import create_numpy_array, load_buffer_custom_array

        # TODO: make it so when saving data in torch tensors, we load back data in torch
        # tensors.
        return load_buffer_custom_array(buffer, create_numpy_array)

    def __del__(self):
        if hasattr(self, "_lib") and self._lib is not None and hasattr(self, "_ptr"):
            self._lib.eqs_tensormap_free(self._ptr)

    def __copy__(self):
        raise ValueError(
            "shallow copies of TensorMap are not possible, use a deepcopy instead"
        )

    def __deepcopy__(self, _memodict):
        new_ptr = self._lib.eqs_tensormap_copy(self._ptr)
        return TensorMap._from_ptr(new_ptr)

    def copy(self) -> "TensorMap":
        """
        Get a deep copy of this TensorMap, including all the data and metadata
        """
        return copy.deepcopy(self)

    def __reduce_ex__(self, protocol: int):
        """
        Used by the Pickler to dump TensorMap object to bytes object. When protocol >= 5
        it supports PickleBuffer which reduces number of copies needed
        """
        import equistore.core

        buffer = equistore.core.io.save_buffer_raw_(self)
        if protocol >= 5:
            return self._from_pickle, (PickleBuffer(buffer),)
        else:
            return self._from_pickle, (buffer.raw,)

    def __len__(self):
        return len(self.keys)

    def __repr__(self) -> str:
        return self.print(4)

    def __str__(self) -> str:
        return self.print(-1)

    def __getitem__(self, selection) -> TensorBlock:
        """This is equivalent to self.block(selection)"""
        return self.block(selection)

    def __eq__(self, other):
        from equistore.operations import equal

        return equal(self, other)

    def __ne__(self, other):
        from equistore.operations import equal

        return not equal(self, other)

    def __add__(self, other):
        from equistore.operations import add

        return add(self, other)

    def __sub__(self, other):
        from equistore.operations import subtract

        return subtract(self, other)

    def __mul__(self, other):
        from equistore.operations import multiply

        return multiply(self, other)

    def __matmul__(self, other):
        from equistore.operations import dot

        return dot(self, other)

    def __truediv__(self, other):
        from equistore.operations import divide

        return divide(self, other)

    def __pow__(self, other):
        from equistore.operations import pow

        return pow(self, other)

    def __neg__(self):
        from equistore.operations import multiply

        return multiply(self, -1)

    def __pos__(self):
        return self

    @property
    def keys(self) -> Labels:
        """The set of keys labeling the blocks in this tensor map."""
        result = eqs_labels_t()
        self._lib.eqs_tensormap_keys(self._ptr, result)
        return Labels._from_eqs_labels_t(result)

    def block_by_id(self, index: int) -> TensorBlock:
        """
        Get the block at ``index`` in this :py:class:`TensorMap`.

        :param index: index of the block to retrieve
        """
        if index >= len(self):
            # we need to raise IndexError to make sure TensorMap supports iterations
            # over blocks with `for block in tensor:` which calls `__getitem__` with
            # integers from 0 to whenever IndexError is raised.
            raise IndexError(
                f"block index out of bounds: we have {len(self)} blocks but the "
                f"index is {index}"
            )

        block = ctypes.POINTER(eqs_block_t)()
        self._lib.eqs_tensormap_block_by_id(self._ptr, block, index)
        return TensorBlock._from_ptr(block, parent=self)

    def blocks_by_id(self, indices: Sequence[int]) -> TensorBlock:
        """
        Get the blocks with the given ``indices`` in this :py:class:`TensorMap`.

        :param indices: indices of the block to retrieve
        """
        return [self.block_by_id(i) for i in indices]

    def blocks_matching(self, selection: Labels) -> List[int]:
        """
        Get a (possibly empty) list of block indexes matching the ``selection``.

        This function finds all keys in this :py:class:`TensorMap` with the same values
        as ``selection`` for the dimensions/names contained in the ``selection``; and
        return the corresponding indexes.

        The ``selection`` should contain a single entry.
        """
        block_indexes = ctypes.ARRAY(c_uintptr_t, len(self.keys))()
        count = c_uintptr_t(block_indexes._length_)

        self._lib.eqs_tensormap_blocks_matching(
            self._ptr,
            block_indexes,
            count,
            selection._as_eqs_labels_t(),
        )

        result = []
        for i in range(count.value):
            result.append(int(block_indexes[i]))

        return result

    def block(
        self,
        selection: Union[None, int, Labels, LabelsEntry, Dict[str, int]] = None,
        **kwargs,
    ) -> TensorBlock:
        """
        Get the single block in this :py:class:`TensorMap` matching the ``selection``.

        When ``selection`` is an ``int``, this is equivalent to
        :py:func:`TensorMap.block_by_id`.

        When ``selection`` is an :py:class:`Labels`, it should only contain a single
        entry, which will be used for the selection.

        When ``selection`` is a ``Dict[str, int]``, it is converted into a single single
        :py:class:`LabelsEntry` (the dict keys becoming the names and the dict values
        being joined together to form the :py:class:`LabelsEntry` values), which is then
        used for the selection.

        When ``selection`` is a :py:class:`LabelsEntry`, this function finds the key in
        this :py:class:`TensorMap` with the same values as ``selection`` for the
        dimensions/names contained in the ``selection``; and return the corresponding
        indexes.

        If ``selection`` is :py:obj:`None`, the selection can be passed as keyword
        arguments, which will be converted to a ``Dict[str, int]``.

        :param selection: description of the block to extract

        >>> from equistore import TensorMap, TensorBlock, Labels
        >>> keys = Labels(["key_1", "key_2"], np.array([[0, 0], [6, 8]]))
        >>> block_1 = TensorBlock(
        ...     values=np.full((3, 5), 1.0),
        ...     samples=Labels.range("sample", 3),
        ...     components=[],
        ...     properties=Labels.range("property", 5),
        ... )
        >>> block_2 = TensorBlock(
        ...     values=np.full((5, 3), 2.0),
        ...     samples=Labels.range("sample", 5),
        ...     components=[],
        ...     properties=Labels.range("property", 3),
        ... )
        >>> tensor = TensorMap(keys, [block_1, block_2])
        >>> # numeric index selection, this gives a block by its position
        >>> block = tensor.block(0)
        >>> block
        TensorBlock
            samples (3): ['sample']
            components (): []
            properties (5): ['property']
            gradients: None
        >>> # This is the first block
        >>> block.values.mean()
        1.0
        >>> # use a single key entry (i.e. LabelsEntry) for the selection
        >>> tensor.block(tensor.keys[0]).values.mean()
        1.0
        >>> # Labels with a single entry selection
        >>> labels = Labels(names=["key_1", "key_2"], values=np.array([[6, 8]]))
        >>> tensor.block(labels).values.mean()
        2.0
        >>> # keyword arguments selection
        >>> tensor.block(key_1=0, key_2=0).values.mean()
        1.0
        >>> # dictionary selection
        >>> tensor.block({"key_1": 6, "key_2": 8}).values.mean()
        2.0
        """
        if selection is None:
            return self.block(kwargs)
        elif isinstance(selection, int):
            return self.block_by_id(selection)
        else:
            selection = _normalize_selection(selection)

        matching = self.blocks_matching(selection)

        if len(matching) == 0:
            if len(self.keys) == 0:
                raise ValueError("there are no blocks in this TensorMap")
            else:
                raise ValueError(
                    f"couldn't find any block matching {selection[0].print()}"
                )
        elif len(matching) > 1:
            raise ValueError(
                f"more than one block matched {selection[0].print()}, "
                "use `TensorMap.blocks` to get all of them"
            )
        else:
            return self.block_by_id(matching[0])

    def blocks(
        self,
        selection: Union[
            None, Sequence[int], int, Labels, LabelsEntry, Dict[str, int]
        ] = None,
        **kwargs,
    ) -> List[TensorBlock]:
        """
        Get the blocks in this :py:class:`TensorMap` matching the ``selection``.

        When ``selection`` is ``None`` (the default), all blocks are returned.

        When ``selection`` is an ``int``, this is equivalent to
        :py:func:`TensorMap.block_by_id`; and for a ``List[int]`` this is equivalent to
        :py:func:`TensorMap.blocks_by_id`.

        When ``selection`` is an :py:class:`Labels`, it should only contain a single
        entry, which will be used for the selection.

        When ``selection`` is a ``Dict[str, int]``, it is converted into a single single
        :py:class:`LabelsEntry` (the dict keys becoming the names and the dict values
        being joined together to form the :py:class:`LabelsEntry` values), which is then
        used for the selection.

        When ``selection`` is a :py:class:`LabelsEntry`, this function finds all keys in
        this :py:class:`TensorMap` with the same values as ``selection`` for the
        dimensions/names contained in the ``selection``; and return the corresponding
        blocks.

        If ``selection`` is :py:obj:`None`, the selection can be passed as keyword
        arguments, which will be converted to a ``Dict[str, int]``.

        :param selection: description of the blocks to extract
        """
        if selection is None:
            return self.blocks(kwargs)
        elif isinstance(selection, int):
            return [self.block_by_id(selection)]
        else:
            selection = _normalize_selection(selection)

        matching = self.blocks_matching(selection)

        if len(self.keys) == 0:
            # return an empty list here instead of the top of this function to make sure
            # the selection was validated
            return []

        if len(matching) == 0:
            raise ValueError(
                f"Couldn't find any block matching '{selection[0].print()}'"
            )
        else:
            return self.blocks_by_id(matching)

    def items(self):
        """get an iterator over (key, block) pairs in this :py:class:`TensorMap`"""
        keys = self.keys
        for i, key in enumerate(keys):
            yield key, self.block_by_id(i)

    def keys_to_samples(
        self,
        keys_to_move: Union[str, Sequence[str]],
        *,
        sort_samples=True,
    ) -> "TensorMap":
        """
        Merge blocks along the samples axis, adding ``keys_to_move`` to the end of the
        samples labels dimensions.

        This function will remove ``keys_to_move`` from the keys, and find all blocks
        with the same remaining keys values. It will then merge these blocks along the
        samples direction (i.e. do a *vertical* concatenation), adding ``keys_to_move``
        to the end of the samples labels dimensions. The values taken by
        ``keys_to_move`` in the new samples labels will be the values of these
        dimensions in the merged blocks' keys.

        If ``keys_to_move`` is a set of :py:class:`Labels`, it must be empty
        (``keys_to_move.values.shape[0] == 0``), and only the :py:class:`Labels.names`
        will be used.

        The order of the samples is controlled by ``sort_samples``. If ``sort_samples``
        is true, samples are re-ordered to keep them lexicographically sorted. Otherwise
        they are kept in the order in which they appear in the blocks.

        This function is only implemented when the blocks to merge have the same
        properties values.

        :param keys_to_move: description of the keys to move
        :param sort_samples: whether to sort the merged samples or keep them in the
            order in which they appear in the original blocks
        :return: a new :py:class:`TensorMap` with merged blocks
        """
        keys_to_move = _normalize_keys_to_move(keys_to_move)

        ptr = self._lib.eqs_tensormap_keys_to_samples(
            self._ptr, keys_to_move._as_eqs_labels_t(), sort_samples
        )
        return TensorMap._from_ptr(ptr)

    def components_to_properties(
        self, dimensions: Union[str, Sequence[str]]
    ) -> "TensorMap":
        """
        Move the given ``dimensions`` from the component labels to the property labels
        for each block.

        :param dimensions: name of the component dimensions to move to the properties
        """
        c_dimensions = _list_or_str_to_array_c_char(dimensions)

        ptr = self._lib.eqs_tensormap_components_to_properties(
            self._ptr, c_dimensions, c_dimensions._length_
        )
        return TensorMap._from_ptr(ptr)

    def keys_to_properties(
        self,
        keys_to_move: Union[str, Sequence[str], Labels],
        *,
        sort_samples=True,
    ) -> "TensorMap":
        """
        Merge blocks along the properties direction, adding ``keys_to_move`` at the
        beginning of the properties labels dimensions.

        This function will remove ``keys_to_move`` from the keys, and find all blocks
        with the same remaining keys values. Then it will merge these blocks along the
        properties direction (i.e. do an *horizontal* concatenation).

        If ``keys_to_move`` is given as strings, then the new property labels will
        **only** contain entries from the existing blocks. For example, merging a block
        with key ``a=0`` and properties ``p=1, 2`` with a block with key ``a=2`` and
        properties ``p=1, 3`` will produce a block with properties ``a, p = (0, 1), (0,
        2), (2, 1), (2, 3)``.

        If ``keys_to_move`` is a set of :py:class:`Labels` and it is empty
        (``len(keys_to_move) == 0``), the :py:class:`Labels.names` will be used as if
        they where passed directly.

        Finally, if ``keys_to_move`` is a non empty set of :py:class:`Labels`, the new
        properties labels will contains **all** of the entries of ``keys_to_move``
        (regardless of the values taken by ``keys_to_move.names`` in the merged blocks'
        keys) followed by the existing properties labels. For example, using ``a=2, 3``
        in ``keys_to_move``, blocks with properties ``p=1, 2`` will result in ``a, p =
        (2, 1), (2, 2), (3, 1), (3, 2)``. If there is no values (no block/missing
        sample) for a given property in the merged block, then the value will be set to
        zero.

        When using a non empty :py:class:`Labels` for ``keys_to_move``, the properties
        labels of all the merged blocks must take the same values.

        The order of the samples in the merged blocks is controlled by ``sort_samples``.
        If ``sort_samples`` is :py:obj:`True`, samples are re-ordered to keep them
        lexicographically sorted. Otherwise they are kept in the order in which they
        appear in the blocks.

        :param keys_to_move: description of the keys to move
        :param sort_samples: whether to sort the merged samples or keep them in the
            order in which they appear in the original blocks
        :return: a new :py:class:`TensorMap` with merged blocks
        """
        keys_to_move = _normalize_keys_to_move(keys_to_move)
        ptr = self._lib.eqs_tensormap_keys_to_properties(
            self._ptr, keys_to_move._as_eqs_labels_t(), sort_samples
        )
        return TensorMap._from_ptr(ptr)

    @property
    def sample_names(self) -> Tuple[str]:
        """names of the sample labels for all blocks in this tensor map"""
        if len(self.keys) == 0:
            return tuple()

        return self.block(0).samples.names

    @property
    def components_names(self) -> List[Tuple[str]]:
        """names of the component labels for all blocks in this tensor map"""
        if len(self.keys) == 0:
            return []

        return [c.names for c in self.block(0).components]

    @property
    def property_names(self) -> Tuple[str]:
        """names of the property labels for all blocks in this tensor map"""
        if len(self.keys) == 0:
            return tuple()

        return self.block(0).properties.names

    def print(self, max_keys: int) -> str:
        """
        Print this :py:class:`TensorMap` to a string, including at most ``max_keys`` in
        the output.

        :param max_keys: how many keys to include in the output. Use ``-1`` to include
            all keys.
        """

        result = f"TensorMap with {len(self)} blocks\nkeys:"
        result += self.keys.print(max_entries=max_keys, indent=5)
        return result


def _normalize_keys_to_move(keys_to_move: Union[str, Sequence[str], Labels]) -> Labels:
    if isinstance(keys_to_move, str):
        keys_to_move = (keys_to_move,)

    if not isinstance(keys_to_move, Labels):
        for key in keys_to_move:
            assert isinstance(key, str)

        keys_to_move = Labels(
            names=keys_to_move,
            values=np.zeros((0, len(keys_to_move))),
        )

    return keys_to_move


def _list_or_str_to_array_c_char(strings: Union[str, Sequence[str]]):
    if isinstance(strings, str):
        strings = [strings]

    c_strings = ctypes.ARRAY(ctypes.c_char_p, len(strings))()
    for i, v in enumerate(strings):
        assert isinstance(v, str)
        c_strings[i] = v.encode("utf8")

    return c_strings


def _normalize_selection(
    selection: Union[Labels, LabelsEntry, Dict[str, int]]
) -> Labels:
    if isinstance(selection, dict):
        for key, value in selection.items():
            if not np.can_cast(value, np.int32, casting="same_kind"):
                raise TypeError(
                    f"expected integer values in selection, got {key}={value} of "
                    f"type {type(value)}"
                )

        return Labels(
            list(selection.keys()),
            np.array([[np.int32(v) for v in selection.values()]], dtype=np.int32),
        )

    elif isinstance(selection, Labels):
        return selection

    elif isinstance(selection, LabelsEntry):
        return Labels(selection.names, selection.values.reshape(1, -1))

    else:
        raise TypeError(f"invalid type for block selection: {type(selection)}")
