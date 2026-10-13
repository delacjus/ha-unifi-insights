import {
    LitElement,
    css,
    html,
    nothing,
    type PropertyValues,
    type TemplateResult,
} from "lit";
import { keyed } from "lit/directives/keyed.js";
import { copyText } from "../clipboard";
import type { NodeDetails, TopologyNode } from "../contract";
import {
    NodeDetailsFetcher,
    nodeActions,
    type NodeAction,
} from "../data/node-details";
import { errorNotice } from "../data/state";
import { defineOnce } from "../define";
import {
    fireEvent,
    fireMoreInfo,
    isAdmin,
    navigate,
    type HomeAssistant,
} from "../ha-types";
import { iconFor, iconTemplate, mdiClose, mdiOpenInNew } from "../icons";
import type { LocalizeFunc, LocalizeKey, LocalizeVars } from "../localize";
import type { GraphModel, GroupVisual } from "../model/graph-model";
import { controlStyles, themeTokens } from "../styles";
import "./node-menu";
import type { UitNodeMenu } from "./node-menu";
import {
    KIND_KEYS,
    MEDIUM_KEYS,
    STATE_KEYS,
    formatSpeed,
    visualTitle,
} from "./describe";

type Row = [LocalizeKey, string | undefined];

/** What the live region says: a localised message and, after a failed copy, the value to copy by hand. */
interface Status {
    key: LocalizeKey;
    vars?: LocalizeVars | undefined;
    value?: string | undefined;
}

/**
 * Details of the selected device, client or client group; a side panel, or a
 * bottom sheet when narrow. Details too long for the card open as a dialog.
 */
export class UitDetailPanel extends LitElement {
    static override properties = {
        model: { attribute: false },
        selectedId: { attribute: false },
        localize: { attribute: false },
        hass: { attribute: false },
        menuRequest: { attribute: false },
        narrow: { type: Boolean, reflect: true },
        memberQuery: { state: true },
        modal: { state: true },
        copyStatus: { state: true },
    };

    declare model?: GraphModel;
    declare selectedId?: string;
    declare localize?: LocalizeFunc;
    /** For the administrator-only node details; only `callWS` and `user` are read. */
    declare hass?: HomeAssistant;
    /** A fresh object asks to open the menu of that node, on its first item. */
    declare menuRequest?: { id: string } | undefined;
    declare narrow: boolean;
    declare memberQuery: string;
    declare modal: boolean;
    declare copyStatus?: Status | undefined;

    /** Whether the current press began on the backdrop rather than inside the dialog. */
    private pressedBackdrop = false;
    private menuPending = false;
    /**
     * What an address shown or copied for may belong to: entry, site, selected
     * node and the user's rights. Each change starts a new generation, so a
     * copy that started earlier can no longer report into the new one.
     */
    private copyScope: string | undefined;
    private copyGeneration = 0;
    private readonly details = new NodeDetailsFetcher(() =>
        this.requestUpdate(),
    );

    constructor() {
        super();
        this.narrow = false;
        this.memberQuery = "";
        this.modal = false;
    }

    override disconnectedCallback(): void {
        super.disconnectedCallback();
        // HA detaches hidden or cached panels. An open dialog would come back
        // as a clipped box inside the card, so close the details instead.
        this.renderRoot.querySelector("dialog")?.close();
    }

    protected override willUpdate(changed: PropertyValues<this>): void {
        if (changed.has("selectedId")) this.memberQuery = "";
        const scope = JSON.stringify([
            this.model?.snapshot.entry_id,
            this.model?.snapshot.site_id,
            this.selectedId,
            isAdmin(this.hass),
        ]);
        if (scope !== this.copyScope) {
            this.copyScope = scope;
            this.copyGeneration++;
            this.copyStatus = undefined;
        }
        if (this.selectedId === undefined) this.modal = false;
        const node = this.selectedNode;
        this.details.select(
            this.hass,
            node && this.model
                ? {
                      entry_id: this.model.snapshot.entry_id,
                      site_id: this.model.snapshot.site_id,
                      node_id: node.id,
                  }
                : undefined,
        );
        if (
            changed.has("menuRequest") &&
            this.menuRequest !== undefined &&
            this.menuRequest.id === this.selectedId
        )
            this.menuPending = true;
    }

    protected override updated(changed: PropertyValues<this>): void {
        const dialog = this.renderRoot.querySelector("dialog");
        if (dialog) {
            if (!dialog.open) dialog.showModal();
        } else if (changed.has("selectedId") || changed.has("narrow")) {
            // A card too short for the details (#186) shows them over the
            // dashboard instead. Checked only when the panel opens or the card
            // crosses the narrow breakpoint, so a live update or a resize never
            // opens a dialog the user didn't ask for.
            const panel = this.renderRoot.querySelector<HTMLElement>(".panel");
            if (panel && panel.scrollHeight > panel.clientHeight + 1) {
                // The dialog render recreates the menu; open it after that.
                this.modal = true;
                return;
            }
        }
        this.openRequestedMenu();
    }

    /** The selected infrastructure node or client, if the selection is one. */
    private get selectedNode(): TopologyNode | undefined {
        return this.selectedId === undefined
            ? undefined
            : this.model?.nodes.get(this.selectedId);
    }

    private openRequestedMenu(): void {
        if (!this.menuPending) return;
        this.menuPending = false;
        void this.renderRoot
            .querySelector<UitNodeMenu>("uit-node-menu")
            ?.show();
    }

    /** Closing the dialog restores focus and then fires `uit-close`. */
    private close(): void {
        const dialog = this.renderRoot.querySelector("dialog");
        if (dialog) dialog.close();
        else fireEvent(this, "uit-close");
    }

    protected override render(): TemplateResult | typeof nothing {
        const { model, selectedId, localize } = this;
        if (!model || !selectedId || !localize) return nothing;
        const visual = model.visuals.get(selectedId);
        if (visual?.type === "group")
            return this.shell(
                visualTitle(visual, localize),
                this.groupBody(visual, localize),
            );
        const node = model.nodes.get(selectedId);
        if (!node) return nothing;
        const body =
            node.kind === "client"
                ? this.clientBody(model, node, localize)
                : this.deviceBody(model, node, localize);
        return this.shell(node.name, body, this.menu(node, localize));
    }

    private shell(
        title: string,
        body: TemplateResult,
        menu: TemplateResult | typeof nothing = nothing,
    ): TemplateResult {
        const panel = this.panel(title, body, menu);
        if (!this.modal) return panel;
        return html`<dialog
            aria-labelledby="title"
            @close=${() => fireEvent(this, "uit-close")}
            @keydown=${(e: KeyboardEvent) => {
                // Close only this dialog. The card's own Escape handling would
                // skip focus restore and let the key reach an outer dialog.
                if (e.key !== "Escape") return;
                e.preventDefault();
                e.stopPropagation();
                this.close();
            }}
            @pointerdown=${(e: Event) => {
                this.pressedBackdrop = e.target === e.currentTarget;
            }}
            @click=${(e: Event) => {
                // Only the backdrop targets the dialog itself. A text selection
                // dragged out of the panel ends there too, so check the press.
                if (e.target === e.currentTarget && this.pressedBackdrop)
                    this.close();
            }}
        >
            ${panel}
        </dialog>`;
    }

    private panel(
        title: string,
        body: TemplateResult,
        menu: TemplateResult | typeof nothing,
    ): TemplateResult {
        const localize = this.localize!;
        // The dialog takes its name from the heading, so the section isn't a
        // second landmark with the same name.
        return html`<section
            class="panel"
            role=${this.modal ? nothing : "region"}
            aria-label=${this.modal ? nothing : title}
        >
            <header>
                <h3 id="title" title=${title}>${title}</h3>
                ${menu}
                <button
                    class="close"
                    aria-label=${localize("detail.close")}
                    title=${localize("detail.close")}
                    @click=${() => this.close()}
                >
                    ${iconTemplate(mdiClose)}
                </button>
            </header>
            ${body}${this.statusRegion(localize)}
        </section>`;
    }

    /** What the menu offers right now, or nothing while there is nothing to offer. */
    private menu(
        node: TopologyNode,
        localize: LocalizeFunc,
    ): TemplateResult | typeof nothing {
        const state = this.details.state;
        const actions = nodeActions(
            node,
            state.status === "ready" ? state.details : undefined,
            isAdmin(this.hass),
        );
        const loading = state.status === "loading";
        if (actions.length === 0 && !loading) return nothing;
        // Keyed: a new selection starts with a closed menu.
        return html`${keyed(
            node.id,
            html`<uit-node-menu
                .actions=${actions}
                .loading=${loading}
                .localize=${localize}
                @uit-action=${(e: Event) =>
                    this.runAction(
                        node,
                        (e as CustomEvent<{ action: NodeAction }>).detail
                            .action,
                    )}
            ></uit-node-menu>`,
        )}`;
    }

    /**
     * Polite live region for the result of an action. It is always in the
     * panel, so a message put into it is announced. A failed copy also shows
     * the value as plain selectable text.
     */
    private statusRegion(localize: LocalizeFunc): TemplateResult {
        const failed = this.details.state;
        // A value to copy by hand is an address: only an administrator sees one.
        const copied =
            this.copyStatus?.value === undefined || isAdmin(this.hass)
                ? this.copyStatus
                : undefined;
        const status: Status | undefined =
            copied ??
            (failed.status === "error" ? errorNotice(failed.error) : undefined);
        return html`<div
            class="status ${status ? "has-message" : ""}"
            role="status"
            aria-live="polite"
        >
            ${status
                ? html`<span>${localize(status.key, status.vars)}</span
                      >${status.value === undefined
                          ? nothing
                          : html`<code class="manual">${status.value}</code>`}`
                : nothing}
        </div>`;
    }

    private runAction(node: TopologyNode, action: NodeAction): void {
        const state = this.details.state;
        const details: NodeDetails | undefined =
            state.status === "ready" ? state.details : undefined;
        switch (action) {
            case "copy_ip":
                void this.copy(details?.ip_address);
                break;
            case "copy_mac":
                void this.copy(details?.mac_address);
                break;
            case "open_device": {
                const deviceId = node.ha_device_id || details?.ha_device_id;
                if (deviceId) this.openDevice(deviceId);
                break;
            }
            case "open_entity":
                if (details?.entity_id) {
                    // The more-info dialog must not open behind or under ours.
                    this.renderRoot.querySelector("dialog")?.close();
                    fireMoreInfo(this, details.entity_id);
                }
                break;
        }
    }

    private async copy(value: string | undefined): Promise<void> {
        if (!value) return;
        this.copyStatus = undefined;
        const generation = this.copyGeneration;
        // Inside an open modal dialog only its own content can be selected.
        const ok = await copyText(
            value,
            this.renderRoot.querySelector("dialog") ?? this.renderRoot,
        );
        if (generation !== this.copyGeneration) return;
        this.copyStatus = ok
            ? { key: "menu.copied" }
            : { key: "menu.copy_failed", value };
    }

    private openDevice(haDeviceId: string): void {
        // Leaving the dashboard must not leave the dialog open.
        this.renderRoot.querySelector("dialog")?.close();
        navigate(`/config/devices/device/${encodeURIComponent(haDeviceId)}`);
    }

    private rows(rows: Row[]): TemplateResult {
        const shown = rows.filter(
            (r): r is [LocalizeKey, string] =>
                r[1] !== undefined && r[1] !== "",
        );
        return html`<dl>
            ${shown.map(
                ([key, value]) =>
                    html`<div class="row">
                        <dt>${this.localize!(key)}</dt>
                        <dd>${value}</dd>
                    </div>`,
            )}
        </dl>`;
    }

    private uplinkRows(
        model: GraphModel,
        id: string,
        localize: LocalizeFunc,
        withMedium: boolean,
    ): Row[] {
        const parentId = model.realParent.get(id);
        const edge = model.edges.get(id);
        let port: string | undefined;
        if (edge?.parent_port !== undefined) {
            port =
                edge.child_port === undefined
                    ? String(edge.parent_port)
                    : `${edge.parent_port} → ${edge.child_port}`;
        }
        return [
            [
                "detail.parent",
                parentId === undefined
                    ? undefined
                    : model.nodes.get(parentId)?.name,
            ],
            ["detail.port", port],
            [
                "detail.speed",
                edge?.speed_mbps ? formatSpeed(edge.speed_mbps) : undefined,
            ],
            [
                "detail.medium",
                withMedium && edge
                    ? localize(MEDIUM_KEYS[edge.medium])
                    : undefined,
            ],
            [
                "detail.poe",
                edge?.poe_power_w === undefined
                    ? undefined
                    : `${edge.poe_power_w.toFixed(1)} W`,
            ],
        ];
    }

    private deviceBody(
        model: GraphModel,
        node: TopologyNode,
        localize: LocalizeFunc,
    ): TemplateResult {
        const counts = model.clientCounts.get(node.id);
        const hidden = model.links.get(node.id)?.viaHidden ?? [];
        return html`${this.rows([
            ["detail.kind", localize(KIND_KEYS[node.kind])],
            ["detail.model", node.model],
            ["detail.state", localize(STATE_KEYS[node.state])],
            ...this.uplinkRows(model, node.id, localize, true),
            [
                "detail.clients",
                counts
                    ? localize("detail.clients_value", {
                          total: counts.total,
                          wired: counts.wired,
                          wireless: counts.wireless,
                      })
                    : undefined,
            ],
            [
                "detail.via_hidden",
                hidden.length > 0
                    ? hidden.map((k) => localize(KIND_KEYS[k])).join(", ")
                    : undefined,
            ],
        ])}
        ${node.ha_device_id
            ? html`<button
                  class="action"
                  @click=${() => this.openDevice(node.ha_device_id!)}
              >
                  ${iconTemplate(mdiOpenInNew)}${localize("detail.open_device")}
              </button>`
            : nothing}`;
    }

    private clientBody(
        model: GraphModel,
        node: TopologyNode,
        localize: LocalizeFunc,
    ): TemplateResult {
        return this.rows([
            ["detail.state", localize(STATE_KEYS[node.state])],
            [
                "detail.connection",
                node.connection
                    ? localize(MEDIUM_KEYS[node.connection])
                    : undefined,
            ],
            [
                "detail.vlan",
                node.vlan_id === undefined ? undefined : String(node.vlan_id),
            ],
            ["detail.network", node.network_name],
            ...this.uplinkRows(model, node.id, localize, false),
        ]);
    }

    private groupBody(
        group: GroupVisual,
        localize: LocalizeFunc,
    ): TemplateResult {
        const q = this.memberQuery.trim().toLowerCase();
        const members = q
            ? group.members.filter((m) => m.name.toLowerCase().includes(q))
            : group.members;
        const c = group.counts;
        return html`${this.rows([
                [
                    "detail.clients",
                    localize("detail.clients_value", {
                        total: c.total,
                        wired: c.wired,
                        wireless: c.wireless,
                    }),
                ],
            ])}
            <input
                type="search"
                .value=${this.memberQuery}
                placeholder=${localize("detail.search_members")}
                aria-label=${localize("detail.search_members")}
                @input=${(e: Event) => {
                    this.memberQuery = (e.target as HTMLInputElement).value;
                }}
            />
            <ul class="members">
                ${members.map(
                    (m) =>
                        html`<li>
                            <button
                                class="member ${m.state}"
                                @click=${() =>
                                    fireEvent(this, "uit-select", { id: m.id })}
                            >
                                ${iconTemplate(iconFor(m))}<span
                                    class="name"
                                    title=${m.name}
                                    >${m.name}</span
                                >
                                ${m.state === "online"
                                    ? nothing
                                    : html`<span class="state-text"
                                          >${localize(
                                              STATE_KEYS[m.state],
                                          )}</span
                                      >`}
                            </button>
                        </li>`,
                )}
            </ul>`;
    }

    static override styles = [
        themeTokens,
        controlStyles,
        css`
            :host {
                position: absolute;
                top: 8px;
                right: 8px;
                bottom: 8px;
                width: min(320px, 45%);
                display: flex;
                flex-direction: column;
                z-index: 2;
                pointer-events: none;
            }
            :host([narrow]) {
                top: auto;
                left: 0;
                right: 0;
                bottom: 0;
                width: auto;
                max-height: calc(100% - 8px);
            }
            .panel {
                pointer-events: auto;
                box-sizing: border-box;
                flex: 1 1 auto;
                min-height: 0;
                overflow: auto;
                padding: 0 16px 16px;
                background: var(--card-background-color);
                border: 1px solid var(--uit-line);
                border-radius: var(--ha-card-border-radius, 12px);
                box-shadow: var(--ha-card-box-shadow, none);
            }
            header {
                position: sticky;
                top: 0;
                z-index: 1;
                display: flex;
                align-items: center;
                gap: 8px;
                padding-top: 4px;
                background: var(--card-background-color);
            }
            h3 {
                flex: 1;
                min-width: 0;
                margin: 0;
                font-size: 1.1em;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            button.close {
                border: none;
                padding: 0;
            }
            dl {
                margin: 8px 0;
            }
            .row {
                display: flex;
                gap: 12px;
                padding: 4px 0;
            }
            dt {
                color: var(--secondary-text-color);
                min-width: 7em;
            }
            dd {
                margin: 0;
                overflow-wrap: anywhere;
            }
            input {
                width: 100%;
            }
            .members {
                list-style: none;
                margin: 8px 0 0;
                padding: 0;
            }
            .member {
                width: 100%;
                border: none;
                border-radius: 8px;
                justify-content: flex-start;
            }
            .member .name {
                flex: 1;
                min-width: 0;
                text-align: start;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            .member.offline .name {
                opacity: 0.55;
            }
            .state-text {
                color: var(--uit-offline);
                font-weight: 600;
            }
            .action {
                margin-top: 8px;
            }
            .status.has-message {
                margin-top: 8px;
                color: var(--secondary-text-color);
            }
            .manual {
                display: block;
                margin-top: 4px;
                padding: 6px 8px;
                border: 1px solid var(--uit-line);
                border-radius: 8px;
                color: var(--primary-text-color);
                overflow-wrap: anywhere;
                user-select: all;
            }
            dialog {
                pointer-events: auto;
                box-sizing: border-box;
                width: min(400px, calc(100% - 32px));
                max-width: none;
                max-height: calc(100% - 32px);
                padding: 0;
                border: none;
                background: none;
                color: inherit;
                overflow: visible;
            }
            dialog::backdrop {
                background: rgba(0, 0, 0, 0.32);
            }
            dialog .panel {
                max-height: calc(100vh - 32px);
                max-height: calc(100dvh - 32px);
            }
        `,
    ];
}

defineOnce("uit-detail-panel", UitDetailPanel);

declare global {
    interface HTMLElementTagNameMap {
        "uit-detail-panel": UitDetailPanel;
    }
}
