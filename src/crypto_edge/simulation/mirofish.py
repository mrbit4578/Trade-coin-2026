"""
MiroFish-inspired force-graph context + multi-agent reaction simulation.

MiroFish (github.com/666ghj/MiroFish) is a swarm intelligence / social
simulation engine with force-directed knowledge graphs. This module embeds a
lightweight local equivalent tailored for crypto markets so the agent can run
offline without GPU/cloud:

1. Build a force-graph of entities (spot, venues, OTC, structure, Polymarket)
2. Propagate influence (PageRank-like + spring layout energy)
3. Spawn N agent personas and simulate reactions → consensus probability
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import networkx as nx
import numpy as np

from crypto_edge.models import OrderBookSnapshot, OTCFlow, StructureSignal


@dataclass
class GraphContext:
    nodes: dict[str, dict[str, Any]]
    edges: list[tuple[str, str, float]]
    consensus: float
    energy: float
    agent_votes: list[float]


class MiroFishGraph:
    def __init__(self, n_agents: int = 200, seed: int | None = None) -> None:
        self.n_agents = n_agents
        self.rng = np.random.default_rng(seed)

    def build(
        self,
        symbol: str,
        spot: float,
        books: dict[str, OrderBookSnapshot],
        otc: list[OTCFlow],
        structure: Optional[StructureSignal],
        poly_yes: float,
        mc_p_up: float,
    ) -> GraphContext:
        G = nx.Graph()
        G.add_node("spot", kind="price", value=spot, bias=0.0)
        G.add_node("mc", kind="sim", value=mc_p_up, bias=mc_p_up - 0.5)
        G.add_node("poly", kind="market", value=poly_yes, bias=poly_yes - 0.5)

        for ex, book in books.items():
            imb = book.imbalance()
            G.add_node(f"ob:{ex}", kind="orderbook", value=book.mid, bias=imb)
            G.add_edge("spot", f"ob:{ex}", weight=1.0 + abs(imb))

        if structure:
            G.add_node(
                "smc",
                kind="structure",
                value=structure.score,
                bias=structure.score,
            )
            G.add_edge("spot", "smc", weight=1.2)
            G.add_edge("mc", "smc", weight=0.8)

        for i, f in enumerate(otc[:10]):
            bias = 0.3 if f.side.value == "BUY" else -0.3
            nid = f"otc:{i}"
            G.add_node(nid, kind="otc", value=f.notional_usd, bias=bias)
            G.add_edge("spot", nid, weight=min(2.0, f.notional_usd / 1_000_000))

        G.add_edge("mc", "poly", weight=1.5)
        G.add_edge("spot", "poly", weight=1.0)
        G.add_edge("spot", "mc", weight=1.3)

        # Influence = weighted average of neighbor biases
        influence = {}
        for n in G.nodes:
            bias = G.nodes[n].get("bias", 0.0)
            neigh = list(G.neighbors(n))
            if not neigh:
                influence[n] = bias
                continue
            wsum = 0.0
            acc = bias
            for nb in neigh:
                w = G.edges[n, nb].get("weight", 1.0)
                acc += G.nodes[nb].get("bias", 0.0) * w
                wsum += w
            influence[n] = acc / (1 + wsum)

        # Force-layout energy proxy (spring tension)
        try:
            pos = nx.spring_layout(G, weight="weight", seed=42, iterations=50)
            energy = 0.0
            for u, v, d in G.edges(data=True):
                dx = pos[u][0] - pos[v][0]
                dy = pos[u][1] - pos[v][1]
                dist = (dx * dx + dy * dy) ** 0.5
                energy += abs(dist - 1.0 / d.get("weight", 1.0))
        except Exception:
            energy = 0.0

        # Multi-agent swarm votes
        base = 0.5 + influence.get("mc", 0.0) * 0.5 + influence.get("smc", 0.0) * 0.2
        base += influence.get("poly", 0.0) * -0.15  # fade crowded poly a bit
        otc_nodes = [influence[n] for n in G.nodes if str(n).startswith("otc:")]
        if otc_nodes:
            base += float(np.mean(otc_nodes)) * 0.15

        personas = self.rng.normal(0, 0.12, size=self.n_agents)
        # herding toward graph consensus
        votes = 1 / (1 + np.exp(-(base - 0.5 + personas) * 6))
        # 10% contrarians
        contrarian = self.rng.random(self.n_agents) < 0.1
        votes = np.where(contrarian, 1 - votes, votes)
        consensus = float(np.clip(votes.mean(), 0.03, 0.97))

        nodes = {n: dict(G.nodes[n]) | {"influence": influence.get(n, 0.0)} for n in G.nodes}
        edges = [(u, v, float(d.get("weight", 1.0))) for u, v, d in G.edges(data=True)]
        return GraphContext(
            nodes=nodes,
            edges=edges,
            consensus=consensus,
            energy=float(energy),
            agent_votes=votes.tolist(),
        )

    def blend_with_mc(self, mc_p_up: float, graph: GraphContext, weight: float = 0.35) -> float:
        """Blend Monte Carlo p_up with MiroFish swarm consensus."""
        return float(np.clip((1 - weight) * mc_p_up + weight * graph.consensus, 0.03, 0.97))
