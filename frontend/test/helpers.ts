import fixture from "./fixtures/site-topology.json";
import type { SiteTopology, TopologySource } from "../src/contract";

/** A fresh deep copy of the Python-generated snapshot, with optional overrides. */
export function fixtureSnapshot(
    overrides: Partial<SiteTopology> = {},
): SiteTopology {
    const copy = JSON.parse(JSON.stringify(fixture)) as SiteTopology;
    return { ...copy, ...overrides };
}

/** What the backend pushes for entry_unloaded / site_unavailable. */
export function unavailableSnapshot(code: string): SiteTopology {
    return fixtureSnapshot({
        revision: "",
        status: "unavailable",
        issues: [{ code, severity: "error" }],
        nodes: [],
        edges: [],
        unresolved: [],
        truncation: null,
    });
}

export const SOURCES_ONE: TopologySource[] = [
    {
        entry_id: "entry-1",
        title: "Crestwood",
        sites: [{ id: "site-1", name: "Home" }],
    },
];

export const SOURCES_MULTI: TopologySource[] = [
    {
        entry_id: "entry-1",
        title: "Crestwood",
        sites: [
            { id: "site-1", name: "Home" },
            { id: "site-2", name: "Cabin" },
        ],
    },
    {
        entry_id: "entry-2",
        title: "Office",
        sites: [{ id: "default", name: "Default" }],
    },
];
