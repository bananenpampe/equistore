import os

import numpy as np
import pytest

import equistore


DATA_ROOT = os.path.join(os.path.dirname(__file__), "data")


def test_ones_like():
    tensor = equistore.load(
        os.path.join(DATA_ROOT, "qm7-spherical-expansion.npz"),
        # the npz is using DEFLATE compression, equistore only supports STORED
        use_numpy=True,
    )
    ones_tensor = equistore.ones_like(tensor)
    ones_tensor_positions = equistore.ones_like(tensor, gradients="positions")

    assert equistore.equal_metadata(ones_tensor, tensor)

    tensor_no_cell = equistore.remove_gradients(tensor, "cell")
    assert equistore.equal_metadata(ones_tensor_positions, tensor_no_cell)

    # check the values
    for key, block in tensor.items():
        one_block = ones_tensor[key]

        assert np.all(one_block.values == np.ones_like(block.values))

        for parameter, gradient in block.gradients():
            ones_gradient = one_block.gradient(parameter)
            assert np.all(ones_gradient.values == np.ones_like(gradient.values))


def test_ones_like_error():
    tensor = equistore.load(
        os.path.join(DATA_ROOT, "qm7-spherical-expansion.npz"),
        # the npz is using DEFLATE compression, equistore only supports STORED
        use_numpy=True,
    )

    message = "requested gradient 'err' in ones_like is not defined in this tensor"
    with pytest.raises(ValueError, match=message):
        tensor = equistore.ones_like(tensor, gradients=["positions", "err"])


# TODO: add tests with torch & torch scripting/tracing
