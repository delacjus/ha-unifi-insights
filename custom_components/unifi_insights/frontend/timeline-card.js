import{B as e,H as t,It as n,N as r,a as i,h as a,j as o,m as s,n as c,ot as l,t as u,tt as d,v as f,w as p}from"./chunks/register-dashboard-card-mqPoi0AV.js";u({tag:s,editorTag:a,card:class extends c{static editorTag=a;get cardType(){return`custom:${s}`}get sourceCommand(){return n}get subscribeCommand(){return`unifi_insights/timeline/subscribe`}get defaultTitle(){return`Event Timeline`}get headerIcon(){return l}renderHeaderBadge(){if(!this.snapshot)return o;let e=Array.isArray(this.snapshot.items)?this.snapshot.items:[];return r`<span class="chip ${e.length>0?`warning`:`ok`}">
            ${e.length} Events
        </span>`}renderContent(){let n=this.snapshot;if(!n)return r`<div class="state">No events</div>`;let i=Array.isArray(n.items)?n.items:[];return i.length===0?r`
                <div class="empty-hero">
                    <div class="icon-badge">
                        ${p(t)}
                    </div>
                    <div class="empty-title">All Quiet · 0 Events</div>
                    <div class="empty-sub">
                        No security or motion detections in the recent window.
                    </div>
                </div>
            `:r`
            <div class="list">
                ${i.slice(0,6).map(t=>{let n=t.source??{},i=String(t.kind??`event`),a=String(t.severity??`info`),s=f(t.timestamp);return r`
                        <div class="item-card">
                            <div
                                class="item-icon ${a===`warning`?`offline`:`online`}"
                            >
                                ${p(i===`ring`?e:d)}
                            </div>
                            <div class="item-body">
                                <div class="item-top">
                                    <span class="item-name">
                                        ${String(n.name??`Src`)}
                                    </span>
                                    <span
                                        class="chip ${a===`warning`?`warning`:`ok`}"
                                    >
                                        ${i}
                                    </span>
                                </div>
                                ${s?r`<div class="item-meta">
                                          <span>${s}</span>
                                      </div>`:o}
                            </div>
                        </div>
                    `})}
            </div>
        `}},editor:class extends i{constructor(){super(s,n)}},name:`UniFi Event Timeline`,description:`Recent UniFi Protect security and device activity timeline.`});