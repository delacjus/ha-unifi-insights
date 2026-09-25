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

import { NODE_KINDS as ALL_KINDS } from "../src/contract";
import {
    buildModel,
    type GraphModel,
    type UiState,
} from "../src/model/graph-model";

export function fixtureModel(
    ui: Partial<UiState> = {},
    snapshot: SiteTopology = fixtureSnapshot(),
): GraphModel {
    return buildModel(snapshot, {
        kinds: new Set(ALL_KINDS),
        clients: "collapsed",
        toggledGroups: new Set(),
        ...ui,
    });
}

export async function mount<T extends HTMLElement>(
    tag: string,
    props: Record<string, unknown> = {},
): Promise<T> {
    const el = document.createElement(tag) as T & {
        updateComplete: Promise<boolean>;
    };
    Object.assign(el, props);
    document.body.append(el);
    await el.updateComplete;
    return el;
}

export function cleanup(): void {
    document.body.replaceChildren();
    history.replaceState(null, "", "/");
}
