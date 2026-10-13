import { expect, it } from "vitest";
import { makeLocalize } from "../src/localize";

it("interpolates variables", () => {
    expect(
        makeLocalize("en")("issue.clients_truncated", {
            included: 500,
            total: 612,
            max: 500,
        }),
    ).toBe("Showing 500 of 612 clients (limit 500).");
});

it("falls back to English for languages without a table", () => {
    expect(makeLocalize("de-DE")("view.graph")).toBe("Graph");
    expect(makeLocalize(undefined)("view.list")).toBe("List");
});

it("words the node menu in English", () => {
    const t = makeLocalize("en");
    expect([
        t("menu.label"),
        t("menu.copy_ip"),
        t("menu.copy_mac"),
        t("menu.open_entity"),
        t("menu.loading"),
        t("menu.copied"),
        t("menu.copy_failed"),
        t("error.access_denied"),
        t("error.node_not_found"),
    ]).toEqual([
        "Node actions",
        "Copy IP address",
        "Copy MAC address",
        "Open entity",
        "Loading actions…",
        "Copied to the clipboard.",
        "Couldn't copy. Select the value below to copy it by hand.",
        "Access denied. Node actions need an administrator account.",
        "This device or client is no longer available.",
    ]);
});
