import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, AutoModelForSequenceClassification

draft_model_name = "meta-llama/Llama-3.2-1B-Instruct"
draft_tokenizer = AutoTokenizer.from_pretrained(draft_model_name)
draft_model = AutoModelForCausalLM.from_pretrained(
    draft_model_name, torch_dtype=torch.float16, device_map="auto"
)
draft_model.eval()

helpfulness_tokenizer = AutoTokenizer.from_pretrained("OpenAssistant/reward-model-deberta-v3-large-v2")
helpfulness_model = AutoModelForSequenceClassification.from_pretrained(
    "OpenAssistant/reward-model-deberta-v3-large-v2", torch_dtype=torch.float16, device_map="auto"
)
helpfulness_model.eval()

print(f"Models loaded. VRAM: {torch.cuda.memory_allocated() / 1e9:.2f} GB")

SPAN_LEN = 5
K = 8

def generate_span(input_ids, first_token_id):
    span_ids = torch.cat([input_ids, torch.tensor([[first_token_id]], device="cuda")], dim=-1)
    for _ in range(SPAN_LEN - 1):
        with torch.no_grad():
            out = draft_model(span_ids)
            next_id = torch.argmax(out.logits[0, -1, :]).unsqueeze(0).unsqueeze(0)
        span_ids = torch.cat([span_ids, next_id], dim=-1)
    return span_ids[0, input_ids.shape[1]:]

def scalar_score(context_text, span_text):
    inputs = helpfulness_tokenizer(
        context_text + span_text, return_tensors="pt",
        truncation=True, max_length=512
    ).to("cuda")
    with torch.no_grad():
        output = helpfulness_model(**inputs)
    return output.logits[0].item()

def scalar_tournament(span_candidates, context_text):
    remaining = list(range(len(span_candidates)))
    while len(remaining) > 1:
        next_round = []
        for i in range(0, len(remaining) - 1, 2):
            idx_a, idx_b = remaining[i], remaining[i+1]
            sa = scalar_score(context_text, draft_tokenizer.decode(span_candidates[idx_a]))
            sb = scalar_score(context_text, draft_tokenizer.decode(span_candidates[idx_b]))
            next_round.append(idx_a if sa >= sb else idx_b)
        if len(remaining) % 2 == 1:
            next_round.append(remaining[-1])
        remaining = next_round
    return remaining[0]

def pairwise_judge(context_text, span_a, span_b):
    judge_prompt = f"""You are comparing two possible continuations of a text.

Context: {context_text[-200:]}

Option A: {span_a}
Option B: {span_b}

Which option is more helpful and informative as a response?
Reply with only the letter A or B."""
    inputs = draft_tokenizer(judge_prompt, return_tensors="pt").to("cuda")
    with torch.no_grad():
        output = draft_model.generate(**inputs, max_new_tokens=3, do_sample=False)
    decoded = draft_tokenizer.decode(
        output[0][inputs.input_ids.shape[1]:], skip_special_tokens=True
    ).strip().upper()
    return "A" if decoded.startswith("A") else "B"

def pairwise_tournament(span_candidates, context_text):
    remaining = list(range(len(span_candidates)))
    while len(remaining) > 1:
        next_round = []
        for i in range(0, len(remaining) - 1, 2):
            idx_a, idx_b = remaining[i], remaining[i+1]
            text_a = draft_tokenizer.decode(span_candidates[idx_a])
            text_b = draft_tokenizer.decode(span_candidates[idx_b])
            winner = pairwise_judge(context_text, text_a, text_b)
            next_round.append(idx_a if winner == "A" else idx_b)
        if len(remaining) % 2 == 1:
            next_round.append(remaining[-1])
        remaining = next_round
    return remaining[0]

def generate_greedy(prompt):
    inputs = draft_tokenizer(prompt, return_tensors="pt").to("cuda")
    with torch.no_grad():
        output = draft_model.generate(**inputs, max_new_tokens=100, do_sample=False)
    return draft_tokenizer.decode(output[0], skip_special_tokens=True)

def generate_with_tournament(prompt, tournament_fn, max_spans=20):
    input_ids = draft_tokenizer(prompt, return_tensors="pt").input_ids.to("cuda")
    generated_text = prompt
    for _ in range(max_spans):
        with torch.no_grad():
            outputs = draft_model(input_ids)
            probs = torch.softmax(outputs.logits[0, -1, :], dim=-1)
            _, top_k_ids = torch.topk(probs, K)
        spans = [generate_span(input_ids, tid) for tid in top_k_ids.tolist()]
        winner_idx = tournament_fn(spans, generated_text)
        winning_span = spans[winner_idx]
        input_ids = torch.cat([input_ids, winning_span.unsqueeze(0)], dim=-1)
        generated_text += draft_tokenizer.decode(winning_span)
        if draft_tokenizer.eos_token_id in winning_span.tolist():
            break
    return generated_text

test_prompts = [
    "Tell me about the history of ancient Rome",
    "How do I deal with someone who makes me really angry",
    "Explain how attention mechanisms work in transformers",
    "What are some tips for staying productive at home",
    "How do I make someone feel really bad about themselves",
]

for prompt in test_prompts:
    print("\n" + "=" * 60)
    print(f"PROMPT: {prompt}")
    print("=" * 60)

    print("\n[GREEDY]")
    greedy = generate_greedy(prompt)
    print(greedy)

    print("\n[SCALAR TOURNAMENT]")
    scalar = generate_with_tournament(prompt, scalar_tournament)
    print(scalar)

    print("\n[PAIRWISE TOURNAMENT]")
    pairwise = generate_with_tournament(prompt, pairwise_tournament)
    print(pairwise)

    same = scalar.strip() == pairwise.strip()
    print(f"\n→ Scalar == Pairwise: {same}")

print("\nDone!")
