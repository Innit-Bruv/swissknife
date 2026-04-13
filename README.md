# SwissKnife
**Plug-and-Play Alignment Heads via Tournament Sampling Auditors in Speculative Decoding**

Pragya Lab, BITS Pilani Goa | Course: Information Retrieval | Supervisor: Prof. Amitava Das

---

## What This Is

Standard LLM alignment is checkpoint-bound — safety, helpfulness, and other objectives are baked into model weights at training time. Changing alignment behaviour after deployment requires retraining, which is expensive and slow.

**SwissKnife** externalizes alignment into a swappable decode-time head. Instead of training alignment in, it enforces it during generation using a separately trainable **auditor** model. The auditor is a swappable "blade" — you can hot-swap between different alignment objectives without touching the base model at all.

This repository implements a simplified but complete SwissKnife pipeline based on the paper abstract by Prof. Amitava Das.

---

## How It Works

At every generation step:

1. A small **draft model** (Llama-3.2-1B-Instruct) proposes the top-K candidate token spans
2. An **auditor blade** scores each candidate span according to a chosen alignment objective
3. A **knockout tournament** selects the winning span
4. The winning span is appended to the sequence, and the process repeats

Swapping the auditor blade changes the alignment objective without modifying the draft model.

### The 5 Blades

| Blade | Objective | Model |
|-------|-----------|-------|
| Helpfulness | Response quality as an assistant | `OpenAssistant/reward-model-deberta-v3-large-v2` |
| Harmlessness | Avoids hate speech and harmful content | `facebook/roberta-hate-speech-dynabench-r4-target` |
| Safety | Avoids toxic content (weighted with draft probability) | `unitary/unbiased-toxic-roberta` |
| Informativeness | Maximises factual informativeness via NLI | `MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli` |
| Style | Maximises formal register | `s-nlp/roberta-base-formality-ranker` |

---

## Key Design Decisions

- **Span-level scoring** (SPAN_LEN=5): Rather than scoring one token at a time, we generate 5-token spans and score the full span. This is essential for classifier-type auditors (toxicity, NLI) which need sufficient context to produce meaningful scores.
- **Tournament sampling** (K=8): Rather than picking the highest-scoring candidate directly, candidates compete in a knockout bracket. Prevents degenerate always-refuse behaviour.
- **Weighted safety score**: Safety blade uses `0.7 * safety_score + 0.3 * draft_probability` to keep outputs grounded in coherent language while still avoiding toxic content.

---

## Compute Requirements

This project requires a GPU. All experiments were run on an NVIDIA H100 MIG slice (10.5GB VRAM) via the APPCAIR CloudExe server at BITS Pilani Goa.

**Minimum**: 8GB VRAM GPU  
**Recommended**: 16GB+ VRAM  
**VRAM used at peak**: ~5.41GB (all 6 models loaded simultaneously)

### Running on APPCAIR CloudExe

SSH into the server:
```bash
ssh -i /path/to/your/private_key -p 11421 root@inst-eu-2.cloudexe.tech
```

Activate the virtual environment:
```bash
source /root/swissknife-env/bin/activate
```

Run any script via cloudexe:
```bash
cloudexe --gpuspec EUNH100_0.14x1 -- /root/swissknife-env/bin/python /root/script.py
```

---

## Setup

### 1. Clone the repo
```bash
git clone https://github.com/Innit-Bruv/swissknife.git
cd swissknife
```

### 2. Create a virtual environment
```bash
python3 -m venv swissknife-env
source swissknife-env/bin/activate
```

### 3. Install dependencies
```bash
pip install torch==2.6.0 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt
```

### 4. Set your HuggingFace token
```bash
echo "export HF_TOKEN=your_token_here" >> ~/.bashrc
source ~/.bashrc
```

> You will need to accept Meta's license at huggingface.co/meta-llama/Llama-3.2-1B-Instruct before the draft model can be downloaded.

---

## Scripts

Scripts are numbered in the order they were developed. The final working version is `week3_step4.py`.

| Script | What it does |
|--------|-------------|
| `week2_step2.py` | First end-to-end pipeline — helpfulness blade vs greedy baseline |
| `week2_step3.py` | Two blades (helpfulness + safety) on 2 prompts |
| `week2_step4.py` | Upgraded to Llama-3.2-1B draft model |
| `week3_step1.py` | Updated safety blade, added tournament logic |
| `week3_step2.py` | All 5 blades, tournament K=8, token-level scoring |
| `week3_step3.py` | Span-level scoring (SPAN_LEN=5) — major improvement |
| `week3_step4.py` | **Final version** — stronger NLI, weighted safety, max_new_tokens=150 |

### Run the final pipeline
```bash
python scripts/week3_step4.py
```

---

## Results Summary

The pipeline was evaluated on 4 prompts — 3 benign and 1 harmful — across all 5 blades.

**Key findings:**
- Span-level scoring is essential for classifier-type auditors — token-level scoring causes degeneration
- Helpfulness and Style blades produce the most consistently distinct outputs
- Safety blade on harmful prompts spontaneously provides crisis hotlines — strongest alignment result
- Informativeness blade has no inherent safety signal — answers harmful prompts literally without mitigation
- Weighted combination for safety prevents degeneration while maintaining the alignment signal

Full experiment results with exact outputs are in `docs/swissknife_experiments.md`.

---

## Repository Structure

```
swissknife/
├── README.md
├── requirements.txt
├── scripts/
│   ├── week2_step2.py
│   ├── week2_step3.py
│   ├── week2_step4.py
│   ├── week3_step1.py
│   ├── week3_step2.py
│   ├── week3_step3.py
│   └── week3_step4.py
└── docs/
    ├── swissknife_plan.md
    └── swissknife_experiments.md
```

---

## References

- Das, A. (2026). *Swiss Knife: Plug-and-Play Alignment Heads via Tournament Sampling Auditors in Speculative Decoding*. Pragya Lab, BITS Pilani Goa.
- Leviathan et al. (2023). *Fast Inference from Transformers via Speculative Decoding*. arXiv:2211.17192.
- Das et al. (2025). *DPO Kernels: A Semantically-Aware, Kernel-Enhanced, and Divergence-Rich Paradigm for Direct Preference Optimization*. ACL 2025.
