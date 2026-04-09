import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, AutoModelForSequenceClassification

# ── Load draft model ──────────────────────────────────────────────────────────
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

# ── Blade 5: Style ────────────────────────────────────────────────────────────
style_tokenizer = AutoTokenizer.from_pretrained("s-nlp/roberta-base-formality-ranker")
style_model = AutoModelForSequenceClassification.from_pretrained(
    "s-nlp/roberta-base-formality-ranker", device_map="auto"
)
style_model.eval()

print(f"All models loaded. VRAM: {torch.cuda.memory_allocated() / 1e9:.2f} GB / {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")

# ── Scoring functions (unchanged from EXP-04) ─────────────────────────────────
def score_helpfulness(context_text, span_text):
    full_text = context_text + span_text
    inputs = helpfulness_tokenizer(full_text, return_tensors="pt", truncation=True, max_length=512).to("cuda")
    with torch.no_grad():
        output = helpfulness_model(**inputs)
    return output.logits[0].item()

def score_harmlessness(context_text, span_text):
    full_text = context_text + span_text
    inputs = harmless_tokenizer(full_text, return_tensors="pt", truncation=True, max_length=512).to("cuda")
    with torch.no_grad():
        output = harmless_model(**inputs)
    probs = torch.softmax(output.logits[0], dim=-1)
    return probs[0].item()

def score_safety(context_text, span_text):
    full_text = context_text + span_text
    inputs = safety_tokenizer(full_text, return_tensors="pt", truncation=True, max_length=512).to("cuda")
    with torch.no_grad():
        output = safety_model(**inputs)
    probs = torch.softmax(output.logits[0], dim=-1)
    return probs[0].item()

def score_informativeness(context_text, span_text):
    full_text = context_text + span_text
    inputs = inform_tokenizer(context_text, full_text, return_tensors="pt", truncation=True, max_length=512).to("cuda")
    with torch.no_grad():
        output = inform_model(**inputs)
    probs = torch.softmax(output.logits[0], dim=-1)
    return probs[1].item()

def score_style(context_text, span_text):
    full_text = context_text + span_text
    inputs = style_tokenizer(full_text, return_tensors="pt", truncation=True, max_length=512).to("cuda")
    with torch.no_grad():
        output = style_model(**inputs)
    probs = torch.softmax(output.logits[0], dim=-1)
    return probs[1].item()

# ── THE ONLY CHANGE: Span generation ─────────────────────────────────────────
# Instead of scoring one token, generate SPAN_LEN tokens greedily for each
# top-K first token, then score the whole span. Gives auditor real text to work with.

SPAN_LEN = 5  # number of tokens per span candidate
K = 8         # number of span candidates

def generate_span(input_ids, first_token_id):
    """Given a starting token, greedily generate SPAN_LEN tokens to form a span."""
    span_ids = input_ids.clone()
    first = torch.tensor([[first_token_id]], device="cuda")
    span_ids = torch.cat([span_ids, first], dim=-1)

    for _ in range(SPAN_LEN - 1):
        with torch.no_grad():
            out = draft_model(span_ids)
            next_id = torch.argmax(out.logits[0, -1, :]).unsqueeze(0).unsqueeze(0)
        span_ids = torch.cat([span_ids, next_id], dim=-1)

    # Return only the new span tokens (not the full context)
    new_tokens = span_ids[0, input_ids.shape[1]:]
    return new_tokens

def knockout_tournament_span(span_candidates, score_fn, context_text):
    """Tournament among spans. Each candidate is a list of token ids."""
    remaining = list(range(len(span_candidates)))

    while len(remaining) > 1:
        next_round = []
        for i in range(0, len(remaining) - 1, 2):
            idx_a = remaining[i]
            idx_b = remaining[i + 1]
            text_a = draft_tokenizer.decode(span_candidates[idx_a])
            text_b = draft_tokenizer.decode(span_candidates[idx_b])
            score_a = score_fn(context_text, text_a)
            score_b = score_fn(context_text, text_b)
            winner = idx_a if score_a >= score_b else idx_b
            next_round.append(winner)
        if len(remaining) % 2 == 1:
            next_round.append(remaining[-1])
        remaining = next_round

    return span_candidates[remaining[0]]

def generate_span_tournament(prompt, score_fn, max_spans=20):
    """
    Span-level Swiss Knife generation.
    At each step: generate K candidate spans, tournament picks best, append winning span.
    """
    input_ids = draft_tokenizer(prompt, return_tensors="pt").input_ids.to("cuda")
    generated_text = prompt

    for step in range(max_spans):
        # Get top-K first tokens
        with torch.no_grad():
            outputs = draft_model(input_ids)
            next_token_logits = outputs.logits[0, -1, :]
            probs = torch.softmax(next_token_logits, dim=-1)
            top_k_probs, top_k_ids = torch.topk(probs, K)

        # Generate a full span for each of the K first tokens
        span_candidates = []
        for first_token_id in top_k_ids.tolist():
            span = generate_span(input_ids, first_token_id)
            span_candidates.append(span)

        # Tournament picks the best span
        winning_span = knockout_tournament_span(span_candidates, score_fn, generated_text)

        # Append winning span to sequence
        winning_span_tensor = winning_span.unsqueeze(0)
        input_ids = torch.cat([input_ids, winning_span_tensor], dim=-1)
        generated_text += draft_tokenizer.decode(winning_span)

        # Stop if EOS appears in winning span
        if draft_tokenizer.eos_token_id in winning_span.tolist():
            break

    return generated_text

# ── Greedy baseline ───────────────────────────────────────────────────────────
def generate_greedy(prompt, max_new_tokens=100):
    inputs = draft_tokenizer(prompt, return_tensors="pt").to("cuda")
    with torch.no_grad():
        output = draft_model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
    return draft_tokenizer.decode(output[0], skip_special_tokens=True)

# ── Same prompts as EXP-04 for direct comparison ─────────────────────────────
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
        print(f"\n[SPAN-LEVEL TOURNAMENT K=8 - {blade_name} blade]")
        print(generate_span_tournament(prompt, score_fn))

print("\nDone!")
