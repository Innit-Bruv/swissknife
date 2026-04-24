import torch, time, warnings
warnings.filterwarnings("ignore")
from transformers import AutoTokenizer, AutoModelForCausalLM, AutoModelForSequenceClassification

draft_tokenizer = AutoTokenizer.from_pretrained("meta-llama/Llama-3.2-1B-Instruct")
draft_model = AutoModelForCausalLM.from_pretrained(
    "meta-llama/Llama-3.2-1B-Instruct", torch_dtype=torch.float16, device_map="auto"
)
draft_model.eval()

helpfulness_tokenizer = AutoTokenizer.from_pretrained("OpenAssistant/reward-model-deberta-v3-large-v2")
helpfulness_model = AutoModelForSequenceClassification.from_pretrained(
    "OpenAssistant/reward-model-deberta-v3-large-v2", torch_dtype=torch.float16, device_map="auto"
)
helpfulness_model.eval()
print("Models loaded.")

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

def score_helpfulness(ctx, span, input_ids=None, tid=None):
    inputs = helpfulness_tokenizer(ctx + span, return_tensors="pt", truncation=True, max_length=512).to("cuda")
    with torch.no_grad():
        out = helpfulness_model(**inputs)
    return out.logits[0].item()

def generate_greedy(prompt):
    inputs = draft_tokenizer(prompt, return_tensors="pt").to("cuda")
    with torch.no_grad():
        output = draft_model.generate(**inputs, max_new_tokens=100, do_sample=False)
    return draft_tokenizer.decode(output[0], skip_special_tokens=True)

def generate_scalar(prompt):
    input_ids = draft_tokenizer(prompt, return_tensors="pt").input_ids.to("cuda")
    generated_text = prompt
    for _ in range(20):
        with torch.no_grad():
            outputs = draft_model(input_ids)
            probs = torch.softmax(outputs.logits[0, -1, :], dim=-1)
            _, top_k_ids = torch.topk(probs, K)
        spans = [generate_span(input_ids, tid) for tid in top_k_ids.tolist()]
        scores = [score_helpfulness(generated_text, draft_tokenizer.decode(s)) for s in spans]
        best = spans[scores.index(max(scores))]
        input_ids = torch.cat([input_ids, best.unsqueeze(0)], dim=-1)
        generated_text += draft_tokenizer.decode(best)
        if draft_tokenizer.eos_token_id in best.tolist():
            break
    return generated_text

prompts = [
    "Tell me about the history of ancient Rome",
    "How do I stay productive working from home",
    "Explain how neural networks learn",
    "What are the benefits of exercise",
    "How do I improve my communication skills",
]

N = 3  # runs per prompt for averaging
greedy_times, scalar_times = [], []

for prompt in prompts:
    for _ in range(N):
        start = time.time()
        generate_greedy(prompt)
        greedy_times.append((time.time() - start) * 1000)

        start = time.time()
        generate_scalar(prompt)
        scalar_times.append((time.time() - start) * 1000)

avg_greedy = sum(greedy_times) / len(greedy_times)
avg_scalar = sum(scalar_times) / len(scalar_times)
overhead = ((avg_scalar - avg_greedy) / avg_greedy) * 100

print(f"\n{'='*50}")
print(f"LATENCY RESULTS (avg over {len(prompts)*N} runs)")
print(f"{'='*50}")
print(f"Greedy decoding:      {avg_greedy:.0f}ms per response")
print(f"Swiss Knife (scalar): {avg_scalar:.0f}ms per response")
print(f"Overhead:             {overhead:.1f}%")
print(f"Slowdown factor:      {avg_scalar/avg_greedy:.1f}x")
print("Done!")
