import { describe, expect, it } from "vitest";
import {
    NODE_KINDS,
    type NodeKind,
    type TopologyEdge,
    type TopologyNode,
} from "../src/contract";
import { buildModel } from "../src/model/graph-model";
import {
    SPACING,
    fitTransform,
    layoutModel,
    layoutTiered,
    visibleIds,
} from "../src/model/layout";
import { fixtureModel, fixtureSnapshot } from "./helpers";

const model = buildModel(fixtureSnapshot(), {
    kinds: new Set(NODE_KINDS),
    clients: "collapsed",
    toggledGroups: new Set(),
});

describe("layoutModel", () => {
    it("places every visual, one depth step per level", () => {
        const layout = layoutModel(model, "comfortable", "vertical");
        expect([...layout.positions.keys()].sort()).toEqual(
            [...model.visuals.keys()].sort(),
        );
        const depth = SPACING.comfortable.depth;
        expect(layout.positions.get("dev:uuid-gw")!.y).toBe(0);
        expect(layout.positions.get("dev:uuid-core")!.y).toBe(depth);
        expect(layout.positions.get("dev:uuid-ap")!.y).toBe(2 * depth);
        expect(layout.positions.get("group:dev:uuid-ap")!.y).toBe(3 * depth);
        const xs = model.children
            .get("dev:uuid-core")!
            .map((id) => layout.positions.get(id)!.x);
        expect(new Set(xs).size).toBe(xs.length);
    });

    it("swaps axes when horizontal and tightens when compact", () => {
        const horizontal = layoutModel(model, "compact", "horizontal");
        expect(horizontal.positions.get("dev:uuid-core")).toMatchObject({
            x: SPACING.compact.depth,
        });
        expect(horizontal.bounds.maxX).toBe(3 * SPACING.compact.depth);
    });

    it("handles an empty model", () => {
        const empty = buildModel(fixtureSnapshot({ nodes: [], edges: [] }), {
            kinds: new Set(NODE_KINDS),
            clients: "collapsed",
            toggledGroups: new Set(),
        });
        expect(
            layoutModel(empty, "comfortable", "vertical").positions.size,
        ).toBe(0);
    });
});

const device = (id: string, kind: NodeKind, name: string): TopologyNode => ({
    id: `dev:${id}`,
    kind,
    name,
    state: "online",
});
const client = (id: string, name: string): TopologyNode => ({
    id: `cli:${id}`,
    kind: "client",
    name,
    state: "online",
    connection: "wired",
});
/** `child` is plugged into `parent`; both are node ids. */
const uplink = (child: string, parent: string): TopologyEdge => ({
    source: child,
    target: parent,
    medium: "wired",
});
const modelOf = (
    nodes: TopologyNode[],
    edges: TopologyEdge[],
    ui: Parameters<typeof fixtureModel>[0] = {},
) => fixtureModel(ui, fixtureSnapshot({ nodes, edges }));

describe("layoutTiered", () => {
    const depth = SPACING.comfortable.depth;

    it("puts the fixture on rows by role, every edge crossing to a lower row", () => {
        const layout = layoutTiered(model, "comfortable", "vertical");
        expect([...layout.positions.keys()].sort()).toEqual(
            [...model.visuals.keys()].sort(),
        );
        const y = (id: string) => layout.positions.get(id)!.y;
        expect(y("dev:uuid-gw")).toBe(0);
        expect(y("dev:uuid-core")).toBe(depth);
        // Switches uplinked to the core switch share its tier: sub-row below it.
        for (const id of [
            "dev:uuid-flex",
            "dev:uuid-lite",
            "dev:uuid-pdu",
            "dev:uuid-u1",
            "dev:uuid-u2",
        ])
            expect(y(id)).toBe(2 * depth);
        expect(y("dev:uuid-ap")).toBe(3 * depth);
        expect(y("group:dev:uuid-ap")).toBe(4 * depth);
        expect(y("group:dev:uuid-u1")).toBe(4 * depth);
        expect(model.links.size).toBeGreaterThan(0);
        for (const link of model.links.values())
            expect(y(link.childId)).toBeGreaterThan(y(link.parentId));
    });

    it("orders the rows gateway, switch, access point, other, clients", () => {
        const layout = layoutTiered(
            modelOf(
                [
                    device("pdu", "other", "PDU"),
                    device("ap", "access_point", "AP"),
                    device("sw", "switch", "Switch"),
                    device("gw", "gateway", "Gateway"),
                    client("c", "Laptop"),
                    client("t", "Tablet"),
                ],
                [
                    uplink("dev:sw", "dev:gw"),
                    uplink("dev:ap", "dev:gw"),
                    uplink("dev:pdu", "dev:gw"),
                    uplink("cli:c", "dev:pdu"),
                    uplink("cli:t", "dev:sw"),
                ],
            ),
            "comfortable",
            "vertical",
        );
        const y = (id: string) => layout.positions.get(id)!.y;
        expect(
            ["dev:gw", "dev:sw", "dev:ap", "dev:pdu", "group:dev:pdu"].map(y),
        ).toEqual([0, depth, 2 * depth, 3 * depth, 4 * depth]);
        // A client group is on the client row wherever its parent is.
        expect(y("group:dev:sw")).toBe(4 * depth);
    });

    it("puts a child of the same or an earlier tier on a sub-row below its parent", () => {
        // gateway > AP > switch > AP > client group: the switch and the second
        // AP are not below the first AP's tier, so each steps one sub-row down
        // inside the access point tier. The client group starts the next row.
        const layout = layoutTiered(
            modelOf(
                [
                    device("gw", "gateway", "Gateway"),
                    device("core", "switch", "Core"),
                    device("ap1", "access_point", "AP 1"),
                    device("sw", "switch", "Mesh switch"),
                    device("ap2", "access_point", "AP 2"),
                    client("c", "Phone"),
                ],
                [
                    uplink("dev:core", "dev:gw"),
                    uplink("dev:ap1", "dev:gw"),
                    uplink("dev:sw", "dev:ap1"),
                    uplink("dev:ap2", "dev:sw"),
                    uplink("cli:c", "dev:ap2"),
                ],
            ),
            "comfortable",
            "vertical",
        );
        const y = (id: string) => layout.positions.get(id)!.y;
        expect(
            [
                "dev:gw",
                "dev:core",
                "dev:ap1",
                "dev:sw",
                "dev:ap2",
                "group:dev:ap2",
            ].map(y),
        ).toEqual([0, depth, 2 * depth, 3 * depth, 4 * depth, 5 * depth]);
    });

    it("puts expanded clients on a sub-row below their group", () => {
        const expanded = fixtureModel({ clients: "expanded" });
        const layout = layoutTiered(expanded, "comfortable", "vertical");
        const y = (id: string) => layout.positions.get(id)!.y;
        expect(y("group:dev:uuid-ap")).toBe(4 * depth);
        expect(y("cli:cli-phone")).toBe(5 * depth);
        expect(y("cli:cli-tv")).toBe(5 * depth);
        for (const link of expanded.links.values())
            expect(y(link.childId)).toBeGreaterThan(y(link.parentId));
    });

    it("skips tiers that have no nodes", () => {
        const noGateway = fixtureModel({
            kinds: new Set<NodeKind>(["switch", "access_point", "client"]),
        });
        const layout = layoutTiered(noGateway, "comfortable", "vertical");
        const y = (id: string) => layout.positions.get(id)!.y;
        expect(y("dev:uuid-core")).toBe(0);
        expect(y("dev:uuid-flex")).toBe(depth);
        expect(y("dev:uuid-ap")).toBe(2 * depth);
        expect(y("group:dev:uuid-ap")).toBe(3 * depth);
        expect(layout.bounds.maxY).toBe(3 * depth);
    });

    it("orders a row by the position of the parents, not by model order", () => {
        // Model order puts "Aaa"'s group (parent: Beta, x > 0) before "Bbb"'s
        // (parent: the AP under Alpha, x < 0); the layout must swap them so
        // the two edges do not cross.
        const layout = layoutTiered(
            modelOf(
                [
                    device("gw", "gateway", "Gateway"),
                    device("alpha", "switch", "Alpha"),
                    device("beta", "switch", "Beta"),
                    device("ap", "access_point", "AP"),
                    client("a", "Aaa"),
                    client("b", "Bbb"),
                ],
                [
                    uplink("dev:alpha", "dev:gw"),
                    uplink("dev:beta", "dev:gw"),
                    uplink("dev:ap", "dev:alpha"),
                    uplink("cli:a", "dev:beta"),
                    uplink("cli:b", "dev:ap"),
                ],
            ),
            "comfortable",
            "vertical",
        );
        const x = (id: string) => layout.positions.get(id)!.x;
        expect(x("dev:alpha")).toBeLessThan(x("dev:beta"));
        expect(x("group:dev:ap")).toBeLessThan(x("group:dev:beta"));
    });

    it("puts a node without a parent after the others in its row", () => {
        const snapshot = fixtureSnapshot();
        snapshot.nodes.push(client("orphan", "Orphan"));
        const layout = layoutTiered(
            fixtureModel({}, snapshot),
            "comfortable",
            "vertical",
        );
        const at = (id: string) => layout.positions.get(id)!;
        expect(at("group:unconnected").y).toBe(at("group:dev:uuid-ap").y);
        expect(at("group:unconnected").x).toBeGreaterThan(
            at("group:dev:uuid-u1").x,
        );
        expect(at("group:dev:uuid-ap").x).toBeLessThan(
            at("group:dev:uuid-u1").x,
        );
    });

    it("spreads siblings one breadth apart", () => {
        const layout = layoutTiered(model, "comfortable", "vertical");
        const row = [
            "dev:uuid-flex",
            "dev:uuid-lite",
            "dev:uuid-pdu",
            "dev:uuid-u1",
            "dev:uuid-u2",
        ].map((id) => layout.positions.get(id)!.x);
        const breadth = SPACING.comfortable.breadth;
        expect(row).toEqual([-2, -1, 0, 1, 2].map((i) => i * breadth));
    });

    it("swaps axes when horizontal", () => {
        const vertical = layoutTiered(model, "comfortable", "vertical");
        const horizontal = layoutTiered(model, "comfortable", "horizontal");
        for (const [id, p] of vertical.positions)
            expect(horizontal.positions.get(id)).toEqual({ x: p.y, y: p.x });
        expect(horizontal.bounds).toEqual({
            minX: vertical.bounds.minY,
            minY: vertical.bounds.minX,
            maxX: vertical.bounds.maxY,
            maxY: vertical.bounds.maxX,
        });
    });

    it("tightens rows and siblings when compact", () => {
        const compact = layoutTiered(model, "compact", "vertical");
        const at = (id: string) => compact.positions.get(id)!;
        expect(at("dev:uuid-core").y).toBe(SPACING.compact.depth);
        expect(at("group:dev:uuid-ap").y).toBe(4 * SPACING.compact.depth);
        expect(at("dev:uuid-lite").x - at("dev:uuid-flex").x).toBe(
            SPACING.compact.breadth,
        );
        const xs = [...compact.positions.values()].map((p) => p.x);
        const ys = [...compact.positions.values()].map((p) => p.y);
        expect(compact.bounds).toEqual({
            minX: Math.min(...xs),
            minY: Math.min(...ys),
            maxX: Math.max(...xs),
            maxY: Math.max(...ys),
        });
    });

    it("handles an empty model", () => {
        const empty = buildModel(fixtureSnapshot({ nodes: [], edges: [] }), {
            kinds: new Set(NODE_KINDS),
            clients: "collapsed",
            toggledGroups: new Set(),
        });
        const layout = layoutTiered(empty, "comfortable", "vertical");
        expect(layout.positions.size).toBe(0);
        expect(layout.bounds).toEqual({ minX: 0, minY: 0, maxX: 0, maxY: 0 });
    });
});

describe("viewport maths", () => {
    it("fits and centres the bounds, clamped to 1.5×", () => {
        expect(
            fitTransform({ minX: 0, minY: 0, maxX: 100, maxY: 100 }, 400, 300),
        ).toEqual({ k: 1.5, x: 125, y: 75 });
        const wide = fitTransform(
            { minX: 0, minY: 0, maxX: 10000, maxY: 100 },
            400,
            300,
        );
        expect(wide.k).toBe(0.2);
    });

    it("culls positions outside the viewport plus margin", () => {
        const layout = {
            positions: new Map([
                ["in", { x: 10, y: 10 }],
                ["out", { x: 5000, y: 10 }],
            ]),
            bounds: { minX: 10, minY: 10, maxX: 5000, maxY: 10 },
        };
        expect([...visibleIds(layout, { x: 0, y: 0, k: 1 }, 800, 600)]).toEqual(
            ["in"],
        );
    });
});
