import numpy as np

from equistore.core import Labels, TensorBlock, TensorMap


def drop_blocks(tensor: TensorMap, keys: Labels, copy: bool = False) -> TensorMap:
    """
    Drop specified key/block pairs from a TensorMap.

    :param tensor:
        the TensorMap to drop the key-block pair from.

    :param keys:
        a :py:class:`Labels` object containing the keys of the blocks to drop

    :param copy:
        if :py:obj:`True`, the returned :py:class:`TensorMap` is constructed by
        copying the blocks from the input `tensor`. If :py:obj:`False`
        (default), the values of the blocks in the output :py:class:`TensorMap`
        reference the same data as the input `tensor`. The latter can be useful
        for limiting memory usage, but should be used with caution when
        manipulating the underlying data.

    :return:
        the input :py:class:`TensorMap` with the specified key/block pairs
        dropped.
    """
    # Check arg types
    if not isinstance(tensor, TensorMap):
        raise TypeError(
            f"input `tensor` must be a TensorMap, got '{type(tensor)}' instead"
        )
    if not isinstance(keys, Labels):
        raise TypeError(
            f"input `keys` must be a Labels object, got '{type(keys)}' instead"
        )
    if not isinstance(copy, bool):
        raise TypeError(f"`copy` flag must be a boolean, got '{type(copy)}' instead")

    # Find the indices of keys to remove
    tensor_keys = tensor.keys
    _, to_remove, used_in_intersection = tensor_keys.intersection_and_mapping(keys)
    to_remove_indices = np.where(to_remove != -1)[0]

    not_present_in_tensor = np.where(used_in_intersection == -1)[0]
    if len(not_present_in_tensor) != 0:
        key = keys[not_present_in_tensor[0]]
        raise ValueError(f"{key.print()} is not present in this tensor")

    # Create the new TensorMap
    new_blocks = []
    new_keys_values = []
    for i in range(len(tensor_keys)):
        if i in to_remove_indices:
            continue

        new_keys_values.append(tensor_keys[i].values)
        block = tensor[i]

        if copy:
            new_blocks.append(block.copy())
        else:
            # just increase the reference count on everything
            new_block = TensorBlock(
                values=block.values,
                samples=block.samples,
                components=block.components,
                properties=block.properties,
            )

            for parameter, gradient in block.gradients():
                if len(gradient.gradients_list()) != 0:
                    raise NotImplementedError(
                        "gradients of gradients are not supported"
                    )

                new_block.add_gradient(
                    parameter=parameter,
                    gradient=TensorBlock(
                        values=gradient.values,
                        samples=gradient.samples,
                        components=gradient.components,
                        properties=new_block.properties,
                    ),
                )

            new_blocks.append(new_block)

    if len(new_keys_values) != 0:
        new_keys = Labels(keys.names, np.vstack(new_keys_values))
    else:
        new_keys = Labels.empty(keys.names)

    return TensorMap(keys=new_keys, blocks=new_blocks)
