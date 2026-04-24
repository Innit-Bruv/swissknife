import csv, warnings
warnings.filterwarnings("ignore")

with open("/home/jovyan/eval_results.csv", "r", encoding="utf-8") as f:
    results = list(csv.DictReader(f))

methods = ["greedy", "helpfulness", "harmlessness", "safety", "informativeness", "style", "pairwise"]
categories = ["alpaca", "realtoxicity", "advbench"]
cat_labels = {"alpaca": "AlpacaEval (helpfulness)", "realtoxicity": "RealToxicityPrompts (safety)", "advbench": "AdvBench (refusal)"}

for category in categories:
    cat_results = [r for r in results if r["category"] == category]
    if not cat_results:
        continue
    n = len(cat_results)
    print(f"\n{'='*80}")
    print(f"{cat_labels[category]} — {n} prompts")
    print(f"{'='*80}")
    print(f"{'Method':<16} {'Helpfulness':>12} {'G-Eval':>8} {'Toxicity↓':>10} {'Harmless':>10} {'Refusal%':>10} {'Latency':>10}")
    print("-"*80)
    for m in methods:
        try:
            help_avg  = sum(float(r[f"{m}_helpfulness"]) for r in cat_results) / n
            geval_avg = sum(float(r[f"{m}_geval"]) for r in cat_results) / n
            tox_avg   = sum(float(r[f"{m}_toxicity"]) for r in cat_results) / n
            harm_avg  = sum(float(r[f"{m}_harmlessness"]) for r in cat_results) / n
            ref_avg   = sum(float(r[f"{m}_refusal"]) for r in cat_results) / n * 100
            lat_avg   = sum(float(r[f"{m}_latency_ms"]) for r in cat_results) / n
            print(f"{m:<16} {help_avg:>12.3f} {geval_avg:>8.1f} {tox_avg:>10.4f} {harm_avg:>10.4f} {ref_avg:>9.1f}% {lat_avg:>9.0f}ms")
        except:
            print(f"{m:<16} (no data)")

print("\nDone!")
