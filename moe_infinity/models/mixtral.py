# Copyright (c) EfficientMoE.
# SPDX-License-Identifier: Apache-2.0

# EfficientMoE Team

from typing import Dict

import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers.models.mixtral.modeling_mixtral import (
    MixtralBlockSparseTop2MLP,
)

from moe_infinity.utils import ArcherConfig
'''
config for mixtral
{
  "architectures": [
    "MixtralForCausalLM"
  ],
  "attention_dropout": 0.0,
  "bos_token_id": 1,
  "eos_token_id": 2,
  "hidden_act": "silu",
  "hidden_size": 4096,
  "initializer_range": 0.02,
  "intermediate_size": 14336,
  "max_position_embeddings": 32768,
  "model_type": "mixtral",
  "num_attention_heads": 32,
  "num_experts_per_tok": 2,
  "num_hidden_layers": 32,
  "num_key_value_heads": 8,
  "num_local_experts": 8,
  "output_router_logits": false,
  "rms_norm_eps": 1e-05,
  "rope_theta": 1000000.0,
  "router_aux_loss_coef": 0.02,
  "sliding_window": 4096,
  "tie_word_embeddings": false,
  "torch_dtype": "bfloat16",
  "transformers_version": "4.36.0.dev0",
  "use_cache": true,
  "vocab_size": 32000
}
'''


class SyncMixtralSparseMoeBlock(nn.Module):
    archer_config: ArcherConfig = None
    layer_id: int = None

    def __init__(self, config):
        super().__init__()
        self.hidden_dim = config.hidden_size
        self.ffn_dim = config.intermediate_size
        self.num_experts = config.num_local_experts
        self.top_k = config.num_experts_per_tok

        # gating
        self.gate = nn.Linear(self.hidden_dim, self.num_experts, bias=False)

        self.experts = nn.ModuleList(
            [MixtralBlockSparseTop2MLP(config)
             for _ in range(self.num_experts)]
        )

        self.archer_tracer = None
        self.archer_engine = None
        self.expert_tensor_ids: Dict[int, int] = None

    def forward(self, hidden_states: torch.Tensor) -> torch.Tensor:
        """ """
        batch_size, sequence_length, hidden_dim = hidden_states.shape
        num_tokens = batch_size * sequence_length
        hidden_states = hidden_states.view(-1, hidden_dim)
        # router_logits: (batch * sequence_length, n_experts)
        router_logits = self.gate(hidden_states)

        routing_weights = F.softmax(router_logits, dim=1, dtype=torch.float)
        # routing_weights: values ; selected_experts: indices
        # self.top_k is 2 for mixtral
        routing_weights, selected_experts = torch.topk(
            routing_weights, self.top_k, dim=-1
        )
        # normalize routing_weights
        routing_weights /= routing_weights.sum(dim=-1, keepdim=True)
        # we cast back to the input dtype
        routing_weights = routing_weights.to(hidden_states.dtype)

        router_mask = F.one_hot(selected_experts, num_classes=self.num_experts)
        routing_weights_mask = (
            routing_weights[:, :, None] * router_mask
        ).permute(0, 2, 1)
        router_mask = router_mask.permute(0, 2, 1)
        # assume top-2 here
        router_mask = torch.logical_or(
            router_mask[:, :, 0], router_mask[:, :, 1]
        )
        routing_weights_mask = torch.sum(routing_weights_mask, dim=-1)

        # print("selected_experts", selected_experts)
        expert_index = selected_experts.reshape(
            batch_size, sequence_length, self.top_k
        )
        # self.expert_prefetcher.fetch_experts_lock_cache(
        #     self.layer_id, expert_index
        # )
        # for i in range(batch_size):
        #     seq_id = self.seq_id_list[i]
        #     # start_time = time.time()
        #     expert_matrix = self.expert_predictor.predict(
        #         seq_id, expert_index[i], self.layer_id
        #     )
        #     # print("predict", time.time() - start_time)
        #     # start_time = time.time()
        #     self.expert_prefetcher.prefetch_experts(
        #         self.layer_id, expert_matrix
        #     )
        #     # print("prefetch", time.time() - start_time)

        final_hidden_states = torch.zeros(
            (batch_size * sequence_length, hidden_dim),
            dtype=hidden_states.dtype,
            device=hidden_states.device,
        )

        results = self.expert_executor.dispatch_local(
            hidden_states, router_mask, self.layer_id
        )
        for output, _, idx, _ in results:
            token_indices = router_mask[:, idx].bool()
            final_hidden_states[token_indices, :] += (
                output.to(routing_weights_mask.device)
                * routing_weights_mask[token_indices, idx][:, None]
            )

        # for expert_idx in range(self.num_experts):
        #     # expert_layer = self.experts[expert_idx]
        #     token_indices = router_mask[:, expert_idx]
        #     current_state = hidden_states[token_indices, :]

        #     if token_indices.any():
        #         current_hidden_states = (
        #             self.experts[expert_idx](current_state).to(routing_weights_mask.device)
        #             * routing_weights_mask[token_indices, expert_idx][:, None]
        #         )
        #         final_hidden_states[token_indices, :] += current_hidden_states

        final_hidden_states = final_hidden_states.reshape(
            batch_size, sequence_length, hidden_dim
        )
        return final_hidden_states, router_logits
