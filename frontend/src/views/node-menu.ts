import {
    LitElement,
    css,
    html,
    nothing,
    type PropertyValues,
    type TemplateResult,
} from "lit";
import { repeat } from "lit/directives/repeat.js";
import type { NodeAction } from "../data/node-details";
import { defineOnce } from "../define";
import { fireEvent } from "../ha-types";
import {
    iconTemplate,
    mdiContentCopy,
    mdiDotsVertical,
    mdiInformationOutline,
    mdiOpenInNew,
} from "../icons";
import type { LocalizeFunc, LocalizeKey } from "../localize";
import { controlStyles, themeTokens } from "../styles";

const ACTION_KEYS: Record<NodeAction, LocalizeKey> = {
    copy_ip: "menu.copy_ip",
    copy_mac: "menu.copy_mac",
    open_device: "detail.open_device",
    open_entity: "menu.open_entity",
};

const ACTION_ICONS: Record<NodeAction, string> = {
    copy_ip: mdiContentCopy,
    copy_mac: mdiContentCopy,
    open_device: mdiOpenInNew,
    open_entity: mdiInformationOutline,
};

let menuCount = 0;

/** Elements a press focuses: native controls and anything with a tabindex. */
const FOCUSABLE_ON_PRESS =
    'a[href], button, input, select, textarea, summary, [tabindex], [contenteditable]:not([contenteditable="false"])';

function takesFocusOnPress(target: EventTarget): boolean {
    return (
        target instanceof Element &&
        target.matches(FOCUSABLE_ON_PRESS) &&
        !target.matches(":disabled")
    );
}

/**
 * A button that opens a keyboard-operable menu of node actions.
 *
 * It lives inline in the detail panel, not in a popover or portal, so that it
 * also works inside the panel's native modal dialog (everything outside a modal
 * dialog is inert). The component only chooses; the host performs the action
 * when it hears `uit-action`.
 */
export class UitNodeMenu extends LitElement {
    static override properties = {
        actions: { attribute: false },
        loading: { attribute: false },
        localize: { attribute: false },
        open: { state: true },
    };

    declare actions: NodeAction[];
    /** More actions may follow: show a disabled "Loading" item after the real ones. */
    declare loading: boolean;
    declare localize?: LocalizeFunc;
    declare open: boolean;

    private readonly menuId = `uit-node-menu-${++menuCount}`;
    private listening = false;
    private focusWasInMenu = false;
    /** The user moved off the first item, so a changing list must not move focus. */
    private navigated = false;

    constructor() {
        super();
        this.actions = [];
        this.loading = false;
        this.open = false;
    }

    private get trigger(): HTMLButtonElement | null {
        return this.renderRoot.querySelector<HTMLButtonElement>(
            "button.trigger",
        );
    }

    private get menu(): HTMLElement | null {
        return this.renderRoot.querySelector<HTMLElement>('[role="menu"]');
    }

    private get items(): HTMLElement[] {
        return [
            ...this.renderRoot.querySelectorAll<HTMLElement>(
                '[role="menuitem"]',
            ),
        ];
    }

    private get focusedItem(): HTMLElement | null {
        const active = (this.renderRoot as ShadowRoot).activeElement;
        return active instanceof HTMLElement && this.menu?.contains(active)
            ? active
            : null;
    }

    private get hasContent(): boolean {
        return this.actions.length > 0 || this.loading;
    }

    override connectedCallback(): void {
        super.connectedCallback();
        this.listenOutside(this.open);
    }

    override disconnectedCallback(): void {
        super.disconnectedCallback();
        this.listenOutside(false);
    }

    /** Open the menu and focus its first or last item. */
    async show(where: "first" | "last" = "first"): Promise<void> {
        if (!this.hasContent) return;
        this.navigated = false;
        this.open = true;
        await this.updateComplete;
        const items = this.items;
        items[where === "first" ? 0 : items.length - 1]?.focus();
    }

    /** Close the menu. Whichever way it closes, focus goes back to the button. */
    hide(): void {
        if (!this.open) return;
        this.open = false;
        this.trigger?.focus();
    }

    protected override willUpdate(): void {
        if (!this.hasContent) this.open = false;
        this.focusWasInMenu = this.focusedItem !== null;
    }

    protected override updated(changed: PropertyValues<this>): void {
        if (changed.has("open")) this.listenOutside(this.open);
        // The list changed under focus (the real items arrived while the menu
        // was open): never drop focus, and while it still rests on the first
        // item keep it on the new first one.
        if (this.open && this.focusWasInMenu) {
            const first = this.items[0];
            const focused = this.focusedItem;
            if (focused === null || (!this.navigated && focused !== first))
                first?.focus();
        }
    }

    private listenOutside(on: boolean): void {
        if (on === this.listening) return;
        this.listening = on;
        if (on)
            document.addEventListener("pointerdown", this.onOutsidePress, true);
        else
            document.removeEventListener(
                "pointerdown",
                this.onOutsidePress,
                true,
            );
    }

    private readonly onOutsidePress = (e: Event): void => {
        const path = e.composedPath();
        if (path.includes(this)) return;
        this.hide();
        // A press on a control focuses that control, as it should. Any other
        // press leaves focus on nothing (or on a container such as the dialog),
        // so it is put back on the button once the press has been handled.
        if (!path.some(takesFocusOnPress)) this.keepFocusOnButtonAfterPress();
    };

    /**
     * The browser moves focus as part of the press, after the handler above.
     * Touch sends its mouse events once the pointer is released, so the
     * button gets focus again then as well.
     */
    private keepFocusOnButtonAfterPress(): void {
        const focusButton = (): void => {
            setTimeout(() => {
                if (!this.open) this.trigger?.focus();
            }, 0);
        };
        focusButton();
        const released = (): void => {
            document.removeEventListener("pointerup", released, true);
            document.removeEventListener("pointercancel", released, true);
            focusButton();
        };
        document.addEventListener("pointerup", released, true);
        document.addEventListener("pointercancel", released, true);
    }

    private onTriggerKeydown(e: KeyboardEvent): void {
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            void this.show(e.key === "ArrowDown" ? "first" : "last");
        } else if (e.key === "Escape" && this.open) {
            this.swallow(e);
            this.hide();
        }
    }

    /** Keep a key from the dialog and the card, whose Escape would close the details. */
    private swallow(e: KeyboardEvent): void {
        e.preventDefault();
        e.stopPropagation();
    }

    private onMenuKeydown(e: KeyboardEvent): void {
        const items = this.items;
        const at = this.focusedItem ? items.indexOf(this.focusedItem) : -1;
        let target: number | undefined;
        switch (e.key) {
            case "ArrowDown":
                target = (at + 1) % items.length;
                break;
            case "ArrowUp":
                target = at <= 0 ? items.length - 1 : at - 1;
                break;
            case "Home":
                target = 0;
                break;
            case "End":
                target = items.length - 1;
                break;
            case "Escape":
                this.swallow(e);
                this.hide();
                return;
            case "Tab":
                // Focus passes through the button, then the key moves it on.
                this.hide();
                return;
            default:
                return;
        }
        e.preventDefault();
        this.navigated = true;
        items[target]?.focus();
    }

    private choose(action: NodeAction): void {
        this.hide();
        fireEvent(this, "uit-action", { action });
    }

    protected override render(): TemplateResult | typeof nothing {
        const { localize } = this;
        if (!localize || !this.hasContent) return nothing;
        const label = localize("menu.label");
        return html`<button
                class="trigger"
                type="button"
                aria-haspopup="menu"
                aria-expanded=${String(this.open)}
                aria-controls=${this.open ? this.menuId : nothing}
                aria-label=${label}
                title=${label}
                @click=${() => (this.open ? this.hide() : void this.show())}
                @keydown=${(e: KeyboardEvent) => this.onTriggerKeydown(e)}
            >
                ${iconTemplate(mdiDotsVertical)}
            </button>
            ${this.open
                ? html`<div
                      id=${this.menuId}
                      class="menu"
                      role="menu"
                      aria-label=${label}
                      @keydown=${(e: KeyboardEvent) => this.onMenuKeydown(e)}
                  >
                      ${repeat(
                          this.actions,
                          (action) => action,
                          (action) =>
                              html`<button
                                  type="button"
                                  role="menuitem"
                                  tabindex="-1"
                                  data-action=${action}
                                  @click=${() => this.choose(action)}
                              >
                                  ${iconTemplate(ACTION_ICONS[action])}<span
                                      >${localize(ACTION_KEYS[action])}</span
                                  >
                              </button>`,
                      )}
                      ${this.loading
                          ? html`<div
                                role="menuitem"
                                tabindex="-1"
                                aria-disabled="true"
                                class="loading"
                            >
                                ${localize("menu.loading")}
                            </div>`
                          : nothing}
                  </div>`
                : nothing}`;
    }

    static override styles = [
        themeTokens,
        controlStyles,
        css`
            :host {
                position: relative;
                display: inline-flex;
            }
            .trigger {
                border: none;
                padding: 0;
            }
            .menu {
                position: absolute;
                inset-block-start: calc(100% + 4px);
                inset-inline-end: 0;
                z-index: 3;
                box-sizing: border-box;
                width: max-content;
                min-width: 13em;
                max-width: min(22em, 80vw);
                padding: 4px;
                background: var(--card-background-color);
                border: 1px solid var(--uit-line);
                border-radius: 12px;
                box-shadow: var(
                    --ha-card-box-shadow,
                    0 4px 14px rgba(0, 0, 0, 0.18)
                );
            }
            [role="menuitem"] {
                display: flex;
                align-items: center;
                gap: 10px;
                box-sizing: border-box;
                width: 100%;
                min-height: 44px;
                padding: 0 12px;
                border: none;
                border-radius: 8px;
                font: inherit;
                color: var(--primary-text-color);
                background: none;
                text-align: start;
                cursor: pointer;
            }
            button[role="menuitem"]:hover,
            button[role="menuitem"]:focus {
                background: color-mix(
                    in srgb,
                    var(--uit-focus) 14%,
                    transparent
                );
            }
            .loading {
                color: var(--secondary-text-color);
                cursor: default;
            }
        `,
    ];
}

defineOnce("uit-node-menu", UitNodeMenu);

declare global {
    interface HTMLElementTagNameMap {
        "uit-node-menu": UitNodeMenu;
    }
}
