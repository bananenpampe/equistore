use std::os::raw::c_char;
use std::ffi::CStr;
use std::convert::{TryFrom, TryInto};
use std::collections::BTreeSet;

use crate::{TensorMap, Labels, TensorBlock, Error};

use super::labels::aml_labels_t;
use super::blocks::aml_block_t;
use super::status::{aml_status_t, catch_unwind};

/// Opaque type representing a `TensorMap`.
#[allow(non_camel_case_types)]
pub struct aml_tensormap_t(TensorMap);

impl std::ops::Deref for aml_tensormap_t {
    type Target = TensorMap;
    fn deref(&self) -> &Self::Target {
        &self.0
    }
}

impl std::ops::DerefMut for aml_tensormap_t {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.0
    }
}


/// Create a new `aml_tensormap_t` with the given `keys` and `blocks`.
/// `blocks_count` must be set to the number of entries in the blocks array.
///
/// The new tensor map takes ownership of the blocks, which should not be
/// released separately.
///
/// The memory allocated by this function and the blocks should be released
/// using `aml_tensormap_free`.
///
/// @param keys labels containing the keys associated with each block
/// @param blocks pointer to the first element of an array of blocks
/// @param blocks_count number of elements in the `blocks` array
///
/// @returns A pointer to the newly allocated tensor map, or a `NULL` pointer in
///          case of error. In case of error, you can use `aml_last_error()`
///          to get the error message.
#[no_mangle]
#[allow(clippy::cast_possible_truncation)]
pub unsafe extern fn aml_tensormap(
    keys: aml_labels_t,
    blocks: *mut *mut aml_block_t,
    blocks_count: u64,
) -> *mut aml_tensormap_t {
    let mut result = std::ptr::null_mut();
    let unwind_wrapper = std::panic::AssertUnwindSafe(&mut result);
    let status = catch_unwind(move || {
        let keys = Labels::try_from(&keys)?;

        let blocks_slice = std::slice::from_raw_parts_mut(blocks, blocks_count as usize);
        // check for uniqueness of the pointers: we don't want to move out
        // the same value twice
        if blocks_slice.iter().collect::<BTreeSet<_>>().len() != blocks_slice.len() {
            return Err(Error::InvalidParameter(
                "got the same block more than once when constructing a tensor map".into()
            ));
        }

        let blocks_vec = blocks_slice.iter_mut().map(|ptr| {
            // move out of the blocks pointers
            let block = Box::from_raw(*ptr).block();
            *ptr = std::ptr::null_mut();
            return block;
        }).collect();

        let tensor = TensorMap::new(keys, blocks_vec)?;
        let boxed = Box::new(aml_tensormap_t(tensor));

        // force the closure to capture the full unwind_wrapper, not just
        // unwind_wrapper.0
        let _ = &unwind_wrapper;
        *(unwind_wrapper.0) = Box::into_raw(boxed);
        Ok(())
    });

    if !status.is_success() {
        return std::ptr::null_mut();
    }

    return result;
}


/// Free the memory associated with a `tensor` previously created with
/// `aml_tensormap`.
///
/// If `tensor` is `NULL`, this function does nothing.
///
/// @param tensor pointer to an existing tensor map, or `NULL`
///
/// @returns The status code of this operation. If the status is not
///          `AML_SUCCESS`, you can use `aml_last_error()` to get the full
///          error message.
#[no_mangle]
pub unsafe extern fn aml_tensormap_free(
    tensor: *mut aml_tensormap_t,
) -> aml_status_t {
    catch_unwind(|| {
        if !tensor.is_null() {
            std::mem::drop(Box::from_raw(tensor));
        }

        Ok(())
    })
}


/// Get the keys for the given `tensor` map. After a successful call to this
/// function, `keys.values` contains a pointer to memory inside the
/// `tensor` which is invalidated when the tensor map is freed with
/// `aml_tensormap_free` or the set of keys is modified by calling one
/// of the `aml_tensormap_keys_to_XXX` function.

/// @param tensor pointer to an existing tensor map
/// @param keys pointer to be filled with the keys of the tensor map
///
/// @returns The status code of this operation. If the status is not
///          `AML_SUCCESS`, you can use `aml_last_error()` to get the full
///          error message.
#[no_mangle]
pub unsafe extern fn aml_tensormap_keys(
    tensor: *const aml_tensormap_t,
    keys: *mut aml_labels_t,
) -> aml_status_t {
    catch_unwind(|| {
        check_pointers!(tensor, keys);

        *keys = (*tensor).keys().try_into()?;
        Ok(())
    })
}


/// Get a pointer to the `index`-th block in this tensor map.
///
/// The block memory is still managed by the tensor map, this block should not
/// be freed. The block is invalidated when the tensor map is freed with
/// `aml_tensormap_free` or the set of keys is modified by calling one
/// of the `aml_tensormap_keys_to_XXX` function.
///
/// @param tensor pointer to an existing tensor map
/// @param block pointer to be filled with a block
/// @param index index of the block to get
///
/// @returns The status code of this operation. If the status is not
///          `AML_SUCCESS`, you can use `aml_last_error()` to get the full
///          error message.
#[no_mangle]
#[allow(clippy::cast_possible_truncation)]
pub unsafe extern fn aml_tensormap_block_by_id(
    tensor: *const aml_tensormap_t,
    block: *mut *const aml_block_t,
    index: u64,
) -> aml_status_t {
    catch_unwind(|| {
        check_pointers!(tensor, block);

        (*block) = (&(*tensor).blocks()[index as usize] as *const TensorBlock).cast();

        Ok(())
    })
}


/// Get a pointer to the `block` in this `tensor` corresponding to the given
/// `selection`. The `selection` should have the same names/variables as the
/// keys for this tensor map, and only one entry, describing the
/// requested block.
///
/// The block memory is still managed by the tensor map, this block should not
/// be freed. The block is invalidated when the tensor map is freed with
/// `aml_tensormap_free` or the set of keys is modified by calling one
/// of the `aml_tensormap_keys_to_XXX` function.
///
/// @param tensor pointer to an existing tensor map
/// @param block pointer to be filled with a block
/// @param selection labels with a single entry describing which block is requested
///
/// @returns The status code of this operation. If the status is not
///          `AML_SUCCESS`, you can use `aml_last_error()` to get the full
///          error message.
#[no_mangle]
pub unsafe extern fn aml_tensormap_block_selection(
    tensor: *const aml_tensormap_t,
    block: *mut *const aml_block_t,
    selection: aml_labels_t,
) -> aml_status_t {
    catch_unwind(|| {
        check_pointers!(tensor, block);

        let selection = Labels::try_from(&selection)?;
        let rust_block = (*tensor).block(&selection)?;
        (*block) = (rust_block as *const TensorBlock).cast();

        Ok(())
    })
}


/// Move the given `variables` from the keys to the property labels of the
/// blocks.
///
/// Blocks containing the same values in the keys for the `variables` will
/// be merged together. The resulting merged blocks will have `variables` as
/// the first property variables, followed by the current properties. The
/// new sample labels will contains all of the merged blocks sample labels,
/// re-ordered to keep them lexicographically sorted.
///
/// `variables` must be an array of `variables_count` NULL-terminated strings,
/// encoded as UTF-8.
///
/// @param tensor pointer to an existing tensor map
/// @param variables names of the key variables to move to the properties
/// @param variables_count number of entries in the `variables` array
///
/// @returns The status code of this operation. If the status is not
///          `AML_SUCCESS`, you can use `aml_last_error()` to get the full
///          error message.
#[no_mangle]
#[allow(clippy::cast_possible_truncation)]
pub unsafe extern fn aml_tensormap_keys_to_properties(
    tensor: *mut aml_tensormap_t,
    variables: *const *const c_char,
    variables_count: u64,
) -> aml_status_t {
    catch_unwind(|| {
        check_pointers!(tensor, variables);

        let mut rust_variables = Vec::new();
        for &variable in std::slice::from_raw_parts(variables, variables_count as usize) {
            check_pointers!(variable);
            let variable = CStr::from_ptr(variable).to_str().expect("invalid utf8");
            rust_variables.push(variable);
        }

        (*tensor).keys_to_properties(&rust_variables)?;

        Ok(())
    })
}


/// Move the given variables from the component labels to the property labels
/// for each block in this tensor map.
///
/// `variables` must be an array of `variables_count` NULL-terminated strings,
/// encoded as UTF-8.
///
/// @param tensor pointer to an existing tensor map
/// @param variables names of the key variables to move to the properties
/// @param variables_count number of entries in the `variables` array
///
/// @returns The status code of this operation. If the status is not
///          `AML_SUCCESS`, you can use `aml_last_error()` to get the full
///          error message.
#[no_mangle]
#[allow(clippy::cast_possible_truncation)]
pub unsafe extern fn aml_tensormap_components_to_properties(
    tensor: *mut aml_tensormap_t,
    variables: *const *const c_char,
    variables_count: u64,
) -> aml_status_t {
    catch_unwind(|| {
        check_pointers!(tensor, variables);

        let mut rust_variables = Vec::new();
        for &variable in std::slice::from_raw_parts(variables, variables_count as usize) {
            check_pointers!(variable);
            let variable = CStr::from_ptr(variable).to_str().expect("invalid utf8");
            rust_variables.push(variable);
        }

        (*tensor).components_to_properties(&rust_variables)?;

        Ok(())
    })
}

/// Move the given `variables` from the keys to the sample labels of the
/// blocks.
///
/// Blocks containing the same values in the keys for the `variables` will
/// be merged together. The resulting merged blocks will have `variables` as
/// the last sample variables, preceded by the current samples.
///
/// This function is only implemented if all merged block have the same
/// property labels.
///
/// `variables` must be an array of `variables_count` NULL-terminated strings,
/// encoded as UTF-8.
///
/// @param tensor pointer to an existing tensor map
/// @param variables names of the key variables to move to the samples
/// @param variables_count number of entries in the `variables` array
///
/// @returns The status code of this operation. If the status is not
///          `AML_SUCCESS`, you can use `aml_last_error()` to get the full
///          error message.
#[no_mangle]
#[allow(clippy::cast_possible_truncation)]
pub unsafe extern fn aml_tensormap_keys_to_samples(
    tensor: *mut aml_tensormap_t,
    variables: *const *const c_char,
    variables_count: u64,
) -> aml_status_t {
    catch_unwind(|| {
        check_pointers!(tensor, variables);

        let mut rust_variables = Vec::new();
        for &variable in std::slice::from_raw_parts(variables, variables_count as usize) {
            check_pointers!(variable);
            let variable = CStr::from_ptr(variable).to_str().expect("invalid utf8");
            rust_variables.push(variable);
        }

        (*tensor).keys_to_samples(&rust_variables)?;

        Ok(())
    })
}