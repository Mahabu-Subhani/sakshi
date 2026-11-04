"""Investigation summary.

Default: deterministic template text built only from findings. Optional: an LLM
(Gemini or Claude, via environment variables) may rewrite the summary in plainer
prose. It receives only the structured findings, is told not to add facts, and
its output is labelled as AI-written. The LLM never decides tiers, never sees
raw documents, and is never required for the pipeline to work.

  SAKSHI_LLM=gemini  GEMINI_API_KEY=...      (generativelanguage.googleapis.com)
  SAKSHI_LLM=claude  ANTHROPIC_API_KEY=...   (api.anthropic.com)
"""
from __future__ import annotations

import json
import os
import urllib.request

from ..models import Tier


def deterministic(findings, threads, docs) -> str:
    pm = [f for f in findings if f.tier == Tier.POTENTIAL_MANIPULATION]
    inc = [f for f in findings if f.tier == Tier.INCONSISTENCY]
    obs = [f for f in findings if f.tier == Tier.OBSERVATION]
    lines = [f"{len(docs)} documents analysed. {len(pm)} potential manipulation finding(s), {len(inc)} inconsistencies, "
             f"{len(obs)} observations. {len(threads)} investigation thread(s)."]
    if not pm and not inc:
        lines.append("No rule-breaking inconsistency or corroborated anomaly was found. This is not proof of authenticity; "
                     "see the coverage map for what could and could not be verified.")
    for t in threads[:5]:
        rec = f" Consistent value recovered: {t['recovered']:,.2f}." if isinstance(t.get("recovered"), float) else (
            f" Value recovered from the file: {t['recovered']}." if t.get("recovered") else "")
        lines.append(f"[{t['tier'].replace('_', ' ').title()}] {t['title']} ({len(t['findings'])} linked finding(s), "
                     f"evidence families: {', '.join(t['families'])}).{rec}")
    lines.append("All findings are leads for a human analyst. None is a fraud determination.")
    return "\n".join(lines)


def llm(summary: str, findings) -> tuple[str, str] | None:
    mode = os.environ.get("SAKSHI_LLM", "").lower()
    facts = json.dumps([{"tier": f.tier.value, "title": f.title, "benign": [b.result for b in f.benign]}
                        for f in findings if f.tier != Tier.OBSERVATION][:20])
    prompt = ("Rewrite this document-investigation summary for a bank credit analyst in 5 short plain-English sentences. "
              "Use ONLY the facts given. Do not add facts, do not use the word fraud, keep every tier label as given.\n\n"
              f"SUMMARY:\n{summary}\n\nFINDINGS JSON:\n{facts}")
    try:
        if mode == "gemini" and os.environ.get("GEMINI_API_KEY"):
            url = ("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key="
                   + os.environ["GEMINI_API_KEY"])
            body = {"contents": [{"parts": [{"text": prompt}]}]}
            req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
            r = json.loads(urllib.request.urlopen(req, timeout=40).read())
            return r["candidates"][0]["content"]["parts"][0]["text"], "gemini-2.5-flash"
        if mode == "claude" and os.environ.get("ANTHROPIC_API_KEY"):
            body = {"model": os.environ.get("SAKSHI_CLAUDE_MODEL", "claude-sonnet-5-5"), "max_tokens": 600,
                    "messages": [{"role": "user", "content": prompt}]}
            req = urllib.request.Request("https://api.anthropic.com/v1/messages", json.dumps(body).encode(),
                                         {"Content-Type": "application/json", "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                                          "anthropic-version": "2023-06-01"})
            r = json.loads(urllib.request.urlopen(req, timeout=40).read())
            return r["content"][0]["text"], body["model"]
    except Exception as e:
        return None
    return None
