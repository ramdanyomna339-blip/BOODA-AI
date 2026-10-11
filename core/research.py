"""Source-backed research without an LLM; findings require human review.

Wikipedia is a discovery source, not independent corroboration. Network calls
send only the explicit query, never stored profile, memory, or document text.
"""

from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
from email.utils import parsedate_to_datetime
from hashlib import sha256
import http.client
import json
import math
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit
from urllib.parse import urlencode, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler
from uuid import uuid4

from core.persistence import JsonObjectStore
from core.knowledge_base import _terms
from core.research_web import PublicTextFetcher, WebSearch, source_from_response


def now():
    return datetime.now(timezone.utc).isoformat()


def _text(value, name, limit=12000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must contain 1–{limit} characters.")
    return value.strip()


def source_freshness(source, *, at=None):
    stamp = source.get("updated_at")
    if not stamp:
        return "unknown"
    try:
        try:
            date = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            date = parsedate_to_datetime(stamp)
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        age = ((at or datetime.now(timezone.utc)) - date).days
        return "unknown" if age < 0 else "review_age" if age > 180 else "recent_revision"
    except (ValueError, TypeError, OverflowError):
        return "unknown"


def _locked(method):
    """Serialize read-modify-write cycles across workspace processes."""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        self.store.file_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.store.file_path) + ".lock.sqlite3", timeout=120) as lock:
            lock.execute("BEGIN IMMEDIATE")
            self.data = self.store.load()
            self.data.setdefault("sessions", {})
            return method(self, *args, **kwargs)
    return wrapped


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Research provider redirects are disabled.")


class WikipediaSearch:
    """Bounded, fixed-host public encyclopedia search in Arabic or English."""

    def search(self, query, *, language="ar", limit=5):
        if language not in {"ar", "en"}:
            raise ValueError("Language must be ar or en.")
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise ValueError("Query must contain 1–500 characters.")
        if type(limit) is not int or not 1 <= limit <= 5:
            raise ValueError("Limit must be between 1 and 5.")
        params = urlencode({
            "action": "query", "format": "json", "formatversion": 2,
            "generator": "search", "gsrsearch": query, "gsrlimit": limit,
            "prop": "extracts|revisions", "exintro": 1, "explaintext": 1,
            "exchars": 1500, "rvprop": "timestamp",
        })
        request = Request(f"https://{language}.wikipedia.org/w/api.php?{params}",
                          headers={"User-Agent": "BoodaResearch/1.0 (local research tool)"})
        with build_opener(_NoRedirect()).open(request, timeout=15) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Research response exceeds size limit.")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Invalid research provider response.")
        if "error" in payload:
            raise ValueError("Research provider returned an API error.")
        pages = payload.get("query", {}).get("pages", [])
        if not isinstance(pages, list) or any(not isinstance(page, dict) for page in pages):
            raise ValueError("Invalid research provider pages.")
        results = []
        for page in sorted(pages, key=lambda p: p.get("index", 0))[:limit]:
            text = page.get("extract", "").strip()
            if not text:
                continue
            revisions = page.get("revisions") or [{}]
            results.append({
                "title": page["title"], "text": text[:1500],
                "source": f"https://{language}.wikipedia.org/wiki/" + quote(page["title"], safe=""),
                "updated_at": revisions[0].get("timestamp"),
                "publisher": "Wikipedia", "kind": "encyclopedia",
            })
        return results


class BoodaResearchManager:
    def __init__(self, file_path="knowledge/research.json", *, knowledge_base=None,
                 provider=None, output_dir="outputs/research", web_provider=None,
                 fetcher=None, event_log=None):
        self.store = JsonObjectStore(file_path)
        self.data = self.store.load()
        self.data.setdefault("sessions", {})
        self.knowledge_base = knowledge_base
        self.provider = provider if provider is not None else WikipediaSearch()
        self.output_dir = Path(output_dir)
        self.fetcher = fetcher or PublicTextFetcher()
        self.web_provider = web_provider or WebSearch(self.fetcher)
        self.event_log = event_log

    def _save(self, action, entity_id):
        self.store.save(self.data)
        if self.event_log is not None:
            self.event_log.record(action, entity_type="research", entity_id=entity_id,
                                  details={"reference_only": True})

    @_locked
    def research(self, topic, *, online=False, language="ar", engine="wikipedia"):
        if not isinstance(topic, str) or not topic.strip() or len(topic) > 500:
            raise ValueError("Topic must contain 1–500 characters.")
        topic = topic.strip()
        if type(online) is not bool or language not in {"ar", "en"} or engine not in {"wikipedia", "web"}:
            raise ValueError("Invalid research mode, language, or engine.")
        sources, errors = [], []
        if self.knowledge_base is not None:
            sources.extend(dict(item, kind="local_document")
                           for item in self.knowledge_base.search(topic, limit=5))
        if online:
            try:
                provider = self.provider if engine == "wikipedia" else self.web_provider
                found = provider.search(topic, language=language, limit=5)
                if isinstance(found, dict):
                    sources.extend(found["sources"])
                    errors.extend(found.get("errors", []))
                else:
                    sources.extend(found)
            except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException) as error:
                errors.append(f"Online search failed ({type(error).__name__}); no fabricated results.")
        session_id = "research-" + uuid4().hex
        unique = {}
        for source in sources:
            key = (source["source"], source.get("page"), source["text"])
            if key not in unique:
                unique[key] = dict(source, source_id=f"S{len(unique) + 1}", retrieved_at=now())
        session = {
            "id": session_id, "topic": topic, "created_at": now(),
            "online": online, "engine": engine, "sources": list(unique.values()), "errors": errors,
            "status": "partial" if errors else ("ready_for_review" if unique else "no_results"),
            "findings": [], "applications": [],
        }
        self.data["sessions"][session_id] = session
        self._save("research_created", session_id)
        return deepcopy(session)

    @_locked
    def get(self, session_id):
        return deepcopy(self.data["sessions"][session_id])

    @_locked
    def list_sessions(self):
        return [deepcopy(s) for s in self.data["sessions"].values()]

    def research_needs(self, query, *, task_manager=None):
        """Identify review/search needs without sending a query over the network."""
        query = _text(query, "query", 500)
        approved = self.approved_knowledge(query)
        terms = _terms(query)
        sessions = [s for s in self.list_sessions() if terms & _terms(s["topic"])]
        needs = []
        if not approved:
            needs.append({"reason": "no_approved_relevant_knowledge", "suggested_query": query})
        for session in sessions:
            if session["errors"]:
                needs.append({"reason": "incomplete_research", "research_id": session["id"], "suggested_query": session["topic"]})
            for comparison in self._comparison(session):
                if comparison["state"] in {"conflicting", "needs_evidence"}:
                    needs.append({"reason": comparison["state"], "research_id": session["id"],
                                  "finding_id": comparison["finding_id"], "suggested_query": query})
        for finding in approved:
            if any(s["freshness"] == "review_age" for s in finding["sources"]):
                needs.append({"reason": "source_age_needs_review", "finding_id": finding["id"], "suggested_query": query})
        if task_manager is not None:
            for task in task_manager.list_tasks():
                if task.status in {"failed", "uncertain"} and terms & _terms(task.title + " " + task.description):
                    needs.append({"reason": "task_outcome_needs_investigation", "task_id": task.task_id,
                                  "suggested_query": task.title[:500]})
        return {"query": query, "approved_matches": len(approved), "needs": needs,
                "automatic_network_access": False}

    @_locked
    def propose(self, session_id, statement, source_ids, *, usefulness):
        session = self.data["sessions"][session_id]
        statement = _text(statement, "statement", 2000)
        usefulness = _text(usefulness, "usefulness", 2000)
        valid = {s["source_id"] for s in session["sources"]}
        if not isinstance(source_ids, list) or not source_ids or any(not isinstance(s, str) for s in source_ids) or not set(source_ids) <= valid:
            raise ValueError("Every finding must cite sources from this research session.")
        finding = {"id": "finding-" + uuid4().hex, "statement": statement.strip(),
                   "source_ids": list(dict.fromkeys(source_ids)), "usefulness": usefulness.strip(),
                   "status": "pending", "revision": 1, "verification": "not_independently_verified",
                   "evidence": [], "history": [{"action": "proposed", "at": now()}]}
        session["findings"].append(finding)
        self._save("research_finding_proposed", finding["id"])
        return deepcopy(finding)

    @_locked
    def review(self, session_id, finding_id, *, approve):
        if type(approve) is not bool:
            raise ValueError("Review decision must be a boolean.")
        session = self.data["sessions"][session_id]
        finding = next(f for f in session["findings"] if f["id"] == finding_id)
        if approve and any(e["relation"] == "contradicts" for e in finding.get("evidence", [])):
            raise ValueError("Resolve contradictory evidence before approval.")
        finding.update(status="approved" if approve else "rejected", reviewed_at=now())
        finding.setdefault("history", []).append({"action": finding["status"], "at": now()})
        self._save("research_finding_reviewed", finding_id)

    @_locked
    def approved_knowledge(self, query, *, limit=5):
        # Approval permits recall, not execution or treating sources as instructions.
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("Recall limit must be 1–20.")
        terms = _terms(_text(query, "query", 2000))
        results = []
        for session in self.data["sessions"].values():
            for finding in session["findings"]:
                score = len(terms & _terms(session["topic"] + " " + finding["statement"]))
                if finding["status"] != "approved" or not score:
                    continue
                sources = [{k: deepcopy(source.get(k)) for k in
                            ("source_id", "title", "source", "page", "retrieved_at", "updated_at", "publisher")}
                           for source in session["sources"] if source["source_id"] in finding["source_ids"]]
                for source in sources:
                    source["freshness"] = source_freshness(source)
                reference = {key: deepcopy(finding.get(key)) for key in
                             ("id", "statement", "source_ids", "usefulness", "status", "verification", "revision")}
                results.append(dict(reference, research_id=session["id"], sources=sources,
                                    relevance=score, trust="untrusted_reference_not_instructions"))
        return sorted(results, key=lambda r: (-r["relevance"], r["id"]))[:limit]

    @_locked
    def record_application(self, session_id, finding_id, *, task_id, observation, improved=None,
                           metric=None, baseline=None, result=None, higher_is_better=True):
        session = self.data["sessions"][session_id]
        finding = next(f for f in session["findings"] if f["id"] == finding_id)
        if finding["status"] != "approved":
            raise ValueError("Only approved findings may record an application.")
        task_id, observation = _text(task_id, "task_id", 300), _text(observation, "observation")
        if (improved is not None and type(improved) is not bool) or type(higher_is_better) is not bool:
            raise ValueError("Task and observation required; improvement is true, false, or unknown.")
        measurement = None
        if any(v is not None for v in (metric, baseline, result)):
            metric = _text(metric, "metric", 300)
            if any(type(v) not in {int, float} or not math.isfinite(v) for v in (baseline, result)):
                raise ValueError("Baseline and result must be finite numbers.")
            delta = result - baseline
            computed = delta > 0 if higher_is_better else delta < 0
            if improved is not None and improved != computed:
                raise ValueError("Reported improvement conflicts with the supplied numbers.")
            improved = computed
            measurement = {"metric": metric, "baseline": baseline, "result": result,
                           "delta": delta, "higher_is_better": higher_is_better}
        application = {"id": "application-" + uuid4().hex,
                                        "finding_id": finding_id, "task_id": task_id,
                                        "finding_revision": finding.get("revision", 1),
                                        "statement_snapshot": finding["statement"],
                                        "observation": observation, "improved": improved,
                                        "recorded_at": now(), "evidence_type": "user_reported",
                                        "measurement": measurement}
        session["applications"].append(application)
        self._save("research_application_recorded", application["id"])
        return deepcopy(application)

    def semantic_compare(self, session_id, analyzer, *, limit=5):
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError("Semantic analysis limit must be 1–10.")
        snapshot = self.get(session_id)
        analyses = []
        for finding in snapshot["findings"][:limit]:
            evidence = analyzer.analyze(finding["statement"], snapshot["sources"])
            analyses.append({"finding_id": finding["id"], "revision": finding.get("revision", 1),
                             "statement": finding["statement"], "evidence": evidence})
        return self._store_semantic(session_id, snapshot["sources"], analyses)

    @_locked
    def _store_semantic(self, session_id, source_snapshot, analyses):
        session = self.data["sessions"][session_id]
        if session["sources"] != source_snapshot:
            raise ValueError("Sources changed during semantic analysis; run it again.")
        findings = {f["id"]: f for f in session["findings"]}
        for analysis in analyses:
            finding = findings[analysis["finding_id"]]
            if finding.get("revision", 1) != analysis["revision"] or finding["statement"] != analysis["statement"]:
                raise ValueError("Claim changed during semantic analysis; run it again.")
        for analysis in analyses:
            finding = findings[analysis["finding_id"]]
            finding["evidence"] = [e for e in finding.get("evidence", []) if e.get("method") != "semantic_model"] + analysis["evidence"]
            for evidence in analysis["evidence"]:
                if evidence["source_id"] not in finding["source_ids"]:
                    finding["source_ids"].append(evidence["source_id"])
            if analysis["evidence"]:
                finding["status"] = "pending"
                finding.setdefault("history", []).append({"action": "semantic_analysis", "at": now()})
        self._save("research_semantically_analyzed", session_id)
        return deepcopy(analyses)

    @_locked
    def record_task_outcome(self, task, *, duration_seconds=None, task_manager=None):
        """Observe actual terminal task results; availability is not proof of use."""
        if task.status not in {"completed", "failed", "blocked", "uncertain"}:
            return []
        references = task.metadata.get("research_references", [])
        recorded = []
        for reference in references[:5]:
            session = self.data["sessions"].get(reference.get("research_id"))
            if session is None:
                continue
            finding = next((f for f in session["findings"] if f["id"] == reference.get("finding_id")), None)
            if finding is None or finding["status"] != "approved" or finding.get("revision", 1) != reference.get("revision"):
                continue
            if any(a["task_id"] == task.task_id and a.get("finding_revision", 1) == reference["revision"]
                   and a.get("evidence_type") == "observed_task_result" for a in session["applications"]):
                continue
            measurement, improved = None, None
            specification = task.metadata.get("research_measurement")
            if isinstance(specification, dict) and isinstance(task.result, dict) and task.status == "completed":
                metric, baseline = specification.get("metric"), None
                higher = specification.get("higher_is_better")
                baseline_task = task_manager.get_task(specification.get("baseline_task_id")) if task_manager is not None else None
                if (baseline_task is not None and baseline_task.task_id != task.task_id
                        and baseline_task.status == "completed" and isinstance(baseline_task.result, dict)
                        and baseline_task.project_id == task.project_id):
                    prior_metrics = baseline_task.result.get("metrics", {})
                    baseline = prior_metrics.get(metric) if isinstance(prior_metrics, dict) else None
                result = task.result.get("metrics", {}).get(metric) if isinstance(task.result.get("metrics"), dict) else None
                if (isinstance(metric, str) and type(higher) is bool
                        and all(type(v) in {int, float} and math.isfinite(v) for v in (baseline, result))):
                    delta = result - baseline
                    improved = delta > 0 if higher else delta < 0
                    measurement = {"metric": metric, "baseline": baseline, "result": result,
                                   "delta": delta, "higher_is_better": higher,
                                   "baseline_task_id": baseline_task.task_id, "baseline_origin": "observed_task_result"}
            application = {"id": "application-" + uuid4().hex, "finding_id": finding["id"],
                           "finding_revision": finding.get("revision", 1), "statement_snapshot": finding["statement"],
                           "task_id": task.task_id, "task_status": task.status,
                           "observation": "Automatically captured terminal task outcome.",
                           "evidence_type": "observed_task_result", "exposure": "available_during_planning_not_proven_used",
                           "improved": improved, "measurement": measurement, "recorded_at": now(),
                           "duration_seconds": duration_seconds,
                           "result_digest": sha256(str(task.result).encode("utf-8")).hexdigest()}
            session["applications"].append(application)
            recorded.append(deepcopy(application))
        if recorded:
            self._save("research_task_outcome_observed", task.task_id)
        return recorded

    @_locked
    def add_source(self, session_id, url):
        session = self.data["sessions"][session_id]
        if len(session["sources"]) >= 20:
            raise ValueError("A research session accepts at most 20 sources.")
        source = source_from_response(self.fetcher.fetch(url))
        existing = next((s for s in session["sources"] if s["source"] == source["source"]), None)
        if existing is not None:
            return deepcopy(existing)
        numbers = [int(s["source_id"][1:]) for s in session["sources"]]
        source.update(source_id=f"S{max(numbers, default=0) + 1}", retrieved_at=now())
        session["sources"].append(source)
        session["status"] = "partial" if session["errors"] else "ready_for_review"
        self._save("research_source_added", session_id)
        return deepcopy(source)

    @_locked
    def extract_candidates(self, session_id):
        """Extract relevant verbatim sentences, never invent a synthesized claim."""
        session = self.data["sessions"][session_id]
        existing = {f["statement"] for f in session["findings"]}
        terms = _terms(session["topic"])
        candidates = []
        for source in session["sources"]:
            if len(session["findings"]) >= 50:
                break
            sentences = re.split(r"(?<=[.!؟。])\s+|[\n\r]+", source["text"])
            ranked = sorted((s.strip() for s in sentences if 25 <= len(s.strip()) <= 1500),
                            key=lambda s: len(terms & _terms(s)), reverse=True)
            if not ranked or not terms & _terms(ranked[0]) or ranked[0] in existing:
                continue
            statement = ranked[0]
            finding = {"id": "finding-" + uuid4().hex, "statement": statement,
                       "source_ids": [source["source_id"]], "usefulness": "يحتاج تحديد تطبيق عملي عند المراجعة.",
                       "status": "pending", "revision": 1, "verification": "not_independently_verified",
                       "origin": "verbatim_extraction", "evidence": [{"source_id": source["source_id"],
                       "quote": statement, "relation": "supports", "method": "exact_excerpt"}],
                       "history": [{"action": "extracted", "at": now()}]}
            session["findings"].append(finding)
            candidates.append(deepcopy(finding))
            existing.add(statement)
        self._save("research_candidates_extracted", session_id)
        return candidates

    @_locked
    def add_evidence(self, session_id, finding_id, source_id, quote, *, relation):
        session = self.data["sessions"][session_id]
        finding = next(f for f in session["findings"] if f["id"] == finding_id)
        source = next(s for s in session["sources"] if s["source_id"] == source_id)
        quote = _text(quote, "quote", 2000)
        if relation not in {"supports", "contradicts", "unclear"}:
            raise ValueError("Evidence must support, contradict, or be unclear.")
        if " ".join(quote.split()) not in " ".join(source["text"].split()):
            raise ValueError("Evidence quote must exist verbatim in the cited source.")
        evidence = {"source_id": source_id, "quote": quote, "relation": relation,
                    "method": "user_classified", "at": now()}
        if source_id not in finding["source_ids"]:
            finding["source_ids"].append(source_id)
        finding.setdefault("evidence", []).append(evidence)
        finding["status"] = "pending"
        finding.setdefault("history", []).append({"action": "evidence_changed", "at": now()})
        self._save("research_evidence_added", finding_id)
        return deepcopy(evidence)

    @_locked
    def remove_evidence(self, session_id, finding_id, index):
        session = self.data["sessions"][session_id]
        finding = next(f for f in session["findings"] if f["id"] == finding_id)
        evidence = finding.get("evidence", [])
        if type(index) is not int or not 0 <= index < len(evidence):
            raise ValueError("Invalid evidence index.")
        removed = evidence.pop(index)
        finding["status"] = "pending"
        finding.setdefault("history", []).append({"action": "evidence_removed", "at": now(),
                                                  "removed": removed})
        self._save("research_evidence_removed", finding_id)

    @_locked
    def correct_finding(self, session_id, finding_id, *, statement, usefulness):
        session = self.data["sessions"][session_id]
        finding = next(f for f in session["findings"] if f["id"] == finding_id)
        statement, usefulness = _text(statement, "statement", 2000), _text(usefulness, "usefulness", 2000)
        finding.setdefault("history", []).append({"action": "corrected", "at": now(),
                                                  "previous_statement": finding["statement"]})
        finding.update(statement=statement, usefulness=usefulness, status="pending", evidence=[],
                       revision=finding.get("revision", 1) + 1)
        self._save("research_finding_corrected", finding_id)

    @staticmethod
    def _comparison(session):
        sources = {s["source_id"]: s for s in session["sources"]}
        comparisons = []
        for finding in session["findings"]:
            evidence = list(finding.get("evidence", []))
            # Exact matches can be detected; paraphrases/negation require review.
            for source in session["sources"]:
                if (finding["statement"] in source["text"]
                        and not any(e["source_id"] == source["source_id"] for e in evidence)):
                    evidence.append({"source_id": source["source_id"], "relation": "supports",
                                     "quote": finding["statement"], "method": "exact_match"})
            supporting = [sources[e["source_id"]] for e in evidence if e["relation"] == "supports"]
            groups = set()
            content_seen = set()
            for source in supporting:
                digest = sha256(source["text"].encode("utf-8")).hexdigest()
                if digest in content_seen:
                    continue
                content_seen.add(digest)
                publisher = source.get("publisher")
                if source.get("kind") == "encyclopedia":
                    publisher = "Wikipedia"
                if not publisher:
                    publisher = urlsplit(source["source"]).hostname or source["source"]
                # Subdomains and different Wikipedia languages aren't independent publishers.
                publisher = publisher.lower()
                if publisher.endswith(".wikipedia.org"):
                    publisher = "wikipedia"
                publisher = publisher.removeprefix("www.")
                if "." in publisher and "/" not in publisher:
                    publisher = ".".join(publisher.split(".")[-2:])
                groups.add(publisher)
            contradictions = [e for e in evidence if e["relation"] == "contradicts"]
            state = ("conflicting" if contradictions else
                     "multiple_publishers_support" if len(groups) >= 2 else
                     "single_publisher_support" if supporting else "needs_evidence")
            comparisons.append({"finding_id": finding["id"], "state": state,
                                "publisher_groups": sorted(groups), "evidence": evidence,
                                "independence": "publisher_estimate_not_proof",
                                "semantic_verification": ("model_assessed_requires_review" if
                                    any(e.get("method") == "semantic_model" for e in evidence) else "requires_human_review")})
        return comparisons

    @_locked
    def compare(self, session_id):
        return self._comparison(self.data["sessions"][session_id])

    @_locked
    def learning_summary(self, session_id):
        session = self.data["sessions"][session_id]
        applications = session["applications"]
        return {"findings": len(session["findings"]),
                "approved": sum(f["status"] == "approved" for f in session["findings"]),
                "applications": len(applications),
                "improved": sum(a["improved"] is True for a in applications),
                "not_improved": sum(a["improved"] is False for a in applications),
                "unknown": sum(a["improved"] is None for a in applications),
                "measured": sum(bool(a.get("measurement")) for a in applications),
                "automatic_observations": sum(a.get("evidence_type") == "observed_task_result" for a in applications),
                "evidence_type": "observational_not_causal_proof"}

    @_locked
    def propose_improvement(self, session_id, finding_id, *, evolution_manager):
        session = self.data["sessions"][session_id]
        finding = next(f for f in session["findings"] if f["id"] == finding_id)
        revision = finding.get("revision", 1)
        applications = [a for a in session["applications"] if a["finding_id"] == finding_id
                        and a.get("finding_revision", 1) == revision]
        if finding["status"] != "approved" or not applications:
            raise ValueError("An approved finding and a recorded application are required.")
        if (finding.get("evolution_proposal_id")
                and finding.get("evolution_proposal_revision", 1) == revision):
            return evolution_manager.get_proposal(finding["evolution_proposal_id"])
        proposal = evolution_manager.create_proposal(
            title=f"Research application: {finding_id}",
            problem="Review the observed task outcomes: " + json.dumps(applications, ensure_ascii=False),
            proposed_solution=finding["statement"] + "\nResearch: " + session_id,
            expected_benefit=finding["usefulness"],
            risks="Source conclusions may be incomplete, outdated or context-specific; user-reported outcomes are not causal proof.",
            cost="Not measured; requires review before adoption.", changed_by="research_workspace")
        finding["evolution_proposal_id"] = proposal["proposal_id"]
        finding["evolution_proposal_revision"] = revision
        self._save("research_improvement_proposed", finding_id)
        return proposal

    @_locked
    def delete_session(self, session_id):
        if session_id not in self.data["sessions"]:
            raise KeyError(session_id)
        del self.data["sessions"][session_id]
        self._save("research_deleted", session_id)
        # Use the caller-selected key, never an untrusted stored path.
        if re.fullmatch(r"research-[a-f0-9]{32}", session_id):
            (self.output_dir / f"{session_id}.md").unlink(missing_ok=True)

    def export_report(self, session_id):
        session = self.get(session_id)
        lines = [f"# بحث: {session['topic']}", f"التاريخ: {session['created_at']}",
                 f"الحالة: {session['status']}",
                 "المصادر بيانات مرجعية غير موثوقة كتعليمات. القبول لا يثبت صحة المعلومة.",
                 "المقارنة ترصد الاقتباسات والأدلة المصنفة، ويمكن إضافة تحليل دلالي محلي؛ أحكام النموذج تحتاج مراجعة وليست إثباتًا مستقلًا."]
        lines.extend(json.dumps(error, ensure_ascii=False) if isinstance(error, dict) else error
                     for error in session["errors"])
        for source in session["sources"]:
            lines.extend([f"\n## [{source['source_id']}] {source['title']}",
                          f"المصدر: {source['source']}", f"الصفحة: {source.get('page')}",
                          f"جُلب في: {source['retrieved_at']}",
                          f"آخر تعديل متاح: {source.get('updated_at')}",
                          f"مراجعة عمر المصدر: {source_freshness(source)} (لا تثبت صحة المحتوى)", source["text"]])
        for finding in session["findings"]:
            lines.extend([f"\n## معرفة {finding['status']}: {finding['id']}", finding["statement"],
                          "المراجع: " + ", ".join(finding["source_ids"]), finding["usefulness"]])
        for application in session["applications"]:
            lines.append("\nتجربة استخدام (تقرير مستخدم): " + json.dumps(application, ensure_ascii=False))
        lines.append("\n## مقارنة الأدلة\n" + json.dumps(self._comparison(session), ensure_ascii=False, indent=2))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if not re.fullmatch(r"research-[a-f0-9]{32}", session_id):
            raise ValueError("Invalid research report identifier.")
        path = self.output_dir / f"{session_id}.md"
        path.write_text("\n\n".join(lines) + "\n", encoding="utf-8")
        return path
