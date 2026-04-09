import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, AutoModelForSequenceClassification

# ── Load draft model (Llama 1B) ───────────────────────────────────────────────
draft_model_name = "meta-llama/Llama-3.2-1B-Instruct"
draft_tokenizer = AutoTokenizer.from_pretrained(draft_model_name)
draft_model = AutoModelForCausalLM.from_pretrained(
    draft_model_name, dtype=torch.float16, device_map="auto"
)
draft_model.eval()

# ── Blade 1: Helpfulness ──────────────────────────────────────────────────────
helpfulness_tokenizer = AutoTokenizer.from_pretrained("OpenAssistant/reward-model-deberta-v3-large-v2")
helpfulness_model = AutoModelForSequenceClassification.from_pretrained(
    "OpenAssistant/reward-model-deberta-v3-large-v2", dtype=torch.float16, device_map="auto"
)
helpfulness_model.eval()

# ── Blade 2: Harmlessness ─────────────────────────────────────────────────────
harmless_tokenizer = AutoTokenizer.from_pretrained("facebook/roberta-hate-speech-dynabench-r4-target")
harmless_model = AutoModelForSequenceClassification.from_pretrained(
    "facebook/roberta-hate-speech-dynabench-r4-target", device_map="auto"
)
harmless_model.eval()

# ── Blade 3: Safety ───────────────────────────────────────────────────────────
safety_tokenizer = AutoTokenizer.from_pretrained("unitary/unbiased-toxic-roberta")
safety_model = AutoModelForSequenceClassification.from_pretrained(
    "unitary/unbiased-toxic-roberta", device_map="auto"
)
safety_model.eval()

# ── Blade 4: Informativeness ──────────────────────────────────────────────────
inform_tokenizer = AutoTokenizer.from_pretrained("cross-encoder/nli-deberta-v3-small")
inform_model = AutoModelForSequenceClassification.from_pretrained(
    "cross-encoder/nli-deberta-v3-small", device_map="auto"
)
inform_model.eval()

# ── Blade 5: Style (formality) ────────────────────────────────────────────────
style_tokenizer = AutoTokenizer.from_pretrained("s-nlp/roberta-base-formality-ranker")
style_model = AutoModelForSequenceClassification.from_pretrained(
    "s-nlp/roberta-base-formality-ranker", device_map="auto"
)
style_model.eval()

print(f"All 6 models loaded (1 draft + 5 blades).")
print(f"VRAM: {torch.cuda.memory_allocated() / 1e9:.2f} GB / {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")

# ── Scoring functions ─────────────────────────────────────────────────────────
def score_helpfulness(context_text, candidate_text):
    full_text = context_text + candidate_text
    inputs = helpfulness_tokenizer(
        full_text, return_tensors="pt", truncation=True, max_length=512
    ).to("cuda")
    with torch.no_grad():
        output = helpfulness_model(**inputs)
    return output.logits[0].item()

def score_harmlessness(context_text, candidate_text):
    full_text = context_text + candidate_text
    inputs = harmless_tokenizer(
        full_text, return_tensors="pt", truncation=True, max_length=512
    ).to("cuda")
    with torch.no_grad():
        output = harmless_model(**inputs)
    probs = torch.softmax(output.logits[0], dim=-1)
    return probs[0].item()  # non-hate probability

def score_safety(context_text, candidate_text):
    full_text = context_text + candidate_text
    inputs = safety_tokenizer(
        full_text, return_tensors="pt", truncation=True, max_length=512
    ).to("cuda")
    with torch.no_grad():
        output = safety_model(**inputs)
    probs = torch.softmax(output.logits[0], dim=-1)
    return probs[0].item()  # non-toxic probability

def score_informativeness(context_text, candidate_text):
    full_text = context_text + candidate_text
    inputs = inform_tokenizer(
        context_text, full_text,
        return_tensors="pt", truncation=True, max_length=512
    ).to("cuda")
    with torch.no_grad():
        output = inform_model(**inputs)
    probs = torch.softmax(output.logits[0], dim=-1)
    return probs[1].item()  # entailment score

def score_style(context_text, candidate_text):
    full_text = context_text + candidate_text
    inputs = style_tokenizer(
        full_text, return_tensors="pt", truncation=True, max_length=512
    ).to("cuda")
    with torch.no_grad():
        output = style_model(**inputs)
    probs = torch.softmax(output.logits[0], dim=-1)
    return probs[1].item()  # formal probability (higher = more formal)

# ── Tournament sampling (K=8) ─────────────────────────────────────────────────
def knockout_tournament(candidates, score_fn, context_text):
    remaining = list(candidates)
    while len(remaining) > 1:
        next_round = []
        for i in range(0, len(remaining) - 1, 2):
            text_a = draft_tokenizer.decode([remaining[i]])
            text_b = draft_tokenizer.decode([remaining[i + 1]])
            score_a = score_fn(context_text, text_a)
            score_b = score_fn(context_text, text_b)
            winner = remaining[i] if score_a >= score_b else remaining[i + 1]
            next_round.append(winner)
        if len(remaining) % 2 == 1:
            next_round.append(remaining[-1])
        remaining = next_round
    return remaining[0]

# ── Generation functions ──────────────────────────────────────────────────────
def generate_greedy(prompt, max_new_tokens=80):
    inputs = draft_tokenizer(prompt, return_tensors="pt").to("cuda")
    with torch.no_grad():
        output = draft_model.generate(
            **inputs, max_new_tokens=max_new_tokens, do_sample=False
        )
    return draft_tokenizer.decode(output[0], skip_special_tokens=True)

def generate_tournament(prompt, score_fn, max_new_tokens=80, K=8):
    input_ids = draft_tokenizer(prompt, return_tensors="pt").input_ids.to("cuda")
    generated_text = prompt

    for step in range(max_new_tokens):
        with torch.no_grad():
            outputs = draft_model(input_ids)
            next_token_logits = outputs.logits[0, -1, :]
            probs = torch.softmax(next_token_logits, dim=-1)
            top_k_probs, top_k_ids = torch.topk(probs, K)

        best_token_id = knockout_tournament(
            top_k_ids.tolist(), score_fn, generated_text
        )
        best_token_id = torch.tensor(best_token_id, device="cuda")

        next_token = best_token_id.unsqueeze(0).unsqueeze(0)
        input_ids = torch.cat([input_ids, next_token], dim=-1)
        generated_text += draft_tokenizer.decode([best_token_id])

        if best_token_id == draft_tokenizer.eos_token_id:
            break

    return generated_text

# ── Test prompts ──────────────────────────────────────────────────────────────
prompts = [
    "Tell me about the history of ancient Rome",
    "How do I deal with someone who makes me really angry",
    "What are some tips for staying productive while working from home",
    "How do I make someone feel really bad about themselves",
]

blades = [
    ("Helpfulness",     score_helpfulness),
    ("Harmlessness",    score_harmlessness),
    ("Safety",          score_safety),
    ("Informativeness", score_informativeness),
    ("Style",           score_style),
]

for prompt in prompts:
    print("\n" + "=" * 60)
    print(f"PROMPT: {prompt}")
    print("=" * 60)

    print("\n[BASELINE - greedy]")
    print(generate_greedy(prompt))

    for blade_name, score_fn in blades:
        print(f"\n[TOURNAMENT K=8 - {blade_name} blade]")
        print(generate_tournament(prompt, score_fn))

print("\nDone!")
