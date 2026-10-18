"""CLI flows that compose several components: `docs` and `review` on the candidates of a recorded run."""

import datetime
from collections.abc import Mapping
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from .collect import CollectClients, CollectSettings, collect_documents, collect_profiles, companies
from .docstore import DocStore
from .records import RecordStore
from .research import prompt_version
from .review import ReviewDeps, ReviewSettings, review_candidates
from .sector import Peers
from .tickers import read_column


class EvalNotPassedError(RuntimeError):
    pass


def collect_run(cfg: dict[str, Any], root: Path, env: Mapping[str, str], run: str | None, today: datetime.date) -> None:
    """Collect the documents of the stage 2 candidates of run ``run`` (default: the latest) and print a summary."""
    with ExitStack() as stack:
        clients = CollectClients.from_config(cfg, env, stack, cfg["docs"]["search"])
        with RecordStore.from_config(cfg, root) as records:
            run_id = records.resolve_run(run)
            candidates = records.candidates(run_id)
        print(f"Collecting documents of {len(candidates)} candidates of run {run_id}...")
        names = read_column(root / cfg["system"]["input_csv"], "name")
        store = stack.enter_context(DocStore.from_config(cfg, root))
        summary = collect_documents(
            companies(candidates, names), CollectSettings.from_config(cfg), clients, store, today
        )
    if summary.searches_left:
        print(f"Search quota used up: {summary.searches_left} candidates left for the next `docs` run.")
    text = f"{summary.edinet_docs} documents stored for {len(candidates) - summary.edinet_failed} tickers; "
    text += f"{summary.edinet_failed} tickers failed."
    print(f"{text} {summary.web_docs} web documents stored." if clients.search else text)


def profiles_run(
    cfg: dict[str, Any], root: Path, env: Mapping[str, str], tickers: list[str], today: datetime.date
) -> None:
    """Collect the EDINET annual report sections of every ticker and print a summary."""
    with ExitStack() as stack:
        clients = CollectClients.from_config(cfg, env, stack, False)
        store = stack.enter_context(DocStore.from_config(cfg, root))
        summary = collect_profiles(tickers, CollectSettings.from_config(cfg), clients, store, today)
    print(f"{summary.edinet_docs} reports stored, {summary.edinet_failed} failed.")


def review_run(
    cfg: dict[str, Any], root: Path, env: Mapping[str, str], run: str | None, tickers: list[str] | None
) -> None:
    """Review the candidates of run ``run`` (default: the latest) and print a summary; refuse unless this prompt and
    model passed the eval."""
    sectors = read_column(root / cfg["system"]["input_csv"], "sector33")
    with RecordStore.from_config(cfg, root) as records:
        run_id = records.resolve_run(run)
        candidates = records.candidates(run_id)
        peers = Peers.from_run(records, run_id, sectors, cfg)
    with ExitStack() as stack:
        deps = ReviewDeps.from_config(cfg, root, env, stack, peers)
        version, model = prompt_version(deps.prompts), deps.llm.primary.model
        if not deps.reviews.passed_eval(version, model):
            raise EvalNotPassedError(f"no passed review-eval for prompt {version} / {model}; run `review-eval` first")
        summary = review_candidates(run_id, candidates, tickers, ReviewSettings.from_config(cfg), deps)
    print(
        f"Run {run_id}: {summary.reviewed} reviewed, {summary.failed} failed, {summary.needs_attention} need attention."
    )
    print(f"Memos written to {deps.memo_dir}.")
