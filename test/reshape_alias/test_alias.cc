/* SPDX-License-Identifier: Apache-2.0 */
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <memory>
#include <vector>

#include "flatbuffers/flatbuffers.h"
#include "tensorflow/lite/micro/micro_allocator.h"
#include "tensorflow/lite/schema/schema_generated.h"

namespace {
struct TensorSpec {
  int elements = 16;
  tflite::TensorType type = tflite::TensorType_INT8;
  bool variable = false;
  bool constant = false;
};
struct OpSpec {
  bool reshape;
  std::vector<int32_t> inputs;
  int output;
};

std::vector<uint8_t> BuildModel(const std::vector<TensorSpec>& tensor_specs,
                              const std::vector<OpSpec>& ops,
                              const std::vector<int32_t>& graph_outputs,
                              bool offline = false, bool second_graph = false,
                              bool legacy_codes = false) {
  tflite::ModelT model;
  model.version = 3;
  model.buffers.emplace_back(new tflite::BufferT);
  model.buffers.emplace_back(new tflite::BufferT);
  model.buffers[1]->data.assign(64, 0x29);
  for (auto builtin : {tflite::BuiltinOperator_ADD,
                       tflite::BuiltinOperator_RESHAPE}) {
    auto code = std::make_unique<tflite::OperatorCodeT>();
    // 旧格式算子通过兼容字段保存操作类型。
    code->builtin_code = legacy_codes ? tflite::BuiltinOperator_ADD : builtin;
    code->deprecated_builtin_code = static_cast<int8_t>(builtin);
    model.operator_codes.push_back(std::move(code));
  }
  auto graph = std::make_unique<tflite::SubGraphT>();
  for (const auto& spec : tensor_specs) {
    auto tensor = std::make_unique<tflite::TensorT>();
    tensor->shape = {spec.elements};
    tensor->type = spec.type;
    tensor->is_variable = spec.variable;
    tensor->buffer = spec.constant ? 1 : 0;
    graph->tensors.push_back(std::move(tensor));
  }
  graph->inputs = {0};
  graph->outputs = graph_outputs;
  for (const auto& op : ops) {
    auto node = std::make_unique<tflite::OperatorT>();
    node->opcode_index = op.reshape ? 1 : 0;
    node->inputs = op.inputs;
    node->outputs = {op.output};
    graph->operators.push_back(std::move(node));
  }
  model.subgraphs.push_back(std::move(graph));
  if (second_graph) {
    auto unused = std::make_unique<tflite::SubGraphT>();
    auto constant = std::make_unique<tflite::TensorT>();
    constant->shape = {16};
    constant->type = tflite::TensorType_INT8;
    constant->buffer = 1;
    unused->tensors.push_back(std::move(constant));
    model.subgraphs.push_back(std::move(unused));
  }
  if (offline) {
    std::vector<int32_t> offsets(tensor_specs.size() + 3, -1);
    offsets[0] = 1;
    offsets[1] = 0;
    offsets[2] = static_cast<int32_t>(tensor_specs.size());
    auto data = std::make_unique<tflite::BufferT>();
    const auto* first = reinterpret_cast<const uint8_t*>(offsets.data());
    data->data.assign(first, first + offsets.size() * sizeof(int32_t));
    model.buffers.push_back(std::move(data));
    auto metadata = std::make_unique<tflite::MetadataT>();
    metadata->name = "OfflineMemoryAllocation";
    metadata->buffer = 2;
    model.metadata.push_back(std::move(metadata));
  }
  flatbuffers::DefaultAllocator allocator;
  flatbuffers::FlatBufferBuilder builder(1024, &allocator);
  builder.Finish(tflite::Model::Pack(builder, &model));
  return {builder.GetBufferPointer(),
          builder.GetBufferPointer() + builder.GetSize()};
}

struct Allocation {
  alignas(16) uint8_t arena[65536] = {};
  std::vector<uint8_t> bytes;
  tflite::SubgraphAllocations* tensors = nullptr;
  explicit Allocation(std::vector<uint8_t> data, bool linear = false)
      : bytes(std::move(data)) {
    auto* allocator = tflite::MicroAllocator::Create(
        arena, sizeof(arena),
        linear ? tflite::MemoryPlannerType::kLinear
               : tflite::MemoryPlannerType::kGreedy);
    assert(allocator != nullptr);
    const auto* model = tflite::GetModel(bytes.data());
    tensors = allocator->StartModelAllocation(model);
    assert(tensors != nullptr);
    for (unsigned i = 0; i < model->subgraphs()->Get(0)->operators()->size(); ++i)
      assert(allocator->FinishPrepareNodeAllocations(i) == kTfLiteOk);
    tflite::ScratchBufferHandle* scratch = nullptr;
    assert(allocator->FinishModelAllocation(model, tensors, &scratch) == kTfLiteOk);
  }
  int8_t* data(int tensor) { return tensors[0].tensors[tensor].data.int8; }
};

void CheckLifetimeAndValues(bool linear = false, bool offline = false,
                            bool second_graph = false, bool legacy_codes = false) {
  std::vector<TensorSpec> specs(5);
  std::vector<OpSpec> ops = {{false, {0}, 1}, {true, {1}, 2},
                             {false, {0}, 3}, {false, {2, 3}, 4}};
  Allocation a(BuildModel(specs, ops, {4}, offline, second_graph, legacy_codes), linear);
  assert((a.data(1) == a.data(2)) == !(linear || offline || second_graph));
  assert(a.data(2) != a.data(3));
  assert(a.data(2) != a.data(4));
  for (int iteration = 0; iteration < 7; ++iteration) {
    for (int i = 0; i < 16; ++i) a.data(0)[i] = i - 15 + iteration;
    for (int i = 0; i < 16; ++i) a.data(1)[i] = a.data(0)[i] + 1;
    if (a.data(1) != a.data(2)) std::memcpy(a.data(2), a.data(1), 16);
    for (int i = 0; i < 16; ++i) a.data(3)[i] = a.data(0)[i] + 7;
    for (int i = 0; i < 16; ++i) a.data(4)[i] = a.data(2)[i] + a.data(3)[i];
    for (int i = 0; i < 16; ++i)
      assert(a.data(4)[i] == 2 * (i - 15 + iteration) + 8);
  }
}

void CheckChainAndBranch() {
  std::vector<TensorSpec> specs(7);
  std::vector<OpSpec> ops = {{false, {0}, 5}, {true, {5}, 1},
                            {true, {1}, 2}, {false, {0}, 3},
                            {false, {5, 3}, 4}, {false, {2, 4}, 6}};
  Allocation a(BuildModel(specs, ops, {1, 6}));
  assert(a.data(5) == a.data(1) && a.data(1) == a.data(2));
  assert(a.data(5) != a.data(3) && a.data(5) != a.data(4));
  assert(a.data(5) != a.data(6));
  for (int i = 0; i < 16; ++i) a.data(0)[i] = i - 8;
  for (int i = 0; i < 16; ++i) a.data(5)[i] = a.data(0)[i] + 1;
  for (int i = 0; i < 16; ++i) a.data(3)[i] = a.data(0)[i] + 2;
  for (int i = 0; i < 16; ++i) a.data(4)[i] = a.data(5)[i] + a.data(3)[i];
  for (int i = 0; i < 16; ++i) a.data(6)[i] = a.data(2)[i] + a.data(4)[i];
  for (int i = 0; i < 16; ++i) {
    assert(a.data(6)[i] == 3 * (i - 8) + 4);
    assert(a.data(1)[i] == i - 7);
  }
}

void CheckExclusions() {
  {
    Allocation a(BuildModel(std::vector<TensorSpec>(2), {{true, {0}, 1}}, {1}));
    assert(a.data(0) != a.data(1));
  }
  for (int kind = 0; kind < 6; ++kind) {
    std::vector<TensorSpec> specs(4);
    std::vector<OpSpec> ops = {{false, {0}, 1}, {true, {1}, 2},
                              {false, {2}, 3}};
    if (kind == 0) specs[1].constant = true;
    if (kind == 1) specs[1].variable = true;
    if (kind == 2) specs[2].elements = 8;
    if (kind == 3) {
      specs[2].elements = 8;
      specs[2].type = tflite::TensorType_INT16;
    }
    if (kind == 4) ops.push_back({false, {0}, 1});
    if (kind == 5) ops.push_back({false, {0}, 2});
    Allocation a(BuildModel(specs, ops, {3}));
    assert(a.data(1) != a.data(2));
  }
}
}  // namespace

int main() {
  CheckLifetimeAndValues();
  CheckLifetimeAndValues(true);
  CheckLifetimeAndValues(false, true);
  CheckLifetimeAndValues(false, false, true);
  CheckLifetimeAndValues(false, false, false, true);
  CheckChainAndBranch();
  CheckExclusions();
  std::cout << "RESHAPE_ALIAS_PASS cases=13 repeated_inferences=35\n";
}
