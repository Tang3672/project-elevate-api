"""ModelStore — async persistence for MarketModel versions.

Wraps the existing market_model_repository but serialises/deserialises full
Node graphs rather than flat lo/hi dicts.

The store is thin by design: it does not recompute, it does not validate.
All invariants live in MarketModel.__post_init__.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from app.model.market_model import MarketModel

logger = logging.getLogger(__name__)


@dataclass
class VersionSummary:
    version: int
    parent_version: Optional[int]
    created_at: str
    created_by: str
    change_note: str
    model_hash: str


class ModelStore:
    """Async store for MarketModel versions backed by market_model_versions table."""

    async def save(self, m: MarketModel) -> None:
        from app.db.market_model_repository import save_baseline, save_edit
        nodes_json = {nid: n.to_dict() for nid, n in m.nodes.items()}

        if m.version == 1 and m.parent_version is None:
            await save_baseline(m.report_id, {
                "_schema": "v9_node_graph",
                "model_id": m.id,
                "nodes": nodes_json,
                "created_at": m.created_at,
                "created_by": m.created_by,
                "change_note": m.change_note,
                "model_hash": m.model_hash(),
            })
        else:
            await save_edit(
                report_id=m.report_id,
                parent_version=m.parent_version or 1,
                nodes={
                    "_schema": "v9_node_graph",
                    "model_id": m.id,
                    "nodes": nodes_json,
                    "created_at": m.created_at,
                    "created_by": m.created_by,
                    "change_note": m.change_note,
                    "model_hash": m.model_hash(),
                },
                rationale=m.change_note,
                user_id=None,
            )

    async def load(self, report_id: str, version: Optional[int] = None) -> Optional[MarketModel]:
        from app.db.market_model_repository import get_version, get_latest
        row = await (get_version(report_id, version) if version else get_latest(report_id))
        if row is None:
            return None
        return self._from_row(row, report_id)

    async def latest(self, report_id: str) -> Optional[MarketModel]:
        return await self.load(report_id)

    async def versions(self, report_id: str) -> list[VersionSummary]:
        from app.db.market_model_repository import list_versions
        rows = await list_versions(report_id)
        out = []
        for r in rows:
            nodes = r.get("nodes") or {}
            out.append(VersionSummary(
                version=r["version"],
                parent_version=r.get("parent_version"),
                created_at=str(r.get("created_at", "")),
                created_by=nodes.get("created_by", "engine") if isinstance(nodes, dict) else "engine",
                change_note=nodes.get("change_note", "") if isinstance(nodes, dict) else "",
                model_hash=nodes.get("model_hash", "") if isinstance(nodes, dict) else "",
            ))
        return out

    def _from_row(self, row: dict, report_id: str) -> Optional[MarketModel]:
        nodes_blob = row.get("nodes") or {}
        # v9 node graph
        if isinstance(nodes_blob, dict) and nodes_blob.get("_schema") == "v9_node_graph":
            raw_nodes = nodes_blob["nodes"]
            from app.model.nodes import Node
            nodes = {nid: Node.from_dict(nd) for nid, nd in raw_nodes.items()}
            return MarketModel(
                id=nodes_blob.get("model_id", f"mm_{row.get('id', 'legacy')}"),
                report_id=report_id,
                version=row["version"],
                parent_version=row.get("parent_version"),
                nodes=nodes,
                created_at=nodes_blob.get("created_at", str(row.get("created_at", ""))),
                created_by=nodes_blob.get("created_by", "engine"),
                change_note=nodes_blob.get("change_note", ""),
            )
        # legacy flat-dict — convert via extract adapter
        from app.model.extract import extract_model_from_flat
        return extract_model_from_flat(nodes_blob, report_id, row["version"])
