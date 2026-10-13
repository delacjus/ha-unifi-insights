import { hierarchy, tree } from "d3-hierarchy";
import type { Density, Orientation } from "../config";
import type { NodeKind } from "../contract";
import type { GraphModel, Visual } from "./graph-model";

export interface Point {
    x: number;
    y: number;
}

export interface Bounds {
    minX: number;
    minY: number;
    maxX: number;
    maxY: number;
}

export interface Layout {
    positions: Map<string, Point>;
    bounds: Bounds;
}

export interface ViewTransform {
    x: number;
    y: number;
    k: number;
}

/** Distance between siblings (`breadth`) and between levels (`depth`), in SVG units. */
export const SPACING: Record<Density, { breadth: number; depth: number }> = {
    comfortable: { breadth: 132, depth: 150 },
    compact: { breadth: 92, depth: 112 },
};

/** Above this many visible nodes only those near the viewport are put in the DOM. */
export const CULL_THRESHOLD = 300;

const SUPER_ROOT = "\u0000root";

const emptyLayout = (): Layout => ({
    positions: new Map(),
    bounds: { minX: 0, minY: 0, maxX: 0, maxY: 0 },
});

/** The layout axes are `along` a level and `down` through the levels; horizontal swaps them. */
const toPoint = (
    along: number,
    down: number,
    orientation: Orientation,
): Point =>
    orientation === "vertical" ? { x: along, y: down } : { x: down, y: along };

/** Layout from positions, with the bounds that enclose them. */
function layoutOf(positions: Map<string, Point>): Layout {
    const bounds: Bounds = {
        minX: Infinity,
        minY: Infinity,
        maxX: -Infinity,
        maxY: -Infinity,
    };
    for (const p of positions.values()) {
        bounds.minX = Math.min(bounds.minX, p.x);
        bounds.minY = Math.min(bounds.minY, p.y);
        bounds.maxX = Math.max(bounds.maxX, p.x);
        bounds.maxY = Math.max(bounds.maxY, p.y);
    }
    return { positions, bounds };
}

/** Tidy-tree layout of the model; a synthetic super-root turns the forest into one tree. */
export function layoutModel(
    model: GraphModel,
    density: Density,
    orientation: Orientation,
): Layout {
    if (model.roots.length === 0) return emptyLayout();
    const { breadth, depth } = SPACING[density];
    const root = hierarchy<string>(SUPER_ROOT, (id) =>
        id === SUPER_ROOT ? model.roots : model.children.get(id),
    );
    const laidOut = tree<string>()
        .nodeSize([breadth, depth])
        .separation((a, b) => (a.parent === b.parent ? 1 : 1.25))(root);
    const positions = new Map<string, Point>();
    for (const n of laidOut.descendants()) {
        if (n.data === SUPER_ROOT) continue;
        positions.set(n.data, toPoint(n.x, (n.depth - 1) * depth, orientation));
    }
    return layoutOf(positions);
}

/** Tier of each node kind, top row first; client groups share the clients' tier. */
const TIER: Record<NodeKind, number> = {
    gateway: 0,
    switch: 1,
    access_point: 2,
    other: 3,
    client: 4,
};
const TIER_COUNT = TIER.client + 1;
const tierOf = (visual: Visual): number =>
    visual.type === "group" ? TIER.client : TIER[visual.node.kind];

/**
 * Tiered layout: rows follow the device role (gateway, switches, access
 * points, other infrastructure, client groups and clients).
 *
 * A child goes in the row of its own tier when that is below its parent's
 * row. Otherwise (same tier as the parent, or a tier above it, e.g. a switch
 * behind an access point) it goes on a sub-row directly below the parent's
 * row, inside the parent's tier. So every edge runs to a lower row. Tiers
 * without nodes take no space. Inside a row, nodes sit in the order of their
 * parents' positions along the row, which keeps the edges from crossing.
 */
export function layoutTiered(
    model: GraphModel,
    density: Density,
    orientation: Orientation,
): Layout {
    if (model.roots.length === 0) return emptyLayout();
    const { breadth, depth } = SPACING[density];

    // Breadth-first, so a parent has its slot before any of its children.
    const slots = new Map<string, { tier: number; sub: number }>();
    const queue = [...model.roots];
    const subRows = new Array<number>(TIER_COUNT).fill(0);
    for (const id of queue) {
        const tier = tierOf(model.visuals.get(id)!);
        const parent = model.parentOf.get(id);
        const above = parent === undefined ? undefined : slots.get(parent)!;
        const slot =
            above === undefined || tier > above.tier
                ? { tier, sub: 0 }
                : { tier: above.tier, sub: above.sub + 1 };
        slots.set(id, slot);
        subRows[slot.tier] = Math.max(subRows[slot.tier]!, slot.sub + 1);
        queue.push(...(model.children.get(id) ?? []));
    }

    const firstRow: number[] = [];
    let rowCount = 0;
    for (const count of subRows) {
        firstRow.push(rowCount);
        rowCount += count;
    }
    const rows: string[][] = Array.from({ length: rowCount }, () => []);
    for (const id of queue) {
        const { tier, sub } = slots.get(id)!;
        rows[firstRow[tier]! + sub]!.push(id);
    }

    // Top to bottom: every parent is in an earlier row, so its place is known.
    const along = new Map<string, number>();
    const positions = new Map<string, Point>();
    rows.forEach((ids, row) => {
        const keyed = ids.map((id) => {
            const parent = model.parentOf.get(id);
            return {
                id,
                key: parent === undefined ? Infinity : along.get(parent)!,
            };
        });
        // Array.prototype.sort is stable: siblings keep their model order.
        keyed.sort((a, b) => (a.key === b.key ? 0 : a.key < b.key ? -1 : 1));
        keyed.forEach(({ id }, i) => {
            const offset = (i - (keyed.length - 1) / 2) * breadth;
            along.set(id, offset);
            positions.set(id, toPoint(offset, row * depth, orientation));
        });
    });
    return layoutOf(positions);
}

/** Transform that centres `bounds` in the viewport, scaled into [0.2, 1.5]. */
export function fitTransform(
    bounds: Bounds,
    width: number,
    height: number,
    padding = 48,
): ViewTransform {
    const w = Math.max(bounds.maxX - bounds.minX, 1);
    const h = Math.max(bounds.maxY - bounds.minY, 1);
    const k = Math.min(
        1.5,
        Math.max(
            0.2,
            Math.min((width - 2 * padding) / w, (height - 2 * padding) / h),
        ),
    );
    const cx = (bounds.minX + bounds.maxX) / 2;
    const cy = (bounds.minY + bounds.maxY) / 2;
    return { k, x: width / 2 - cx * k, y: height / 2 - cy * k };
}

/** Ids whose screen position falls inside the viewport grown by `margin` px. */
export function visibleIds(
    layout: Layout,
    t: ViewTransform,
    width: number,
    height: number,
    margin = 120,
): Set<string> {
    const out = new Set<string>();
    for (const [id, p] of layout.positions) {
        const sx = p.x * t.k + t.x;
        const sy = p.y * t.k + t.y;
        if (
            sx >= -margin &&
            sx <= width + margin &&
            sy >= -margin &&
            sy <= height + margin
        )
            out.add(id);
    }
    return out;
}
