import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WS_NODE_DETAILS, type NodeDetails } from "../src/contract";
import type { HomeAssistant } from "../src/ha-types";
import { makeLocalize } from "../src/localize";
import { UitDetailPanel } from "../src/views/detail-panel";
import type { UitNodeMenu } from "../src/views/node-menu";
import { cleanup, fixtureModel, mount } from "./helpers";

const localize = makeLocalize("en");
afterEach(cleanup);

const panel = (selectedId: string | undefined) =>
    mount<UitDetailPanel>("uit-detail-panel", {
        model: fixtureModel(),
        localize,
        selectedId,
    });
const rows = (el: UitDetailPanel) =>
    Object.fromEntries(
        [...el.shadowRoot!.querySelectorAll(".row")].map((r) => [
            r.querySelector("dt")!.textContent,
            r.querySelector("dd")!.textContent,
        ]),
    );

it("shows a device with its uplink and an Open device link", async () => {
    const el = await panel("dev:uuid-core");
    expect(el.shadowRoot!.querySelector("h3")!.textContent).toBe("Core 24");
    expect(rows(el)).toMatchObject({
        Type: "Switch",
        Model: "USW Pro Max 24",
        State: "Online",
        "Connected to": "Gateway",
        Port: "11 → 26",
        Speed: "10G",
        Link: "Wired",
    });
    el.shadowRoot!.querySelector<HTMLButtonElement>("button.action")!.click();
    expect(location.pathname).toBe("/config/devices/device/reg-core");
});

it("shows PoE draw on a powered link", async () => {
    expect(rows(await panel("dev:uuid-ap"))).toMatchObject({ PoE: "12.3 W" });
});

it("shows a client hidden inside a collapsed group", async () => {
    const el = await panel("cli:cli-tv");
    expect(rows(el)).toMatchObject({
        Connection: "Wired",
        VLAN: "3",
        Network: "Media",
        "Connected to": "Ultra A",
        Port: "4",
    });
    expect(el.shadowRoot!.querySelector("button.action")).toBeNull();
});

it("lists and searches group members, selecting one on click", async () => {
    const el = await panel("group:dev:uuid-u1");
    const selected = vi.fn();
    el.addEventListener("uit-select", (e) =>
        selected((e as CustomEvent).detail),
    );
    el.shadowRoot!.querySelector<HTMLButtonElement>("button.member")!.click();
    expect(selected).toHaveBeenCalledWith({ id: "cli:cli-tv" });
    const search = el.shadowRoot!.querySelector<HTMLInputElement>("input")!;
    search.value = "zzz";
    search.dispatchEvent(new Event("input"));
    await el.updateComplete;
    expect(el.shadowRoot!.querySelectorAll("button.member")).toHaveLength(0);
});

it("closes on request and renders nothing without a selection", async () => {
    const el = await panel("dev:uuid-gw");
    const closed = vi.fn();
    el.addEventListener("uit-close", closed);
    el.shadowRoot!.querySelector<HTMLButtonElement>("button.close")!.click();
    expect(closed).toHaveBeenCalledOnce();
    const empty = await panel("dev:gone");
    expect(empty.shadowRoot!.querySelector("section")).toBeNull();
});

it("shows details in a modal dialog that closes the panel", async () => {
    // jsdom has no dialog methods or layout, so stub them and force the mode.
    // Browsers fire "close" in a later task, so the stub defers it too.
    const proto = HTMLDialogElement.prototype;
    proto.showModal = vi.fn(function (this: HTMLDialogElement) {
        this.open = true;
    });
    proto.close = vi.fn(function (this: HTMLDialogElement) {
        this.open = false;
        queueMicrotask(() => this.dispatchEvent(new Event("close")));
    });
    const settle = () => new Promise((resolve) => setTimeout(resolve));
    try {
        const el = await panel("dev:uuid-core");
        el.modal = true;
        await el.updateComplete;
        const dialog = el.shadowRoot!.querySelector("dialog")!;
        expect(dialog.open).toBe(true);
        expect(dialog.getAttribute("aria-labelledby")).toBe("title");
        expect(dialog.querySelector("section")!.hasAttribute("role")).toBe(
            false,
        );
        expect(dialog.querySelector("#title")!.textContent).toBe("Core 24");
        const closed = vi.fn();
        el.addEventListener("uit-close", closed);

        // A click inside the panel, or a drag from it onto the backdrop,
        // keeps the dialog open.
        const dl = dialog.querySelector<HTMLElement>("dl")!;
        dl.click();
        dl.dispatchEvent(new Event("pointerdown", { bubbles: true }));
        dialog.click();
        await settle();
        expect(closed).not.toHaveBeenCalled();

        // A press and release on the backdrop closes it.
        dialog.dispatchEvent(new Event("pointerdown"));
        dialog.click();
        await settle();
        expect(closed).toHaveBeenCalledOnce();

        // Escape and Close go through the dialog, not straight to uit-close.
        for (const close of [
            () =>
                dialog.dispatchEvent(
                    new KeyboardEvent("keydown", {
                        key: "Escape",
                        bubbles: true,
                    }),
                ),
            () =>
                dialog
                    .querySelector<HTMLButtonElement>("button.close")!
                    .click(),
        ]) {
            dialog.open = true;
            closed.mockClear();
            close();
            expect(dialog.open).toBe(false);
            await settle();
            expect(closed).toHaveBeenCalledOnce();
        }

        dialog.open = true;
        dialog.querySelector<HTMLButtonElement>("button.action")!.click();
        expect(dialog.open).toBe(false);
        expect(location.pathname).toBe("/config/devices/device/reg-core");

        // Detaching the panel (HA suspending the view) closes the dialog.
        dialog.open = true;
        el.remove();
        expect(dialog.open).toBe(false);
        document.body.append(el);

        el.selectedId = undefined;
        await el.updateComplete;
        expect(el.modal).toBe(false);
    } finally {
        delete (proto as Partial<HTMLDialogElement>).showModal;
        delete (proto as Partial<HTMLDialogElement>).close;
    }
});

it("constrains .panel as a shrinkable flex child with a sticky header so narrow panels fit or scroll cleanly", () => {
    // jsdom does not compute layout, so verify the CSS contract directly.
    const cssText = UitDetailPanel.styles.map((s) => s.cssText).join("\n");
    expect(cssText).toMatch(
        /:host\s*\{[^}]*display:\s*flex;[^}]*flex-direction:\s*column;/s,
    );
    expect(cssText).toMatch(
        /:host\(\[narrow\]\)\s*\{[^}]*max-height:\s*calc\(100%\s*-\s*8px\);/s,
    );
    expect(cssText).toMatch(
        /\.panel\s*\{[^}]*flex:\s*1 1 auto;[^}]*min-height:\s*0;[^}]*overflow:\s*auto;/s,
    );
    expect(cssText).toMatch(
        /header\s*\{[^}]*position:\s*sticky;[^}]*top:\s*0;/s,
    );
    expect(cssText).not.toMatch(/\.panel\s*\{[^}]*height:\s*100%;/s);
});

describe("node actions", () => {
    const DETAILS: NodeDetails = {
        kind: "switch",
        ip_address: "192.0.2.10",
        mac_address: "aa:bb:cc:dd:ee:ff",
        ha_device_id: "reg-core",
        entity_id: "sensor.core_status",
    };
    const CLIENT: NodeDetails = {
        kind: "client",
        ip_address: "192.0.2.77",
        entity_id: "device_tracker.tv",
    };

    const hassOf = (
        isAdminUser: boolean | undefined,
        callWS: ReturnType<typeof vi.fn>,
    ) =>
        ({
            callWS,
            user:
                isAdminUser === undefined
                    ? undefined
                    : { is_admin: isAdminUser },
        }) as unknown as HomeAssistant;

    /** callWS answering each node from a table, after an optional gate. */
    const answering = (table: Record<string, NodeDetails>) =>
        vi.fn(async (message: { node_id: string }) => {
            const answer = table[message.node_id];
            if (!answer) throw { code: "node_not_found", message: "" };
            return answer;
        });

    const adminPanel = (
        selectedId: string | undefined,
        callWS: ReturnType<typeof vi.fn> = answering({
            "dev:uuid-core": DETAILS,
            "cli:cli-tv": CLIENT,
        }),
        props: Record<string, unknown> = {},
    ) =>
        mount<UitDetailPanel>("uit-detail-panel", {
            model: fixtureModel(),
            localize,
            selectedId,
            hass: hassOf(true, callWS),
            ...props,
        });

    const menuOf = (el: UitDetailPanel) =>
        el.shadowRoot!.querySelector<UitNodeMenu>("uit-node-menu");
    const labelsOf = (menu: UitNodeMenu) =>
        [...menu.shadowRoot!.querySelectorAll('[role="menuitem"]')].map((i) =>
            i.textContent?.trim(),
        );
    const itemOf = (menu: UitNodeMenu, action: string) =>
        menu.shadowRoot!.querySelector<HTMLElement>(
            `[data-action="${action}"]`,
        )!;
    const status = (el: UitDetailPanel) =>
        el.shadowRoot!.querySelector<HTMLElement>('[role="status"]')!;
    /** Open the menu and wait for the details and the menu to render. */
    async function openMenu(el: UitDetailPanel): Promise<UitNodeMenu> {
        await settleAll(el);
        const menu = menuOf(el)!;
        menu.shadowRoot!.querySelector<HTMLButtonElement>(
            "button.trigger",
        )!.click();
        await settleAll(el);
        return menu;
    }
    async function settleAll(el: UitDetailPanel): Promise<void> {
        for (let i = 0; i < 3; i++) {
            await new Promise((resolve) => setTimeout(resolve, 0));
            await el.updateComplete;
            await menuOf(el)?.updateComplete;
        }
    }

    function stubClipboard(writeText: (text: string) => Promise<void>) {
        Object.defineProperty(window, "isSecureContext", {
            configurable: true,
            value: true,
        });
        Object.defineProperty(navigator, "clipboard", {
            configurable: true,
            value: { writeText },
        });
    }
    // jsdom has no dialog methods; browsers fire "close" in a later task.
    const proto = HTMLDialogElement.prototype;
    beforeEach(() => {
        proto.showModal = vi.fn(function (this: HTMLDialogElement) {
            this.open = true;
        });
        proto.close = vi.fn(function (this: HTMLDialogElement) {
            this.open = false;
            queueMicrotask(() => this.dispatchEvent(new Event("close")));
        });
    });
    afterEach(() => {
        // Detaching a panel with an open dialog calls close(): detach first.
        cleanup();
        delete (proto as Partial<HTMLDialogElement>).showModal;
        delete (proto as Partial<HTMLDialogElement>).close;
        delete (window as { isSecureContext?: boolean }).isSecureContext;
        delete (navigator as { clipboard?: unknown }).clipboard;
        delete (document as { execCommand?: unknown }).execCommand;
    });

    it("never calls the websocket for a non-administrator, who keeps the device link", async () => {
        const callWS = answering({ "dev:uuid-core": DETAILS });
        for (const admin of [false, undefined]) {
            const el = await panel("dev:uuid-core");
            el.hass = hassOf(admin, callWS);
            await settleAll(el);
            expect(callWS).not.toHaveBeenCalled();
            expect(menuOf(el)!.actions).toEqual(["open_device"]);
            expect(menuOf(el)!.loading).toBe(false);
            // The button next to the rows stays exactly as it was.
            expect(
                el.shadowRoot!.querySelector("button.action")!.textContent,
            ).toContain("Open device");
        }
    });

    it("shows no menu to a non-administrator on a client that has no device link", async () => {
        const callWS = answering({});
        const el = await mount<UitDetailPanel>("uit-detail-panel", {
            model: fixtureModel(),
            localize,
            selectedId: "cli:cli-tv",
            hass: hassOf(false, callWS),
        });
        await settleAll(el);
        expect(menuOf(el)).toBeNull();
        expect(callWS).not.toHaveBeenCalled();
    });

    it("asks the integration about the selected node and fills the menu in", async () => {
        let answer!: (details: NodeDetails) => void;
        const callWS = vi.fn(
            () =>
                new Promise<NodeDetails>((resolve) => {
                    answer = resolve;
                }),
        );
        const el = await adminPanel("dev:uuid-core", callWS);
        expect(callWS).toHaveBeenCalledExactlyOnceWith({
            type: WS_NODE_DETAILS,
            entry_id: "entry-1",
            site_id: "site-1",
            node_id: "dev:uuid-core",
        });
        // Until the answer arrives the menu offers what it has and says it is loading.
        expect(menuOf(el)!.loading).toBe(true);
        expect(menuOf(el)!.actions).toEqual(["open_device"]);
        answer(DETAILS);
        await settleAll(el);
        expect(menuOf(el)!.loading).toBe(false);
        expect(menuOf(el)!.actions).toEqual([
            "copy_ip",
            "copy_mac",
            "open_device",
            "open_entity",
        ]);
        // Addresses are never rendered as rows or placeholders.
        expect(el.shadowRoot!.textContent).not.toContain("192.0.2.10");
        expect(callWS).toHaveBeenCalledOnce();
    });

    it("starts every selection with a closed menu", async () => {
        const el = await adminPanel("dev:uuid-core");
        const menu = await openMenu(el);
        expect(menu.shadowRoot!.querySelector('[role="menu"]')).not.toBeNull();
        el.selectedId = "cli:cli-tv";
        await settleAll(el);
        const next = menuOf(el)!;
        expect(next).not.toBe(menu);
        expect(next.shadowRoot!.querySelector('[role="menu"]')).toBeNull();
    });

    it("hides the actions a client has no data for", async () => {
        const el = await adminPanel("cli:cli-tv");
        await settleAll(el);
        expect(menuOf(el)!.actions).toEqual(["copy_ip", "open_entity"]);
    });

    it("asks nothing for a client group", async () => {
        const callWS = answering({});
        const el = await adminPanel("group:dev:uuid-u1", callWS);
        await settleAll(el);
        expect(callWS).not.toHaveBeenCalled();
        expect(menuOf(el)).toBeNull();
    });

    it("drops the answer of a node that is no longer selected", async () => {
        let answerCore!: (details: NodeDetails) => void;
        const callWS = vi.fn((message: { node_id: string }) =>
            message.node_id === "dev:uuid-core"
                ? new Promise<NodeDetails>((resolve) => {
                      answerCore = resolve;
                  })
                : Promise.resolve(CLIENT),
        );
        const el = await adminPanel("dev:uuid-core", callWS);
        el.selectedId = "cli:cli-tv";
        await settleAll(el);
        expect(menuOf(el)!.actions).toEqual(["copy_ip", "open_entity"]);

        answerCore(DETAILS);
        await settleAll(el);
        expect(menuOf(el)!.actions).toEqual(["copy_ip", "open_entity"]);
        expect(callWS).toHaveBeenCalledTimes(2);
    });

    it("shows a rejected request as a localised message and keeps the device link", async () => {
        for (const [code, text] of [
            [
                "unauthorized",
                "Access denied. Node actions need an administrator account.",
            ],
            ["node_not_found", "This device or client is no longer available."],
        ] as const) {
            const callWS = vi.fn(async () => {
                throw { code, message: "server text" };
            });
            const el = await adminPanel("dev:uuid-core", callWS);
            await settleAll(el);
            expect(status(el).textContent).toContain(text);
            expect(menuOf(el)!.actions).toEqual(["open_device"]);
        }
    });

    it("always has a polite live region, empty until there is something to say", async () => {
        const el = await adminPanel("dev:uuid-core");
        await settleAll(el);
        const region = status(el);
        expect(region.getAttribute("aria-live")).toBe("polite");
        expect(region.textContent?.trim()).toBe("");
    });

    it("copies the IP address and reports it in the live region", async () => {
        const writeText = vi.fn(async () => undefined);
        stubClipboard(writeText);
        const el = await adminPanel("dev:uuid-core");
        const menu = await openMenu(el);
        itemOf(menu, "copy_ip").click();
        await settleAll(el);
        expect(writeText).toHaveBeenCalledExactlyOnceWith("192.0.2.10");
        expect(status(el).textContent).toContain("Copied to the clipboard.");
        expect(status(el).querySelector(".manual")).toBeNull();
        expect(menu.shadowRoot!.querySelector('[role="menu"]')).toBeNull();
    });

    it("copies the MAC address", async () => {
        const writeText = vi.fn(async () => undefined);
        stubClipboard(writeText);
        const el = await adminPanel("dev:uuid-core");
        const menu = await openMenu(el);
        itemOf(menu, "copy_mac").click();
        await settleAll(el);
        expect(writeText).toHaveBeenCalledExactlyOnceWith("aa:bb:cc:dd:ee:ff");
    });

    it("shows the value as selectable text when copying fails", async () => {
        stubClipboard(async () => {
            throw new DOMException("denied", "NotAllowedError");
        });
        const el = await adminPanel("dev:uuid-core");
        const menu = await openMenu(el);
        itemOf(menu, "copy_mac").click();
        await settleAll(el);
        expect(status(el).textContent).toContain(
            "Couldn't copy. Select the value below to copy it by hand.",
        );
        expect(status(el).querySelector(".manual")!.textContent).toBe(
            "aa:bb:cc:dd:ee:ff",
        );
    });

    it("copies through the textarea fallback inside the open dialog", async () => {
        let host: Node | null = null;
        (document as unknown as { execCommand: () => boolean }).execCommand =
            () => {
                host =
                    el.shadowRoot!.querySelector("textarea")?.parentNode ??
                    null;
                return true;
            };
        const el = await adminPanel("dev:uuid-core");
        el.modal = true;
        await settleAll(el);
        const menu = await openMenu(el);
        itemOf(menu, "copy_ip").click();
        await settleAll(el);
        expect(host).toBe(el.shadowRoot!.querySelector("dialog"));
        expect(el.shadowRoot!.querySelector("textarea")).toBeNull();
        expect(status(el).textContent).toContain("Copied to the clipboard.");
    });

    it("clears the message when another node is selected", async () => {
        stubClipboard(async () => undefined);
        const el = await adminPanel("dev:uuid-core");
        const menu = await openMenu(el);
        itemOf(menu, "copy_ip").click();
        await settleAll(el);
        expect(status(el).textContent).toContain("Copied");
        el.selectedId = "cli:cli-tv";
        await settleAll(el);
        expect(status(el).textContent?.trim()).toBe("");
    });

    it("does not report a copy that finished after another node was selected", async () => {
        let finish!: () => void;
        stubClipboard(
            () =>
                new Promise<void>((resolve) => {
                    finish = resolve;
                }),
        );
        const el = await adminPanel("dev:uuid-core");
        const menu = await openMenu(el);
        itemOf(menu, "copy_ip").click();
        el.selectedId = "cli:cli-tv";
        await settleAll(el);
        finish();
        await settleAll(el);
        expect(status(el).textContent?.trim()).toBe("");
    });

    it("asks Home Assistant to open the resolved entity", async () => {
        const el = await adminPanel("dev:uuid-core");
        const seen: CustomEvent[] = [];
        document.body.addEventListener("hass-more-info", (e) =>
            seen.push(e as CustomEvent),
        );
        const menu = await openMenu(el);
        itemOf(menu, "open_entity").click();
        await settleAll(el);
        expect(seen).toHaveLength(1);
        expect(seen[0]!.detail).toEqual({ entityId: "sensor.core_status" });
        expect(seen[0]!.bubbles && seen[0]!.composed).toBe(true);
    });

    it("opens the device from the menu through the same navigation as the button", async () => {
        const el = await adminPanel("dev:uuid-core");
        const menu = await openMenu(el);
        itemOf(menu, "open_device").click();
        expect(location.pathname).toBe("/config/devices/device/reg-core");
    });

    it("opens a client's device from the details when the snapshot has none", async () => {
        const callWS = answering({
            "cli:cli-tv": { kind: "client", ha_device_id: "reg/tv 1" },
        });
        const el = await adminPanel("cli:cli-tv", callWS);
        const menu = await openMenu(el);
        expect(labelsOf(menu)).toEqual(["Open device"]);
        itemOf(menu, "open_device").click();
        expect(location.pathname).toBe("/config/devices/device/reg%2Ftv%201");
    });

    describe("in the modal dialog", () => {
        it("keeps Escape inside the menu from closing the dialog", async () => {
            const el = await adminPanel("dev:uuid-core");
            el.modal = true;
            await settleAll(el);
            const dialog = el.shadowRoot!.querySelector("dialog")!;
            const closed = vi.fn();
            el.addEventListener("uit-close", closed);
            const menu = await openMenu(el);
            const escape = () =>
                new KeyboardEvent("keydown", {
                    key: "Escape",
                    bubbles: true,
                    composed: true,
                    cancelable: true,
                });

            itemOf(menu, "copy_ip").dispatchEvent(escape());
            await settleAll(el);
            expect(menu.shadowRoot!.querySelector('[role="menu"]')).toBeNull();
            expect(dialog.open).toBe(true);
            expect(closed).not.toHaveBeenCalled();
            expect(menu.shadowRoot!.activeElement).toBe(
                menu.shadowRoot!.querySelector("button.trigger"),
            );

            // With the menu closed, Escape reaches the dialog again.
            menu.shadowRoot!.querySelector("button.trigger")!.dispatchEvent(
                escape(),
            );
            await settleAll(el);
            expect(dialog.open).toBe(false);
            expect(closed).toHaveBeenCalledOnce();
        });

        it("closes the dialog before opening the device or the entity", async () => {
            const el = await adminPanel("dev:uuid-core");
            el.modal = true;
            await settleAll(el);
            const dialog = el.shadowRoot!.querySelector("dialog")!;
            const openedWith: boolean[] = [];
            document.body.addEventListener("hass-more-info", () =>
                openedWith.push(dialog.open),
            );

            const menu = await openMenu(el);
            itemOf(menu, "open_entity").click();
            expect(openedWith).toEqual([false]);

            dialog.open = true;
            const again = await openMenu(el);
            itemOf(again, "open_device").click();
            expect(dialog.open).toBe(false);
            expect(location.pathname).toBe("/config/devices/device/reg-core");
        });
    });

    describe("opened from a context request", () => {
        it("opens the menu on its first item for the selected node", async () => {
            const el = await adminPanel("dev:uuid-core");
            el.menuRequest = { id: "dev:uuid-core" };
            await settleAll(el);
            const menu = menuOf(el)!;
            expect(
                menu.shadowRoot!.querySelector('[role="menu"]'),
            ).not.toBeNull();
            expect(labelsOf(menu)[0]).toBe("Copy IP address");
            expect(menu.shadowRoot!.activeElement).toBe(
                itemOf(menu, "copy_ip"),
            );
        });

        it("opens while the details still load, then keeps focus in the menu", async () => {
            let answer!: (details: NodeDetails) => void;
            const callWS = vi.fn(
                () =>
                    new Promise<NodeDetails>((resolve) => {
                        answer = resolve;
                    }),
            );
            const el = await adminPanel("dev:uuid-core", callWS, {
                menuRequest: { id: "dev:uuid-core" },
            });
            await settleAll(el);
            const menu = menuOf(el)!;
            expect(labelsOf(menu)).toEqual(["Open device", "Loading actions…"]);
            answer(DETAILS);
            await settleAll(el);
            // The items arrive around the first one; focus stays on the first.
            expect(labelsOf(menu)).toEqual([
                "Copy IP address",
                "Copy MAC address",
                "Open device",
                "Open entity",
            ]);
            expect(menu.shadowRoot!.activeElement).toBe(
                itemOf(menu, "copy_ip"),
            );
        });

        it("opens inside the dialog when the panel is modal", async () => {
            const el = await adminPanel("dev:uuid-core");
            el.modal = true;
            el.menuRequest = { id: "dev:uuid-core" };
            await settleAll(el);
            const dialog = el.shadowRoot!.querySelector("dialog")!;
            const menu = menuOf(el)!;
            expect(dialog.contains(menu)).toBe(true);
            expect(menu.shadowRoot!.activeElement).toBe(
                itemOf(menu, "copy_ip"),
            );
        });

        it("waits for the dialog that a too-short card turns the panel into", async () => {
            // jsdom has no layout: make the panel report that it overflows.
            const original = Object.getOwnPropertyDescriptor(
                Element.prototype,
                "scrollHeight",
            )!;
            Object.defineProperty(Element.prototype, "scrollHeight", {
                configurable: true,
                get(this: Element) {
                    return this.classList.contains("panel") ? 500 : 0;
                },
            });
            try {
                const el = await adminPanel("dev:uuid-core", undefined, {
                    menuRequest: { id: "dev:uuid-core" },
                });
                await settleAll(el);
                expect(el.modal).toBe(true);
                const dialog = el.shadowRoot!.querySelector("dialog")!;
                const menu = menuOf(el)!;
                expect(dialog.contains(menu)).toBe(true);
                expect(
                    menu.shadowRoot!.querySelector('[role="menu"]'),
                ).not.toBeNull();
                expect(menu.shadowRoot!.activeElement).toBe(
                    itemOf(menu, "copy_ip"),
                );
            } finally {
                Object.defineProperty(
                    Element.prototype,
                    "scrollHeight",
                    original,
                );
            }
        });

        it("ignores a request for another node, a request without a menu, and a repeat", async () => {
            const el = await adminPanel("dev:uuid-core");
            el.menuRequest = { id: "cli:cli-tv" };
            await settleAll(el);
            expect(
                menuOf(el)!.shadowRoot!.querySelector('[role="menu"]'),
            ).toBeNull();

            const plain = await mount<UitDetailPanel>("uit-detail-panel", {
                model: fixtureModel(),
                localize,
                selectedId: "cli:cli-tv",
                hass: hassOf(false, answering({})),
                menuRequest: { id: "cli:cli-tv" },
            });
            await settleAll(plain);
            expect(menuOf(plain)).toBeNull();

            // The same request object is consumed once: closing the menu
            // sticks across later renders.
            const request = { id: "dev:uuid-core" };
            el.menuRequest = request;
            await settleAll(el);
            const menu = menuOf(el)!;
            menu.hide();
            el.model = fixtureModel();
            await settleAll(el);
            expect(menu.shadowRoot!.querySelector('[role="menu"]')).toBeNull();
        });
    });
});
