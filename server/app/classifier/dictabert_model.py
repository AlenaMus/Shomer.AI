"""DictaBERT custom model classes — server-importable copy.

These two classes are a minimal extraction of the training script's model
definition (``training/train_dictabert.py``).  The training script imports
``datasets``, ``sklearn``, and other training-only packages at module level,
making it unimportable in the server venv.  This file contains only what the
server needs:

- ``DictaBertMlpConfig`` — the HuggingFace config sub-class with the MLP head
  dimensions baked in.
- ``DictaBertWithMlpHead`` — the BERT backbone + 2-layer MLP classification head.

Architecture (locked — docs/concepts/dictabert_classifier_architecture.md §5):
  pooled_output (768)
    -> Dropout(0.1)
    -> Linear(768, 256)
    -> GELU
    -> Dropout(0.1)
    -> Linear(256, num_labels)
    -> logits

**Keep this file in sync with ``training/train_dictabert.py``.** If the training
script's model architecture changes (new head dimensions, different pooling),
update both files together.  The model_type (``"dictabert_mlp"``) must also stay
in sync so ``from_pretrained`` picks the right config class.

No training-stack deps (``datasets``, ``sklearn``, ``numpy``) are imported here.
Only ``torch`` + ``transformers`` which are available in the server venv.
"""

from __future__ import annotations

import torch.nn as nn
import torch.nn.functional as F
from transformers import BertConfig, BertModel, BertPreTrainedModel
from transformers.modeling_outputs import SequenceClassifierOutput


class DictaBertMlpConfig(BertConfig):
    """BertConfig extended with MLP head dimensions.

    Mirrors the definition in ``training/train_dictabert.py`` exactly.
    The ``model_type`` must match what was used during training so that
    ``AutoConfig.from_pretrained`` resolves to this class.
    """

    model_type = "dictabert_mlp"

    def __init__(
        self,
        classifier_hidden_dim: int = 256,
        classifier_dropout: float = 0.1,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.classifier_hidden_dim = classifier_hidden_dim
        self.classifier_dropout = classifier_dropout


class DictaBertWithMlpHead(BertPreTrainedModel):
    """DictaBERT backbone + 2-layer MLP classification head.

    Architecture per docs/concepts/dictabert_classifier_architecture.md §5:
      pooled_output (768)
        -> Dropout(0.1)
        -> Linear(768, 256)
        -> GELU
        -> Dropout(0.1)
        -> Linear(256, num_labels)
        -> logits

    Mirrors the definition in ``training/train_dictabert.py`` exactly — the same
    attribute names (``bert``, ``pre_dropout``, ``fc1``, ``act``, ``mid_dropout``,
    ``fc2``) so the saved ``model.safetensors`` keys map without renaming.
    """

    config_class = DictaBertMlpConfig

    def __init__(self, config: DictaBertMlpConfig) -> None:
        super().__init__(config)
        self.num_labels = config.num_labels

        self.bert = BertModel(config)

        hidden_dim = getattr(config, "classifier_hidden_dim", 256)
        drop_p = getattr(config, "classifier_dropout", 0.1)

        self.pre_dropout = nn.Dropout(drop_p)
        self.fc1 = nn.Linear(config.hidden_size, hidden_dim)
        self.act = nn.GELU()
        self.mid_dropout = nn.Dropout(drop_p)
        self.fc2 = nn.Linear(hidden_dim, config.num_labels)

        self.post_init()

    def forward(
        self,
        input_ids=None,
        attention_mask=None,
        token_type_ids=None,
        position_ids=None,
        head_mask=None,
        inputs_embeds=None,
        labels=None,
        output_attentions=None,
        output_hidden_states=None,
        return_dict=None,
    ) -> SequenceClassifierOutput:
        return_dict = return_dict if return_dict is not None else self.config.use_return_dict

        outputs = self.bert(
            input_ids=input_ids,
            attention_mask=attention_mask,
            token_type_ids=token_type_ids,
            position_ids=position_ids,
            head_mask=head_mask,
            inputs_embeds=inputs_embeds,
            output_attentions=output_attentions,
            output_hidden_states=output_hidden_states,
            return_dict=return_dict,
        )

        # pooled_output is [CLS] after Linear(768->768) + tanh (BERT pooler).
        pooled_output = outputs[1]  # shape (B, 768)

        # MLP head (same attribute names as training script — safetensors keys match).
        x = self.pre_dropout(pooled_output)
        x = self.fc1(x)
        x = self.act(x)
        x = self.mid_dropout(x)
        logits = self.fc2(x)  # shape (B, num_labels)

        loss = None
        if labels is not None:
            loss = F.cross_entropy(logits, labels)

        return SequenceClassifierOutput(
            loss=loss,
            logits=logits,
            hidden_states=outputs.hidden_states if output_hidden_states else None,
            attentions=outputs.attentions if output_attentions else None,
        )
