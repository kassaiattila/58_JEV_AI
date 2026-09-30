"""Real PDFs and real graphs over a synthetic network: evidence that it runs, nothing more."""
import json
from datetime import datetime

from typesafe_sdk import Choice, Noul, SystemOneResponse
from jav.adapters.jev import JevAdapter
from jav.experiments.run_stack_trial import DATA, write_json
from jav.experiments.stack_trial import DirectAdapter, TypedAdapter, run_trial


class SyntheticClient:
    def system_one(self, *, state, questions, model):
        answers = {}
        for key, q in questions.items():
            if isinstance(q, Choice):
                choice = next(iter(q.criteria))
                answers[key] = dict(type="choice", choice=choice, confidence=.5,
                    probabilities={k: 1. if k == choice else 0. for k in q.criteria})
            elif isinstance(q, Noul):
                answers[key] = dict(type="noul", noul=.5)
            else:
                raise ValueError("unexpected score question")
        return SystemOneResponse.model_validate(dict(model=model, answers=answers,
            usage=dict(input_tokens=0, output_tokens=0)))


def main():
    cases = json.loads((DATA / "sample.json").read_text(encoding="utf-8"))["cases"]
    labels = json.loads((DATA / "labels.json").read_text(encoding="utf-8"))["cases"]
    out = DATA / datetime.now().strftime("offline_%H%M%S")
    out.mkdir()
    rows = []
    for case in cases:
        for flow in (["detect", "invoice"] if "invoice" in labels[case["case_id"]] else ["detect"]):
            for cls in (DirectAdapter, TypedAdapter):
                run_id = f"{case['case_id']}-{flow}-{cls.__name__}"
                base = JevAdapter(client=SyntheticClient(), cache_dir=out / "cache", model="jev-1.13.0")
                adapter = cls(base)
                try:
                    result = run_trial(flow, case["path"], out, run_id, adapter,
                                       doc_type=labels[case["case_id"]]["doc_type"] or "invoice_hu")
                    again = run_trial(flow, case["path"], out, run_id, adapter,
                                      doc_type=labels[case["case_id"]]["doc_type"] or "invoice_hu")
                    rows.append({"case_id": case["case_id"], "flow": flow, "adapter": cls.__name__,
                                 "status": result.final_status, "terminal_reload_equal": result == again,
                                 "passed": result == again and bool(result.final_status), "mocked_provider": True})
                except Exception as exc:
                    rows.append({"case_id": case["case_id"], "flow": flow, "adapter": cls.__name__,
                                 "passed": False, "error": type(exc).__name__, "message": str(exc)[:200]})
            print(case["case_id"], flow, rows[-2]["passed"], rows[-1]["passed"], flush=True)
            write_json(out / "checks.json", rows)
    print("offline checks", sum(r["passed"] for r in rows), "/", len(rows), out)


if __name__ == "__main__":
    main()
