"""
Module for finding unique metadata for TensorMaps and TensorBlocks
"""
from typing import List, Optional, Tuple, Union

import numpy as np

from equistore.core import Labels, TensorBlock, TensorMap


def unique_metadata(
    tensor: TensorMap,
    axis: str,
    names: Union[List[str], Tuple[str], str],
    gradient: Optional[str] = None,
) -> Labels:
    """
    Returns a :py:class:`Labels` object containing the unique metadata across
    all blocks of the input :py:class:`TensorMap`  ``tensor``. Unique Labels are
    returned for the specified ``axis`` (either ``"samples"`` or
    ``"properties"``) and metadata ``names``.

    Passing ``gradient`` as a ``str`` corresponding to a gradient parameter (for
    instance ``"cell"`` or ``"positions"``) returns the unique indices only for
    the gradient blocks. Note that gradient blocks by definition have the same
    properties metadata as their parent :py:class:`TensorBlock`.

    An empty :py:class:`Labels` object is returned if there are no indices in
    the (gradient) blocks of ``tensor`` corresponding to the specified ``axis``
    and ``names``. This will have length zero but the names will be the same as
    passed in ``names``.

    For example, to find the unique ``"structure"`` indices in the ``"samples"``
    metadata present in a given :py:class:`TensorMap`:

    .. code-block:: python

        import equistore

        unique_structures = equistore.unique_metadata(
            tensor,
            axis="samples",
            names=["structure"],
        )

    Or, to find the unique ``"atom"`` indices in the ``"samples"`` metadata
    present in the ``"positions"`` gradient blocks of a given
    :py:class:`TensorMap`:

    .. code-block:: python

        unique_grad_atoms = equistore.unique_metadata(
            tensor,
            axis="samples",
            names=["atom"],
            gradient="positions",
        )

    The unique indices can then be used to split the :py:class:`TensorMap` into
    several smaller :py:class:`TensorMap` objects. Say, for example, that the
    ``unique_structures`` from the example above are:

    .. code-block:: python

        Labels(
            [(0,), (1,), (2,), (3,), (4,), (5,), (6,), (7,), (8,), (9,)],
            dtype=[("structure", "<i4")],
        )

    Then, the following code will split the :py:class:`TensorMap` into 2
    :py:class:`TensorMap` objects, with first containing structure indices 0-3
    and the second containing structure indices 4-9:

    .. code-block:: python

        import equistore

        [tensor_1, tensor_2] = equistore.split(
            tensor,
            axis="samples",
            grouped_labels=[unique_structures[:4], unique_structures[4:]],
        )

    :param tensor: the :py:class:`TensorMap` to find unique indices for.
    :param axis: a ``str``, either ``"samples"`` or ``"properties"``,
        corresponding to the ``axis`` along which the named unique indices
        should be found.
    :param names: a ``str``, ``list`` of ``str``, or ``tuple`` of ``str``
        corresponding to the name(s) of the indices along the specified ``axis``
        for which the unique values should be found.
    :param gradient: a ``str`` corresponding to the gradient parameter name for
        the gradient blocks to find the unique indices for. If :py:obj:`None`
        (default), the unique indices of the regular :py:class:`TensorBlock`
        objects will be calculated.

    :return: a sorted :py:class:`Labels` object containing the unique metadata
        for the blocks of the input ``tensor`` or its gradient blocks for the
        specified parameter. Each element in the returned :py:class:`Labels`
        object has len(``names``) entries.
    """
    # Parse input args
    if not isinstance(tensor, TensorMap):
        raise TypeError("`tensor` argument must be an equistore TensorMap")
    names = (
        [names]
        if isinstance(names, str)
        else (list(names) if isinstance(names, tuple) else names)
    )
    _check_args(tensor, axis, names, gradient)
    # Make a list of the blocks to find unique indices for
    if gradient is None:
        blocks = tensor.blocks()
    else:
        blocks = [block.gradient(gradient) for block in tensor]

    return _unique_from_blocks(blocks, axis, names)


def unique_metadata_block(
    block: TensorBlock,
    axis: str,
    names: Union[List[str], Tuple[str], str],
    gradient: Optional[str] = None,
) -> Labels:
    """
    Returns a :py:class:`Labels` object containing the unique metadata in the
    input :py:class:`TensorBlock`  ``block``, for the specified ``axis`` (either
    ``"samples"`` or ``"properties"``) and metadata ``names``.

    Passing ``gradient`` as a ``str`` corresponding to a gradient parameter (for
    instance ``"cell"`` or ``"positions"``) returns the unique indices only for
    the gradient block associated with ``block``. Note that gradient blocks by
    definition have the same properties metadata as their parent
    :py:class:`TensorBlock`.

    An empty :py:class:`Labels` object is returned if there are no indices in
    the (gradient) blocks of ``tensor`` corresponding to the specified ``axis``
    and ``names``. This will have length zero but the names will be the same as
    passed in ``names``.

    For example, to find the unique ``"structure"`` indices in the ``"samples"``
    metadata present in a given :py:class:`TensorBlock`:

    .. code-block:: python

        import equistore

        unique_samples = equistore.unique_metadata_block(
            block,
            axis="samples",
            names=["structure"],
        )

    To find the unique ``"atom"`` indices along the ``"samples"`` axis present
    in the ``"positions"`` gradient block of a given :py:class:`TensorBlock`:

    .. code-block:: python

        unique_grad_samples = equistore.unique_metadata_block(
            block,
            axis="samples",
            names=["atom"],
            gradient="positions",
        )

    :param block: the :py:class:`TensorBlock` to find unique indices for.
    :param axis: a str, either ``"samples"`` or ``"properties"``, corresponding
        to the ``axis`` along which the named unique metadata should be found.
    :param names: a ``str``, ``list`` of ``str``, or ``tuple`` of ``str``
        corresponding to the name(s) of the metadata along the specified
        ``axis`` for which the unique indices should be found.
    :param gradient: a ``str`` corresponding to the gradient parameter name for
        the gradient blocks to find the unique metadata for. If :py:obj:`None`
        (default), the unique metadata of the regular :py:class:`TensorBlock`
        objects will be calculated.

    :return: a sorted :py:class:`Labels` object containing the unique metadata
        for the input ``block`` or its gradient for the specified parameter.
        Each element in the returned :py:class:`Labels` object has
        len(``names``) entries.
    """
    # Parse input args
    if not isinstance(block, TensorBlock):
        raise TypeError("`block` argument must be an equistore TensorBlock")
    names = (
        [names]
        if isinstance(names, str)
        else (list(names) if isinstance(names, tuple) else names)
    )
    _check_args(block, axis, names, gradient)

    # Make a list of the blocks to find unique indices for
    if gradient is None:
        blocks = [block]
    else:
        blocks = [block.gradient(gradient)]

    return _unique_from_blocks(blocks, axis, names)


def _unique_from_blocks(
    blocks: List[TensorBlock],
    axis: str,
    names: List[str],
) -> Labels:
    """
    Finds the unique metadata of a list of blocks along the given ``axis`` and
    for the specified ``names``.
    """
    all_values = []
    for block in blocks:
        if axis == "samples":
            all_values.append(block.samples.view(names).values)
        else:
            assert axis == "properties"
            all_values.append(block.properties.view(names).values)

    unique_values = np.unique(np.vstack(all_values), axis=0)
    return Labels(names=names, values=unique_values)


def _check_args(
    tensor: Union[TensorMap, TensorBlock],
    axis: str,
    names: List[str],
    gradient: Optional[str] = None,
):
    """Checks input args for `unique_metadata` and `unique_metadata_block`"""
    # Check tensors
    if isinstance(tensor, TensorMap):
        blocks = tensor.blocks()
        if gradient is not None:
            if not isinstance(gradient, str):
                raise TypeError(
                    f"`gradient` argument must be a `str`, not {type(gradient)}"
                )
            if not np.all([block.has_gradient(gradient) for block in blocks]):
                raise ValueError(
                    f"not all input blocks have a gradient with respect to '{gradient}'"
                )
            blocks = [block.gradient(gradient) for block in blocks]  # redefine blocks

    elif isinstance(tensor, TensorBlock):
        blocks = [tensor]
        if gradient is not None:
            if not isinstance(gradient, str):
                raise TypeError(
                    f"`gradient` argument must be a str, not {type(gradient)}"
                )
            if not tensor.has_gradient(gradient):
                raise ValueError(
                    f"input block does not have a gradient with respect to '{gradient}'"
                )
            blocks = [tensor.gradient(gradient)]

    if not isinstance(axis, str):
        raise TypeError(
            "`axis` argument must be a str, either `'samples'` or `'properties'`,"
            + f" not {type(axis)}"
        )
    if axis not in ["samples", "properties"]:
        raise ValueError("`axis` argument must be either `'samples'` or `'properties'`")

    if not isinstance(names, list):
        raise TypeError(f"`names` argument must be a list of str, not {type(names)}")

    if not np.all([isinstance(name, str) for name in names]):
        raise TypeError(
            "`names` argument must be a list of str, "
            + f"not {[type(name) for name in names]}"
        )
