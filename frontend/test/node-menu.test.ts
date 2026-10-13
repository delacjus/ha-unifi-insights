import { afterEach, describe, expect, it, vi } from "vitest";
import type { NodeAction } from "../src/data/node-details";
import { makeLocalize } from "../src/localize";
import "../src/views/node-menu";
import type { UitNodeMenu } from "../src/views/node-menu";
import { cleanup, mount } from "./helpers";

const localize = makeLocalize("en");
afterEach(cleanup);

const ALL: NodeAction[] = ["copy_ip", "copy_mac", "open_device", "open_entity"];

const menu = (props: Record<string, unknown> = {}) =>
    mount<UitNodeMenu>("uit-node-menu", {
        localize,
        actions: ALL,
        loading: false,
        ...props,
    });
const trigger = (el: UitNodeMenu) =>
    el.shadowRoot!.querySelector<HTMLButtonElement>("button.trigger")!;
const list = (el: UitNodeMenu) =>
    el.shadowRoot!.querySelector<HTMLElement>('[role="menu"]');
const items = (el: UitNodeMenu) => [
    ...el.shadowRoot!.querySelectorAll<HTMLElement>('[role="menuitem"]'),
];
const itemOf = (el: UitNodeMenu, action: string) =>
    el.shadowRoot!.querySelector<HTMLElement>(`[data-action="${action}"]`);
const labels = (el: UitNodeMenu) => items(el).map((i) => i.textContent?.trim());
const focused = (el: UitNodeMenu) => el.shadowRoot!.activeElement;
const press = (target: Element, key: string, init: KeyboardEventInit = {}) => {
    const event = new KeyboardEvent("keydown", {
        key,
        bubbles: true,
        composed: true,
        cancelable: true,
        ...init,
    });
    target.dispatchEvent(event);
    return event;
};
/** Click the trigger and wait for the menu to render and take focus. */
async function open(el: UitNodeMenu): Promise<void> {
    trigger(el).click();
    await el.updateComplete;
    await el.updateComplete;
}

describe("<uit-node-menu> button", () => {
    it("is a labelled menu button while the menu is closed", async () => {
        const el = await menu();
        const button = trigger(el);
        expect(button.getAttribute("aria-label")).toBe("Node actions");
        expect(button.getAttribute("aria-haspopup")).toBe("menu");
        expect(button.getAttribute("aria-expanded")).toBe("false");
        expect(button.hasAttribute("aria-controls")).toBe(false);
        expect(list(el)).toBeNull();
    });

    it("renders nothing when there is no action and nothing is loading", async () => {
        const el = await menu({ actions: [] });
        expect(el.shadowRoot!.querySelector("button")).toBeNull();
        el.loading = true;
        await el.updateComplete;
        expect(trigger(el)).not.toBeNull();
    });

    it("opens on click with the first item focused", async () => {
        const el = await menu();
        await open(el);
        const menuEl = list(el)!;
        expect(trigger(el).getAttribute("aria-expanded")).toBe("true");
        expect(trigger(el).getAttribute("aria-controls")).toBe(menuEl.id);
        expect(menuEl.getAttribute("aria-label")).toBe("Node actions");
        expect(labels(el)).toEqual([
            "Copy IP address",
            "Copy MAC address",
            "Open device",
            "Open entity",
        ]);
        expect(items(el).every((i) => i.tabIndex === -1)).toBe(true);
        expect(focused(el)).toBe(items(el)[0]);
    });

    it("closes on a second click and keeps focus on the button", async () => {
        const el = await menu();
        await open(el);
        trigger(el).focus();
        trigger(el).click();
        await el.updateComplete;
        expect(list(el)).toBeNull();
        expect(trigger(el).getAttribute("aria-expanded")).toBe("false");
        expect(focused(el)).toBe(trigger(el));
    });

    it("opens from the keyboard: ArrowDown on the first item, ArrowUp on the last", async () => {
        const el = await menu();
        const down = press(trigger(el), "ArrowDown");
        await el.updateComplete;
        await el.updateComplete;
        expect(down.defaultPrevented).toBe(true);
        expect(focused(el)).toBe(items(el)[0]);

        press(items(el)[0]!, "Escape");
        await el.updateComplete;
        const up = press(trigger(el), "ArrowUp");
        await el.updateComplete;
        await el.updateComplete;
        expect(up.defaultPrevented).toBe(true);
        expect(focused(el)).toBe(items(el)[3]);
    });

    it("can be opened by its host on the last item", async () => {
        const el = await menu();
        await el.show("last");
        expect(focused(el)).toBe(items(el)[3]);
        el.hide();
        await el.updateComplete;
        expect(list(el)).toBeNull();
    });
});

describe("<uit-node-menu> keyboard", () => {
    it("moves with arrows, wrapping, and jumps with Home and End", async () => {
        const el = await menu();
        await open(el);
        const at = (i: number) => items(el)[i];
        const sequence: [string, number][] = [
            ["ArrowDown", 1],
            ["ArrowDown", 2],
            ["ArrowDown", 3],
            ["ArrowDown", 0],
            ["ArrowUp", 3],
            ["ArrowUp", 2],
            ["Home", 0],
            ["End", 3],
        ];
        for (const [key, expected] of sequence) {
            const event = press(focused(el)!, key);
            expect(event.defaultPrevented).toBe(true);
            expect(focused(el), `${key} -> item ${expected}`).toBe(
                at(expected),
            );
        }
    });

    it("lets other keys through", async () => {
        const el = await menu();
        await open(el);
        const event = press(focused(el)!, "a");
        expect(event.defaultPrevented).toBe(false);
        expect(list(el)).not.toBeNull();
    });

    it("closes on Escape, returns focus to the button and keeps the key from the dialog and card", async () => {
        const outer = vi.fn();
        const wrapper = document.createElement("div");
        wrapper.addEventListener("keydown", outer);
        document.body.append(wrapper);
        const el = await menu();
        wrapper.append(el);
        await open(el);

        const event = press(focused(el)!, "Escape");
        await el.updateComplete;
        expect(list(el)).toBeNull();
        expect(focused(el)).toBe(trigger(el));
        expect(event.defaultPrevented).toBe(true);
        expect(outer).not.toHaveBeenCalled();
    });

    it("closes on Escape pressed on the button while the menu is open", async () => {
        const outer = vi.fn();
        const wrapper = document.createElement("div");
        wrapper.addEventListener("keydown", outer);
        document.body.append(wrapper);
        const el = await menu();
        wrapper.append(el);
        await open(el);
        trigger(el).focus();
        const event = press(trigger(el), "Escape");
        await el.updateComplete;
        expect(list(el)).toBeNull();
        expect(focused(el)).toBe(trigger(el));
        expect(event.defaultPrevented).toBe(true);
        expect(outer).not.toHaveBeenCalled();
    });

    it("leaves Escape alone while the menu is closed so the dialog can close", async () => {
        const outer = vi.fn();
        const wrapper = document.createElement("div");
        wrapper.addEventListener("keydown", outer);
        document.body.append(wrapper);
        const el = await menu();
        wrapper.append(el);
        const event = press(trigger(el), "Escape");
        expect(outer).toHaveBeenCalledOnce();
        expect(event.defaultPrevented).toBe(false);
    });

    it("closes on Tab without trapping the key", async () => {
        const el = await menu();
        await open(el);
        const event = press(focused(el)!, "Tab");
        await el.updateComplete;
        expect(list(el)).toBeNull();
        expect(event.defaultPrevented).toBe(false);
        expect(focused(el)).not.toBe(trigger(el));
    });
});

describe("<uit-node-menu> dismissal and activation", () => {
    it("closes on a press outside, not on a press inside, and leaves focus to the pointer", async () => {
        const outside = document.createElement("button");
        document.body.append(outside);
        const el = await menu();
        await open(el);

        for (const target of [trigger(el), items(el)[1]!]) {
            target.dispatchEvent(
                new Event("pointerdown", { bubbles: true, composed: true }),
            );
        }
        await el.updateComplete;
        expect(list(el)).not.toBeNull();

        outside.dispatchEvent(
            new Event("pointerdown", { bubbles: true, composed: true }),
        );
        await el.updateComplete;
        expect(list(el)).toBeNull();
        expect(trigger(el).getAttribute("aria-expanded")).toBe("false");
        expect(focused(el)).not.toBe(trigger(el));
    });

    it("stops listening for outside presses once closed or detached", async () => {
        const add = vi.spyOn(document, "addEventListener");
        const remove = vi.spyOn(document, "removeEventListener");
        try {
            const el = await menu();
            await open(el);
            expect(add).toHaveBeenCalledWith(
                "pointerdown",
                expect.any(Function),
                true,
            );
            press(focused(el)!, "Escape");
            await el.updateComplete;
            expect(remove).toHaveBeenCalledWith(
                "pointerdown",
                expect.any(Function),
                true,
            );
            remove.mockClear();
            await open(el);
            el.remove();
            expect(remove).toHaveBeenCalledWith(
                "pointerdown",
                expect.any(Function),
                true,
            );
        } finally {
            add.mockRestore();
            remove.mockRestore();
        }
    });

    it("fires the chosen action, closes and returns focus to the button", async () => {
        const el = await menu();
        const chosen = vi.fn();
        el.addEventListener("uit-action", (e) =>
            chosen((e as CustomEvent).detail),
        );
        await open(el);
        items(el)[1]!.click();
        await el.updateComplete;
        expect(chosen).toHaveBeenCalledExactlyOnceWith({
            action: "copy_mac",
        });
        expect(list(el)).toBeNull();
        expect(focused(el)).toBe(trigger(el));
    });

    it("closes when the actions go away and stays closed when they return", async () => {
        const el = await menu();
        await open(el);
        el.actions = [];
        await el.updateComplete;
        expect(el.shadowRoot!.querySelector("button")).toBeNull();
        el.actions = ALL;
        await el.updateComplete;
        expect(list(el)).toBeNull();
    });
});

describe("<uit-node-menu> loading", () => {
    it("shows a disabled loading item, then the real items with focus kept in the menu", async () => {
        const el = await menu({ actions: [], loading: true });
        const chosen = vi.fn();
        el.addEventListener("uit-action", chosen);
        await open(el);
        expect(labels(el)).toEqual(["Loading actions…"]);
        const loading = items(el)[0]!;
        expect(loading.getAttribute("aria-disabled")).toBe("true");
        expect(focused(el)).toBe(loading);
        loading.click();
        expect(chosen).not.toHaveBeenCalled();
        expect(list(el)).not.toBeNull();

        el.actions = ["copy_ip", "open_entity"];
        el.loading = false;
        await el.updateComplete;
        await el.updateComplete;
        expect(labels(el)).toEqual(["Copy IP address", "Open entity"]);
        expect(focused(el)).toBe(items(el)[0]);
    });

    it("keeps focus on the item the user moved to when the others arrive around it", async () => {
        const el = await menu({
            actions: ["open_device", "open_entity"],
            loading: true,
        });
        await open(el);
        press(focused(el)!, "ArrowDown");
        expect(focused(el)).toBe(items(el)[1]);
        el.actions = ["copy_ip", "open_device", "open_entity"];
        el.loading = false;
        await el.updateComplete;
        await el.updateComplete;
        expect(focused(el)).toBe(itemOf(el, "open_entity"));
    });

    it("moves focus to the new first item again after the menu was reopened", async () => {
        const el = await menu({
            actions: ["open_device", "open_entity"],
            loading: true,
        });
        await open(el);
        press(focused(el)!, "ArrowDown");
        press(focused(el)!, "Escape");
        await el.updateComplete;
        await open(el);
        expect(focused(el)).toBe(items(el)[0]);
        el.actions = ["copy_ip", "open_device", "open_entity"];
        el.loading = false;
        await el.updateComplete;
        await el.updateComplete;
        expect(focused(el)).toBe(itemOf(el, "copy_ip"));
    });

    it("keeps real items next to the loading item while the rest loads", async () => {
        const el = await menu({ actions: ["open_device"], loading: true });
        await open(el);
        expect(labels(el)).toEqual(["Open device", "Loading actions…"]);
        expect(focused(el)).toBe(items(el)[0]);
    });
});
