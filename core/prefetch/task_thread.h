// Copyright (c) EfficientMoE.
// SPDX-License-Identifier: Apache-2.0

// EfficientMoE Team

#pragma once

#include <atomic>

#include "model/model_topology.h"

typedef std::vector<std::pair<NodePtr, torch::Device>> NodeMoveVec;

void SetThreadScheduling(std::thread& th, int policy, int priority);
void SetThreadAffinity(std::thread& th, int cpu_id);
void SetThreadAffinity(std::thread& th);
void SetThreadAffinity(pid_t tid);

static std::atomic_uint64_t kCPUCounter{0};
extern std::atomic_uint32_t kGPUCounter;
