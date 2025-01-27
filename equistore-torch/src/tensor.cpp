#include <equistore.hpp>

#include "equistore/torch/tensor.hpp"
#include "equistore/torch/array.hpp"
#include "equistore/torch/block.hpp"

using namespace equistore_torch;

TensorMapHolder::TensorMapHolder(equistore::TensorMap tensor): tensor_(std::move(tensor)) {}

static equistore::TensorBlock block_from_torch(const TorchTensorBlock& block) {
    auto components = std::vector<equistore::Labels>();
    for (const auto& component: block->components()) {
        components.push_back(component->as_equistore());
    }

    // use copy constructors of everything here, incrementing reference count
    // of the data and metadata
    auto result = equistore::TensorBlock(
        std::make_unique<TorchDataArray>(block->values()),
        block->samples()->as_equistore(),
        components,
        block->properties()->as_equistore()
    );

    for (const auto& parameter: block->gradients_list()) {
        auto gradient = block_from_torch(block->gradient(parameter));
        result.add_gradient(parameter, std::move(gradient));
    }

    return result;
}

static std::vector<equistore::TensorBlock> blocks_from_torch(const std::vector<TorchTensorBlock>& blocks) {
    auto results = std::vector<equistore::TensorBlock>();
    for (const auto& block: blocks) {
        results.emplace_back(block_from_torch(block));
    }
    return results;
}


TensorMapHolder::TensorMapHolder(TorchLabels keys, const std::vector<TorchTensorBlock>& blocks):
    tensor_(keys->as_equistore(), blocks_from_torch(std::move(blocks)))
{}

TorchTensorMap TensorMapHolder::copy() const {
    return torch::make_intrusive<TensorMapHolder>(this->tensor_.clone());
}

TorchLabels TensorMapHolder::keys() const {
    return torch::make_intrusive<LabelsHolder>(this->tensor_.keys());
}

std::vector<int64_t> TensorMapHolder::blocks_matching(const TorchLabels& selection) const {
    auto results = tensor_.blocks_matching(selection->as_equistore());

    auto results_int64 = std::vector<int64_t>();
    results_int64.reserve(results.size());
    for (auto matching: results) {
        results_int64.push_back(static_cast<int64_t>(matching));
    }

    return results_int64;
}

TorchTensorBlock TensorMapHolder::block_by_id(int64_t index) {
    if (index >= this->keys()->count()) {
        // this needs to be an IndexError to enable iteration over a TensorMap
        C10_THROW_ERROR(IndexError,
            "block index out of bounds: we have " + std::to_string(this->keys()->count())
            + " blocks but the index is " + std::to_string(index)
        );
    }
    return torch::make_intrusive<TensorBlockHolder>(tensor_.block_by_id(index));
}


TorchTensorBlock TensorMapHolder::block(const std::map<std::string, int32_t>& selection_dict) {
    auto names = std::vector<std::string>();
    auto values = std::vector<int32_t>();
    for (const auto& it: selection_dict) {
        names.push_back(it.first);
        values.push_back(static_cast<int32_t>(it.second));
    }

    auto selection = equistore::Labels(names, values.data(), 1);
    return this->block(torch::make_intrusive<LabelsHolder>(std::move(selection)));
}

TorchTensorBlock TensorMapHolder::block(TorchLabels selection) {
    if (selection->count() != 1) {
        C10_THROW_ERROR(ValueError,
            "block selection must contain exactly one entry, got " + std::to_string(selection->count())
        );
    }

    return this->block(torch::make_intrusive<LabelsEntryHolder>(selection, 0));
}

TorchTensorBlock TensorMapHolder::block(TorchLabelsEntry torch_selection) {
    auto cpu_values = torch_selection->values().to(torch::kCPU);
    auto selection = equistore::Labels(
        torch_selection->names(), cpu_values.data_ptr<int32_t>(), 1
    );

    auto matching = tensor_.blocks_matching(selection);
    if (matching.size() == 0) {
        C10_THROW_ERROR(ValueError,
            "could not find blocks matching the selection " + torch_selection->print()
        );
    } else if (matching.size() != 1) {
        C10_THROW_ERROR(ValueError,
            "got more than one matching block for " + torch_selection->print() +
            ", use the `blocks` function to select more than one block"
        );
    }

    return this->block_by_id(matching[0]);
}

TorchTensorBlock TensorMapHolder::block_torch(torch::IValue index) {
    if (index.isInt()) {
        return this->block_by_id(index.toInt());
    } else if (index.isGenericDict()) {
        auto selection = std::map<std::string, int32_t>();
        for (const auto& it: index.toGenericDict()) {
            const auto& key = it.key();
            const auto& value = it.value();
            if (it.key().isString() && value.isInt()) {
                selection.emplace(key.toString()->string(), static_cast<int32_t>(value.toInt()));
            } else {
                C10_THROW_ERROR(ValueError,
                    "expected argument to be Dict[str, int], got Dict["
                    + key.type()->str() + ", " + value.type()->str() + "]"
                );
            }
        }
        return this->block(selection);
    } else if (index.isCustomClass()) {
        torch::optional<TorchLabels> labels = torch::nullopt;
        torch::optional<TorchLabelsEntry> entry = torch::nullopt;
        try {
            labels = index.toCustomClass<LabelsHolder>();
        } catch (const c10::Error&) {
            try {
                entry = index.toCustomClass<LabelsEntryHolder>();
            } catch (const c10::Error&) {
                C10_THROW_ERROR(TypeError,
                    "expected argument to be Labels or LabelsEntry, got"
                    + index.type()->str()
                );
            }
        }

        if (labels.has_value()) {
            return this->block(labels.value());
        } else if (entry.has_value()) {
            return this->block(entry.value());
        } else {
            // this should never be reached, the code above should throw a
            // TypeError before
            throw std::runtime_error("internal error: not a labels nor a labels entry");
        }
    } else {
        C10_THROW_ERROR(ValueError,
            "expected argument to be int, Dict[str, int], Labels, or LabelsEntry, got "
            + index.type()->str()
        );
    }
}


std::vector<TorchTensorBlock> TensorMapHolder::blocks_by_id(const std::vector<int64_t>& indices) {
    auto result = std::vector<TorchTensorBlock>();
    for (auto i: indices) {
        result.push_back(this->block_by_id(i));
    }
    return result;
}

std::vector<TorchTensorBlock> TensorMapHolder::blocks() {
    auto result = std::vector<TorchTensorBlock>();
    for (size_t i=0; i<tensor_.keys().count(); i++) {
        result.push_back(this->block_by_id(i));
    }
    return result;
}


std::vector<TorchTensorBlock> TensorMapHolder::blocks(const std::map<std::string, int32_t>& selection_dict) {
    auto names = std::vector<std::string>();
    auto values = std::vector<int32_t>();
    for (const auto& it: selection_dict) {
        names.push_back(it.first);
        values.push_back(static_cast<int32_t>(it.second));
    }

    auto selection = equistore::Labels(names, values.data(), 1);
    return this->blocks(torch::make_intrusive<LabelsHolder>(std::move(selection)));
}


std::vector<TorchTensorBlock> TensorMapHolder::blocks(TorchLabels selection) {
    if (selection->count() != 1) {
        C10_THROW_ERROR(ValueError,
            "block selection must contain exactly one entry, got " + std::to_string(selection->count())
        );
    }

    return this->blocks(torch::make_intrusive<LabelsEntryHolder>(selection, 0));
}


std::vector<TorchTensorBlock> TensorMapHolder::blocks(TorchLabelsEntry torch_selection) {
    auto cpu_values = torch_selection->values().to(torch::kCPU);
    auto selection = equistore::Labels(
        torch_selection->names(), cpu_values.data_ptr<int32_t>(), 1
    );

    auto matching = std::vector<int64_t>();
    for (auto m: tensor_.blocks_matching(selection)) {
        matching.push_back(static_cast<int64_t>(m));
    }

    return this->blocks_by_id(matching);
}


std::vector<TorchTensorBlock> TensorMapHolder::blocks_torch(torch::IValue index) {
    if (index.isNone()) {
        return this->blocks();
    } else if (index.isInt()) {
        return {this->block_by_id(index.toInt())};
    } else if (index.isIntList()) {
        return this->blocks_by_id(index.toIntVector());
    } else if (index.isGenericDict()) {
        auto selection = std::map<std::string, int32_t>();
        for (const auto& it: index.toGenericDict()) {
            const auto& key = it.key();
            const auto& value = it.value();
            if (it.key().isString() && value.isInt()) {
                selection.emplace(key.toString()->string(), static_cast<int32_t>(value.toInt()));
            } else {
                C10_THROW_ERROR(ValueError,
                    "expected argument to be Dict[str, int], got Dict["
                    + key.type()->str() + ", " + value.type()->str() + "]"
                );
            }
        }
        return this->blocks(selection);
    } else if (index.isCustomClass()) {
        torch::optional<TorchLabels> labels = torch::nullopt;
        torch::optional<TorchLabelsEntry> entry = torch::nullopt;
        try {
            labels = index.toCustomClass<LabelsHolder>();
        } catch (const c10::Error&) {
            try {
                entry = index.toCustomClass<LabelsEntryHolder>();
            } catch (const c10::Error&) {
                C10_THROW_ERROR(TypeError,
                    "expected argument to be Labels or LabelsEntry, got"
                    + index.type()->str()
                );
            }
        }

        if (labels.has_value()) {
            return this->blocks(labels.value());
        } else if (entry.has_value()) {
            return this->blocks(entry.value());
        } else {
            // this should never be reached, the code above should throw a
            // TypeError before
            throw std::runtime_error("internal error: not a labels nor a labels entry");
        }
    } else {
        C10_THROW_ERROR(ValueError,
            "expected argument to be None, int, List[int], Dict[str, int], Labels, or LabelsEntry, got "
            + index.type()->str()
        );
    }
}


/// Transform a torch::IValue containing either a single string, a list of
/// strings or a tuple of strings to something C++ can use
///
/// The `context` is used for the error message in case the torch::IValue is
/// none of the above.
static std::vector<std::string> extract_list_str(const torch::IValue& keys_to_move, std::string context) {
    if (keys_to_move.isString()) {
        return {keys_to_move.toString()->string()};
    } else if (keys_to_move.isList()) {
        auto results = std::vector<std::string>();
        for (const auto& element: keys_to_move.toListRef()) {
            if (element.isString()) {
                results.push_back(element.toString()->string());
            } else {
                C10_THROW_ERROR(TypeError, context + " must be a list of `str`");
            }
        }
        return results;
    } else if (keys_to_move.isTuple()) {
        auto results = std::vector<std::string>();
        for (const auto& element: keys_to_move.toTupleRef().elements()) {
            if (element.isString()) {
                results.push_back(element.toString()->string());
            } else {
                C10_THROW_ERROR(TypeError, context + " must be a tuple of `str`");
            }
        }
        return results;
    } else {
        throw std::runtime_error(
            "internal error: called extract_list_str, but IValue is not a list of str"
        );
    }
}

TorchTensorMap TensorMapHolder::keys_to_properties(torch::IValue keys_to_move, bool sort_samples) const {
    if (keys_to_move.isString() || keys_to_move.isList() || keys_to_move.isTuple()) {
        auto selection = extract_list_str(keys_to_move, "TensorMap::keys_to_properties first argument");
        auto tensor = tensor_.keys_to_properties(selection, sort_samples);
        return torch::make_intrusive<TensorMapHolder>(std::move(tensor));
    } else if (keys_to_move.isCustomClass()) {
        auto selection = keys_to_move.toCustomClass<LabelsHolder>();
        auto tensor = tensor_.keys_to_properties(selection->as_equistore(), sort_samples);
        return torch::make_intrusive<TensorMapHolder>(std::move(tensor));
    } else {
        C10_THROW_ERROR(TypeError,
            "TensorMap::keys_to_properties first argument must be a `str`, list of `str` or `Labels`"
        );
    }
}

TorchTensorMap TensorMapHolder::keys_to_samples(torch::IValue keys_to_move, bool sort_samples) const {
    if (keys_to_move.isString() || keys_to_move.isList() || keys_to_move.isTuple()) {
        auto selection = extract_list_str(keys_to_move, "TensorMap::keys_to_samples first argument");
        auto tensor = tensor_.keys_to_samples(selection, sort_samples);
        return torch::make_intrusive<TensorMapHolder>(std::move(tensor));
    } else if (keys_to_move.isCustomClass()) {
        auto selection = keys_to_move.toCustomClass<LabelsHolder>();
        auto tensor = tensor_.keys_to_samples(selection->as_equistore(), sort_samples);
        return torch::make_intrusive<TensorMapHolder>(std::move(tensor));
    } else {
        C10_THROW_ERROR(TypeError,
            "TensorMap::keys_to_samples first argument must be a `str`, list of `str` or `Labels`"
        );
    }
}

TorchTensorMap TensorMapHolder::components_to_properties(torch::IValue dimensions) const {
    auto selection = extract_list_str(dimensions, "TensorMap::components_to_properties argument");
    auto tensor = this->tensor_.components_to_properties(selection);
    return torch::make_intrusive<TensorMapHolder>(std::move(tensor));
}

static std::vector<std::string> labels_names(const equistore::TensorBlock& block, size_t dimension) {
    auto result = std::vector<std::string>();

    auto labels = block.labels(dimension);
    for (const auto& name: labels.names()) {
        result.push_back(std::string(name));
    }

    return result;
}

std::vector<std::string> TensorMapHolder::sample_names() {
    if (tensor_.keys().count() == 0) {
        return {};
    }

    return labels_names(this->block_by_id(0)->as_equistore(), 0);
}

std::vector<std::vector<std::string>> TensorMapHolder::components_names() {
    auto result = std::vector<std::vector<std::string>>();

    if (tensor_.keys().count() != 0) {
        auto block = this->block_by_id(0);
        auto n_dimensions = block->values().sizes().size();

        for (size_t dimension=1; dimension<n_dimensions-1; dimension++) {
            result.push_back(labels_names(block->as_equistore(), dimension));
        }
    }

    return result;
}

std::vector<std::string> TensorMapHolder::property_names() {
    if (tensor_.keys().count() == 0) {
        return {};
    }

    auto block = this->block_by_id(0);
    auto n_dimensions = block->values().sizes().size();

    return labels_names(block->as_equistore(), n_dimensions - 1);
}

std::vector<std::tuple<TorchLabelsEntry, TorchTensorBlock>> TensorMapHolder::items() {
    auto result = std::vector<std::tuple<TorchLabelsEntry, TorchTensorBlock>>();

    auto keys = this->keys();
    for (size_t i = 0; i<keys->count(); i++) {
        result.push_back({
            torch::make_intrusive<LabelsEntryHolder>(keys, i),
            this->block_by_id(i)
        });
    }
    return result;
}


std::string TensorMapHolder::print(int64_t max_keys) const {
    std::ostringstream output;
    auto keys = this->keys();
    output << "TensorMap with " << keys->count() << " blocks\n";
    output << "keys:" << keys->print(max_keys, 5);
    return output.str();
}
