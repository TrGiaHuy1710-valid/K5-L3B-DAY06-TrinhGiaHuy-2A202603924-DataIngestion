"""Minimal XLM-RoBERTa encoder (the architecture of multilingual-e5) on plain PyTorch.

Why this exists: the `robot` env has torch 2.5.1, but the installed `transformers` (5.x) refuses
to load any PyTorch model below torch 2.6. Rather than modifying the env, this file runs the
model with only `torch`, `safetensors` and `tokenizers`. It is inference-only (no dropout,
no pooler head) and its output is checked against the reference implementation:
`python -m src.embeddings --selftest` compares with vectors produced by transformers.

Weights/tokenizer come from a local folder (e.g. models/multilingual-e5-base) with
config.json, model.safetensors and tokenizer.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import torch
import torch.nn.functional as F
from safetensors.torch import load_file
from tokenizers import Tokenizer


class _Layer(torch.nn.Module):
    def __init__(self, h: int, inter: int, heads: int, eps: float) -> None:
        super().__init__()
        self.heads = heads
        self.q, self.k, self.v = (torch.nn.Linear(h, h) for _ in range(3))
        self.attn_out = torch.nn.Linear(h, h)
        self.attn_ln = torch.nn.LayerNorm(h, eps=eps)
        self.inter = torch.nn.Linear(h, inter)
        self.out = torch.nn.Linear(inter, h)
        self.out_ln = torch.nn.LayerNorm(h, eps=eps)

    def forward(self, x: torch.Tensor, pad_mask: torch.Tensor) -> torch.Tensor:
        b, n, h = x.shape
        split = lambda t: t.view(b, n, self.heads, h // self.heads).transpose(1, 2)  # noqa: E731
        ctx = F.scaled_dot_product_attention(split(self.q(x)), split(self.k(x)), split(self.v(x)),
                                             attn_mask=pad_mask)  # bool, True = attend
        x = self.attn_ln(x + self.attn_out(ctx.transpose(1, 2).reshape(b, n, h)))
        return self.out_ln(x + self.out(F.gelu(self.inter(x))))


class XLMRobertaEncoder(torch.nn.Module):
    def __init__(self, folder: str | Path, device: str = "cpu") -> None:
        super().__init__()
        folder = Path(folder)
        cfg = json.loads((folder / "config.json").read_text(encoding="utf-8"))
        if cfg.get("model_type") != "xlm-roberta" or cfg.get("position_embedding_type") != "absolute":
            raise ValueError(f"{folder} is not an absolute-position XLM-RoBERTa model")
        h, eps = cfg["hidden_size"], cfg["layer_norm_eps"]
        self.pad_id, self.hidden_size = cfg["pad_token_id"], h
        self.max_positions = cfg["max_position_embeddings"] - self.pad_id - 1  # 512 usable tokens
        self.word = torch.nn.Embedding(cfg["vocab_size"], h)
        self.pos = torch.nn.Embedding(cfg["max_position_embeddings"], h)
        self.tok_type = torch.nn.Embedding(cfg["type_vocab_size"], h)
        self.emb_ln = torch.nn.LayerNorm(h, eps=eps)
        self.layers = torch.nn.ModuleList(
            _Layer(h, cfg["intermediate_size"], cfg["num_attention_heads"], eps)
            for _ in range(cfg["num_hidden_layers"])
        )
        self._load(load_file(folder / "model.safetensors"))
        self.to(device).eval()
        self.device = device
        self.tokenizer = Tokenizer.from_file(str(folder / "tokenizer.json"))

    def _load(self, w: dict[str, torch.Tensor]) -> None:
        w = {k.removeprefix("roberta."): v for k, v in w.items()}
        mapping = {
            "embeddings.word_embeddings.weight": self.word.weight,
            "embeddings.position_embeddings.weight": self.pos.weight,
            "embeddings.token_type_embeddings.weight": self.tok_type.weight,
            "embeddings.LayerNorm.weight": self.emb_ln.weight, "embeddings.LayerNorm.bias": self.emb_ln.bias,
        }
        for i, layer in enumerate(self.layers):
            p = f"encoder.layer.{i}."
            for name, mod in [("attention.self.query", layer.q), ("attention.self.key", layer.k),
                              ("attention.self.value", layer.v), ("attention.output.dense", layer.attn_out),
                              ("attention.output.LayerNorm", layer.attn_ln), ("intermediate.dense", layer.inter),
                              ("output.dense", layer.out), ("output.LayerNorm", layer.out_ln)]:
                mapping[p + name + ".weight"], mapping[p + name + ".bias"] = mod.weight, mod.bias
        missing = [k for k in mapping if k not in w]
        if missing:
            raise KeyError(f"weights missing in checkpoint: {missing[:3]}...")
        with torch.no_grad():
            for k, param in mapping.items():
                param.copy_(w[k])

    def tokenize(self, texts: list[str], max_length: int = 512) -> tuple[list[list[int]], list[int]]:
        """Return (ids truncated to max_length incl. <s></s>, full lengths before truncation)."""
        encs = self.tokenizer.encode_batch(texts)  # post-processor adds <s> ... </s>
        full = [len(e.ids) for e in encs]
        ids = [e.ids if len(e.ids) <= max_length else e.ids[: max_length - 1] + [e.ids[-1]] for e in encs]
        return ids, full

    @torch.no_grad()
    def forward(self, ids: list[list[int]]) -> torch.Tensor:
        """Last hidden state [B, L, H] and attention mask for a list of token-id lists."""
        n = max(len(x) for x in ids)
        t = torch.tensor([x + [self.pad_id] * (n - len(x)) for x in ids], device=self.device)
        mask = t != self.pad_id
        pos = torch.cumsum(mask, dim=1) * mask + self.pad_id  # RoBERTa position ids
        x = self.emb_ln(self.word(t) + self.pos(pos) + self.tok_type(torch.zeros_like(t)))
        attn = mask[:, None, None, :]  # [B,1,1,L]
        for layer in self.layers:
            x = layer(x, attn)
        self.last_mask = mask
        return x
