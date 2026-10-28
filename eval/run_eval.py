import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import pathlib
import random
import subprocess
import sys
from datetime import datetime

PAGE_TOL = 0

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from mini_rag import search


def get_git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def verify_locked_test(path: str) -> None:
    p = pathlib.Path(path)
    sha_file = p.with_suffix(".sha256")
    if sha_file.exists():
        expected = sha_file.read_text(encoding="utf-8").split()[0].strip()
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        if expected != actual:
            raise RuntimeError(f"KİLİTLİ TEST SETİ DEĞİŞTİRİLMİŞ! Beklenen={expected}, Gerçek={actual}")


def bootstrap_ci(values: list[float], n_boot: int = 1000, seed: int = 42) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(n_boot):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    low = means[int(0.025 * n_boot)]
    high = means[int(0.975 * n_boot)]
    return (low, high)


def evaluate_dataset(
    questions_path: str = "eval/dev.json",
    k: int = 4,
    use_rewrite: bool = True,
    run_e2e: bool = False,
    quiet_items: bool = False,
) -> dict:
    if "test_locked" in questions_path:
        verify_locked_test(questions_path)

    with open(questions_path, "r", encoding="utf-8") as f:
        questions = json.load(f)

    hit1_list, hit3_list, hit5_list, rr_list = [], [], [], []
    ans_distances, unans_distances = [], []

    # E2E judge lists
    e2e_correct, e2e_partial, e2e_false_abstain, e2e_wrong_confident = [], [], [], []
    unans_correct_abstain = []

    if run_e2e:
        from src.generate import generate_answer
        from eval.judge import judge_answer

    print(f"\n{'=' * 78}")
    print(f"DEĞERLENDİRME SETİ: {questions_path} (k={k}, rewrite={use_rewrite}, e2e={run_e2e})")
    print(f"{'=' * 78}")

    if use_rewrite:
        from src.query_rewrite import rewrite_query
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda item: rewrite_query(item["soru"], use_llm=True), questions))

    e2e_tasks = []

    for idx_q, q in enumerate(questions, 1):
        qid = str(q.get("id", idx_q))
        soru = q["soru"]
        cevapsiz = bool(q.get("cevapsiz", False))
        beklenen_dosya = q.get("beklenen_dosya")
        beklenen_sayfa = q.get("beklenen_sayfa")
        kabul = [(beklenen_dosya, beklenen_sayfa)] + [
            (a["dosya"], a["sayfa"]) for a in (q.get("ek_kabul") or [])
        ]

        results = search(soru, k=max(k, 6), use_rewrite=use_rewrite)
        top1_dist = results[0][2] if results else 1.0

        if cevapsiz:
            unans_distances.append(top1_dist)
            if run_e2e:
                e2e_tasks.append((soru, "", True, results[:6]))
            if not quiet_items and "test_locked" not in questions_path:
                print(f"[{qid:6s} - CEVAPSIZ] {soru[:50]:50s} | Top-1 Mesafe: {top1_dist:.3f}")
        else:
            ans_distances.append(top1_dist)
            rank = None
            for idx, (_, meta, _) in enumerate(results, 1):
                eslesen = any(
                    meta["file"] == f and p is not None and abs(meta["page"] - p) <= PAGE_TOL
                    for f, p in kabul
                )
                if eslesen:
                    rank = idx
                    break

            h1 = 1.0 if rank == 1 else 0.0
            h3 = 1.0 if (rank is not None and rank <= 3) else 0.0
            h5 = 1.0 if (rank is not None and rank <= 5) else 0.0
            rr = (1.0 / rank) if (rank is not None and rank <= k) else 0.0

            hit1_list.append(h1)
            hit3_list.append(h3)
            hit5_list.append(h5)
            rr_list.append(rr)

            if run_e2e:
                e2e_tasks.append((soru, q.get("dogru_cevap", ""), False, results[:6]))

            if not quiet_items and "test_locked" not in questions_path:
                durum = "✓ Hit@1" if rank == 1 else (f"✓ Hit@{rank}" if rank and rank <= 3 else "✗ Kaçırdı")
                print(f"[{qid:6s}] {soru[:46]:46s} | {durum:10s} | Top-1: {top1_dist:.3f}")

    if run_e2e and e2e_tasks:
        def _run_one_e2e(task_tuple):
            s_q, exp_a, is_unans, pre_res = task_tuple
            gen = generate_answer(s_q, k=6, use_rewrite=use_rewrite, precomputed_results=pre_res)
            jres = judge_answer(s_q, exp_a, gen["answer"], is_unanswerable=is_unans)
            return is_unans, jres

        with ThreadPoolExecutor(max_workers=3) as pool:
            for is_unans, jres in pool.map(_run_one_e2e, e2e_tasks):
                if is_unans:
                    unans_correct_abstain.append(1.0 if jres["abstained"] else 0.0)
                else:
                    e2e_correct.append(1.0 if jres["verdict"] == "dogru" else 0.0)
                    e2e_partial.append(1.0 if jres["verdict"] in ("dogru", "kismen") else 0.0)
                    e2e_false_abstain.append(1.0 if jres["abstained"] else 0.0)
                    e2e_wrong_confident.append(1.0 if jres["wrong_confident"] else 0.0)

    ans_count = len(hit1_list)
    metrics = {"dataset": questions_path, "ans_count": ans_count, "unans_count": len(unans_distances)}

    if ans_count > 0:
        h1_mean = sum(hit1_list) / ans_count * 100
        h3_mean = sum(hit3_list) / ans_count * 100
        h5_mean = sum(hit5_list) / ans_count * 100
        mrr_mean = sum(rr_list) / ans_count
        h1_ci = tuple(x * 100 for x in bootstrap_ci(hit1_list))
        h3_ci = tuple(x * 100 for x in bootstrap_ci(hit3_list))
        mrr_ci = bootstrap_ci(rr_list)

        metrics.update({
            "hit1": h1_mean, "hit1_ci": h1_ci,
            "hit3": h3_mean, "hit3_ci": h3_ci,
            "hit5": h5_mean,
            "mrr": mrr_mean, "mrr_ci": mrr_ci,
            "avg_ans_dist": sum(ans_distances) / ans_count,
        })
        print(f"{'-' * 78}")
        print(f"RETRIEVAL METRİKLERİ (n={ans_count}):")
        print(f"  • Hit@1 : %{h1_mean:.1f} ({int(sum(hit1_list))}/{ans_count}) [%95 GA: %{h1_ci[0]:.1f} - %{h1_ci[1]:.1f}]")
        print(f"  • Hit@3 : %{h3_mean:.1f} ({int(sum(hit3_list))}/{ans_count}) [%95 GA: %{h3_ci[0]:.1f} - %{h3_ci[1]:.1f}]")
        print(f"  • Hit@5 : %{h5_mean:.1f} ({int(sum(hit5_list))}/{ans_count})")
        print(f"  • MRR   : {mrr_mean:.3f} [%95 GA: {mrr_ci[0]:.3f} - {mrr_ci[1]:.3f}]")

    if run_e2e and ans_count > 0:
        c_rate = sum(e2e_correct) / ans_count * 100
        p_rate = sum(e2e_partial) / ans_count * 100
        fa_rate = sum(e2e_false_abstain) / ans_count * 100
        wc_rate = sum(e2e_wrong_confident) / ans_count * 100
        p_ci = tuple(x * 100 for x in bootstrap_ci(e2e_partial))
        metrics.update({
            "e2e_correct": c_rate,
            "e2e_useful": p_rate,
            "e2e_useful_ci": p_ci,
            "false_abstain": fa_rate,
            "wrong_confident": wc_rate,
        })
        print(f"UÇTAN UCA (LLM HAKEM) METRİKLERİ (n={ans_count}):")
        print(f"  • Tam Doğru Cevap       : %{c_rate:.1f} ({int(sum(e2e_correct))}/{ans_count})")
        print(f"  • Doğru + Kısmen Doğru  : %{p_rate:.1f} ({int(sum(e2e_partial))}/{ans_count}) [%95 GA: %{p_ci[0]:.1f} - %{p_ci[1]:.1f}]")
        print(f"  • Gereksiz Abstention   : %{fa_rate:.1f} ({int(sum(e2e_false_abstain))}/{ans_count})")
        print(f"  • Yanlış-Güvenli Cevap  : %{wc_rate:.1f} ({int(sum(e2e_wrong_confident))}/{ans_count})")

    if run_e2e and unans_correct_abstain:
        ua_count = len(unans_correct_abstain)
        ua_rate = sum(unans_correct_abstain) / ua_count * 100
        ua_ci = tuple(x * 100 for x in bootstrap_ci(unans_correct_abstain))
        metrics.update({"unans_abstain_acc": ua_rate, "unans_abstain_ci": ua_ci})
        print(f"CEVAPSIZ SET ABSTENTION DOĞRULUĞU (n={ua_count}):")
        print(f"  • Doğru Abstention      : %{ua_rate:.1f} ({int(sum(unans_correct_abstain))}/{ua_count}) [%95 GA: %{ua_ci[0]:.1f} - %{ua_ci[1]:.1f}]")

    print(f"{'=' * 78}\n")
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("label", nargs="?", default="deney")
    parser.add_argument("--dataset", default="eval/dev.json")
    parser.add_argument("--k", type=int, default=4)
    parser.add_argument("--no-rewrite", action="store_true")
    parser.add_argument("--e2e", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    m = evaluate_dataset(
        questions_path=args.dataset,
        k=args.k,
        use_rewrite=not args.no_rewrite,
        run_e2e=args.e2e,
        quiet_items=args.quiet,
    )
    if m.get("ans_count", 0) > 0:
        commit = get_git_commit()
        with open("eval/sonuclar.md", "a", encoding="utf-8") as f:
            f.write(
                f"| {datetime.now():%Y-%m-%d %H:%M} | {args.label} ({pathlib.Path(args.dataset).stem}, {commit}) "
                f"| tol={PAGE_TOL} | {m['ans_count']}+{m['unans_count']} | {m['hit1']:.1f} | {m['hit3']:.1f} "
                f"| {m['mrr']:.3f} | {m.get('avg_ans_dist', 0.0):.3f} | - |\n"
            )
