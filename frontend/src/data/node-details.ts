import { WS_NODE_DETAILS, type NodeDetails } from "../contract";
import {
    isAdmin,
    toWsError,
    type HomeAssistant,
    type WsError,
} from "../ha-types";

export interface NodeDetailsKey {
    entry_id: string;
    site_id: string;
    node_id: string;
}

export type DetailsState =
    | { status: "idle" }
    | { status: "loading" }
    | { status: "ready"; details: NodeDetails }
    | { status: "error"; error: WsError };

const IDLE: DetailsState = { status: "idle" };

/**
 * The details of the one selected node, fetched on demand.
 *
 * Only administrators can call the command, so for anyone else this never
 * touches the socket. Each selection (entry, site and node) gets its own
 * request token: an answer that arrives after another node or site was
 * selected is dropped, and nothing is cached across selections, so one node's
 * addresses can never show under another.
 */
export class NodeDetailsFetcher {
    private current: DetailsState = IDLE;
    private keyId: string | undefined;
    private token = 0;
    private readonly onChange: () => void;

    /** `onChange` runs when an answer or a failure arrives, never during `select`. */
    constructor(onChange: () => void) {
        this.onChange = onChange;
    }

    get state(): DetailsState {
        return this.current;
    }

    /** Point the fetcher at a node; a no-op while the selection is unchanged. */
    select(
        hass: HomeAssistant | undefined,
        key: NodeDetailsKey | undefined,
    ): void {
        const keyId =
            key && hass && isAdmin(hass)
                ? JSON.stringify([key.entry_id, key.site_id, key.node_id])
                : undefined;
        if (keyId === this.keyId) return;
        this.keyId = keyId;
        const token = ++this.token;
        if (!key || !hass || keyId === undefined) {
            this.current = IDLE;
            return;
        }
        this.current = { status: "loading" };
        hass.callWS<NodeDetails>({
            type: WS_NODE_DETAILS,
            entry_id: key.entry_id,
            site_id: key.site_id,
            node_id: key.node_id,
        }).then(
            (details) => this.settle(token, { status: "ready", details }),
            (err: unknown) =>
                this.settle(token, { status: "error", error: toWsError(err) }),
        );
    }

    private settle(token: number, next: DetailsState): void {
        if (token !== this.token) return;
        this.current = next;
        this.onChange();
    }
}

export type NodeAction = "copy_ip" | "copy_mac" | "open_device" | "open_entity";

const has = (value: string | undefined): value is string =>
    typeof value === "string" && value !== "";

/**
 * Menu actions that have data, in menu order. The snapshot's own device id
 * serves everyone; the addresses and the entity come from the details and so
 * exist for administrators only.
 */
export function nodeActions(
    node: { ha_device_id?: string | undefined },
    details: NodeDetails | undefined,
    admin: boolean,
): NodeAction[] {
    const known = admin ? details : undefined;
    const actions: NodeAction[] = [];
    if (has(known?.ip_address)) actions.push("copy_ip");
    if (has(known?.mac_address)) actions.push("copy_mac");
    if (has(node.ha_device_id) || has(known?.ha_device_id))
        actions.push("open_device");
    if (has(known?.entity_id)) actions.push("open_entity");
    return actions;
}
