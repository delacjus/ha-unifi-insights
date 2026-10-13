import { afterEach, describe, expect, it, vi } from "vitest";
import { makeLocalize } from "../src/localize";
import { describeVisual } from "../src/views/describe";
import { SPACING, layoutModel, layoutTiered } from "../src/model/layout";
import { zoomFilter, type UitGraphView } from "../src/views/graph-view";
import { cleanup, fixtureModel, fixtureSnapshot, mount } from "./helpers";

const localize = makeLocalize("en");
afterEach(cleanup);

async function graph(
  props: Record<string, unknown> = {},
): Promise<UitGraphView> {
  const el = await mount<UitGraphView>("uit-graph-view", {
    model: fixtureModel(),
    localize,
    siteName: "Home",
    reducedMotion: true,
    ...props,
  });
  el.setViewportSize(800, 600);
  await el.updateComplete;
  return el;
}
const nodes = (el: UitGraphView) => [
  ...el.shadowRoot!.querySelectorAll<SVGGElement>("g.nodes g.node"),
];
const byId = (el: UitGraphView, id: string) =>
  nodes(el).find((n) => n.getAttribute("data-id") === id)!;
const svgOf = (el: UitGraphView) => el.shadowRoot!.querySelector("svg.canvas")!;

describe("<uit-graph-view> rendering", () => {
  it("draws every visual and link, labelled for assistive tech", async () => {
    const el = await graph();
    const model = fixtureModel();
    expect(nodes(el)).toHaveLength(model.visuals.size);
    expect(el.shadowRoot!.querySelectorAll("g.links path.link")).toHaveLength(
      model.links.size,
    );
    const svg = svgOf(el);
    expect(svg.getAttribute("role")).toBe("application");
    expect(svg.getAttribute("aria-roledescription")).toBe("network topology");
    expect(svg.getAttribute("aria-label")).toBe(
      "Home topology, 8 devices, 2 clients",
    );
    expect(byId(el, "dev:uuid-core").getAttribute("aria-label")).toBe(
      describeVisual(model, model.visuals.get("dev:uuid-core")!, localize),
    );
    expect(byId(el, "group:dev:uuid-ap").getAttribute("aria-expanded")).toBe(
      "false",
    );
    expect(
      nodes(el)
        .filter((n) => n.getAttribute("tabindex") === "0")
        .map((n) => n.getAttribute("data-id")),
    ).toEqual(["dev:uuid-gw"]);
  });

  it("labels links with port, speed and PoE, and can hide labels", async () => {
    const el = await graph();
    const labels = [...el.shadowRoot!.querySelectorAll("text.link-label")].map(
      (t) => t.textContent,
    );
    expect(labels).toContain("p20 · 2.5G · PoE");
    const bare = await graph({ showLabels: false });
    expect(
      bare.shadowRoot!.querySelector("text.label, text.link-label"),
    ).toBeNull();
  });

  it("renders hostile names as text", async () => {
    const snapshot = fixtureSnapshot();
    snapshot.nodes.find((n) => n.id === "dev:uuid-gw")!.name =
      "<img src=x onerror=alert(1)> and a very long gateway name";
    const el = await graph({ model: fixtureModel({}, snapshot) });
    const gw = byId(el, "dev:uuid-gw");
    expect(el.shadowRoot!.querySelector("img")).toBeNull();
    expect(gw.querySelector("title")!.textContent).toBe(
      "<img src=x onerror=alert(1)> and a very long gateway name",
    );
    expect(gw.querySelector("text.label")!.textContent).toMatch(/…$/);
  });

  it("highlights the path from the selection to the root, via a collapsed client group", async () => {
    const el = await graph({ selectedId: "cli:cli-tv" });
    const onPath = nodes(el)
      .filter((n) => n.classList.contains("on-path"))
      .map((n) => n.getAttribute("data-id"));
    expect(onPath).toEqual([
      "dev:uuid-gw",
      "dev:uuid-core",
      "dev:uuid-u1",
      "group:dev:uuid-u1",
    ]);
  });

  it("marks offline nodes with text, not colour alone", async () => {
    const snapshot = fixtureSnapshot();
    snapshot.nodes.find((n) => n.id === "dev:uuid-pdu")!.state = "offline";
    const el = await graph({ model: fixtureModel({}, snapshot) });
    expect(
      byId(el, "dev:uuid-pdu").querySelector("text.state-text")!.textContent,
    ).toBe("Offline");
  });
});

describe("<uit-graph-view> interaction", () => {
  it("moves focus along the tree with arrows and activates with Enter or click", async () => {
    const el = await graph();
    const activated = vi.fn();
    el.addEventListener("uit-activate", (e) =>
      activated((e as CustomEvent).detail),
    );
    byId(el, "dev:uuid-gw").focus();
    svgOf(el).dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }),
    );
    await el.updateComplete;
    await el.updateComplete;
    expect(el.shadowRoot!.activeElement?.getAttribute("data-id")).toBe(
      "dev:uuid-core",
    );
    svgOf(el).dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
    );
    byId(el, "dev:uuid-ap").dispatchEvent(
      new MouseEvent("click", { bubbles: true }),
    );
    expect(activated.mock.calls).toEqual([
      [{ id: "dev:uuid-core" }],
      [{ id: "dev:uuid-ap" }],
    ]);
  });

  it("fits on first size and zooms with the keyboard", async () => {
    const el = await graph();
    const viewport = () =>
      el.shadowRoot!.querySelector("g.viewport")!.getAttribute("transform");
    const fitted = viewport();
    expect(fitted).not.toBe("translate(0,0) scale(1)");
    svgOf(el).dispatchEvent(
      new KeyboardEvent("keydown", { key: "+", bubbles: true }),
    );
    expect(viewport()).not.toBe(fitted);
    svgOf(el).dispatchEvent(
      new KeyboardEvent("keydown", { key: "0", bubbles: true }),
    );
    expect(viewport()).toBe(fitted);
  });

  it("shows a hint instead of hijacking plain wheel scrolling in dashboards", async () => {
    const el = await graph();
    svgOf(el).dispatchEvent(
      new WheelEvent("wheel", {
        deltaY: 100,
        bubbles: true,
        cancelable: true,
      }),
    );
    await el.updateComplete;
    expect(el.shadowRoot!.querySelector(".hint")!.hasAttribute("hidden")).toBe(
      false,
    );
  });

  it("decides which gestures zoom", () => {
    expect(zoomFilter(new WheelEvent("wheel"), true)).toBe("hint");
    expect(zoomFilter(new WheelEvent("wheel", { ctrlKey: true }), true)).toBe(
      "zoom",
    );
    expect(zoomFilter(new WheelEvent("wheel"), false)).toBe("zoom");
    expect(zoomFilter(new MouseEvent("mousedown", { button: 2 }), true)).toBe(
      "ignore",
    );
    expect(zoomFilter(new MouseEvent("mousedown"), true)).toBe("zoom");
  });
});

describe("<uit-graph-view> layout mode", () => {
    const translate = (el: UitGraphView, id: string) =>
        byId(el, id).getAttribute("style");

    it("draws the tree by default and the tiered rows on request", async () => {
        const tree = await graph();
        expect(tree.layoutMode).toBe("tree");
        const tiered = await graph({ layoutMode: "tiered" });
        const model = fixtureModel();
        const depth = SPACING.comfortable.depth;
        const treeLayout = layoutModel(model, "comfortable", "vertical");
        const tieredLayout = layoutTiered(model, "comfortable", "vertical");
        const at = (p: { x: number; y: number }) =>
            `transform: translate(${p.x}px, ${p.y}px)`;
        for (const id of ["dev:uuid-ap", "dev:uuid-flex"]) {
            expect(translate(tree, id)).toBe(at(treeLayout.positions.get(id)!));
            expect(translate(tiered, id)).toBe(
                at(tieredLayout.positions.get(id)!),
            );
        }
        // The tree puts the AP two levels down, the tiers put it on row three.
        expect(tieredLayout.positions.get("dev:uuid-ap")!.y).toBe(3 * depth);
        expect(treeLayout.positions.get("dev:uuid-ap")!.y).toBe(2 * depth);
    });

    it("recomputes the positions when the layout changes", async () => {
        const el = await graph();
        const before = translate(el, "dev:uuid-ap");
        el.layoutMode = "tiered";
        await el.updateComplete;
        const after = translate(el, "dev:uuid-ap");
        expect(after).not.toBe(before);
        expect(after).toBe(
            `transform: translate(0px, ${3 * SPACING.comfortable.depth}px)`,
        );
        el.layoutMode = "tree";
        await el.updateComplete;
        expect(translate(el, "dev:uuid-ap")).toBe(before);
    });
});

describe("<uit-graph-view> updates", () => {
  it("fades new nodes in and removed nodes out, unless motion is reduced", async () => {
    const el = await graph({ reducedMotion: false });
    el.model = fixtureModel({
      toggledGroups: new Set(["group:dev:uuid-ap"]),
    });
    await el.updateComplete;
    expect(byId(el, "cli:cli-phone").classList.contains("enter")).toBe(true);
    el.model = fixtureModel();
    await el.updateComplete;
    expect(el.shadowRoot!.querySelectorAll("g.exits g.node")).toHaveLength(1);
    await new Promise((r) => setTimeout(r, 300));
    await el.updateComplete;
    expect(el.shadowRoot!.querySelectorAll("g.exits g.node")).toHaveLength(0);
  });

  it("keeps the view still when motion is reduced", async () => {
    const el = await graph();
    expect(svgOf(el).classList.contains("still")).toBe(true);
    el.model = fixtureModel({ clients: "hidden" });
    await el.updateComplete;
    expect(el.shadowRoot!.querySelectorAll("g.exits g.node")).toHaveLength(0);
  });
});
