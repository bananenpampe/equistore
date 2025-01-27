import os

import torch

import equistore.torch

from . import utils


def check_tensor(tensor):
    assert tensor.keys.names == [
        "spherical_harmonics_l",
        "center_species",
        "neighbor_species",
    ]
    assert len(tensor.keys) == 27

    block = tensor.block(
        dict(spherical_harmonics_l=2, center_species=6, neighbor_species=1)
    )
    assert block.samples.names == ["structure", "center"]
    assert block.values.shape == (9, 5, 3)

    gradient = block.gradient("positions")
    assert gradient.samples.names == ["sample", "structure", "atom"]
    assert gradient.values.shape == (59, 3, 5, 3)


def test_load():
    loaded = equistore.torch.load(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            "equistore",
            "tests",
            "data.npz",
        ),
    )

    check_tensor(loaded)


def test_save(tmpdir):
    """Check that we can save and load a tensor to a file"""
    tmpfile = "serialize-test.npz"

    tensor = utils.tensor(dtype=torch.float64)

    with tmpdir.as_cwd():
        equistore.torch.save(tmpfile, tensor)
        data = equistore.torch.load(tmpfile)

    assert len(data.keys) == 4


def test_pickle(tmpdir):
    tensor = equistore.torch.load(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            "equistore",
            "tests",
            "data.npz",
        ),
    )
    tmpfile = "serialize-test.npz"

    with tmpdir.as_cwd():
        torch.save(tensor, tmpfile)
        loaded = torch.load(tmpfile)

    check_tensor(loaded)
