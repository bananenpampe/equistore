from typing import Union

from ..tensor import TensorMap
from .add import add
from .equal_metadata import _check_maps
from .multiply import multiply


def subtract(A: TensorMap, B: Union[float, TensorMap]) -> TensorMap:
    r"""Return a new :class:`TensorMap` with the values being the subtract
    of ``A`` and ``B``.

    If ``B`` is a :py:class:`TensorMap` it has to have the same metadata as ``A``.

    If gradients are present in ``A``:

    *  ``B`` is a scalar:

       .. math::
            \nabla(A - B) = \nabla A

    * ``B`` is a :py:class:`TensorMap` with the same metadata of ``A``:

       .. math::
            \nabla(A - B) = \nabla A - \nabla B

    :param A: First :py:class:`TensorMap` for the subtraction.
    :param B: Second instance for the subtraction. Parameter can be a scalar or a
              :py:class:`TensorMap`. In the latter case ``B`` must have the same
              metadata of ``A``.

    :return: New :py:class:`TensorMap` with the same metadata as ``A``.
    """
    if isinstance(B, TensorMap):
        _check_maps(A, B, "subtract")
        B = multiply(B, -1)
    else:
        # check if can be converted in float (so if it is a constant value)
        try:
            B = -float(B)
        except TypeError as e:
            raise TypeError("B should be a TensorMap or a scalar value. ") from e
    tensor_result = add(A=A, B=B)

    return tensor_result