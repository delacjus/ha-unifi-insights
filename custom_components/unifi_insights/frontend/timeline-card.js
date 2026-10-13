<<<<<<< HEAD
<<<<<<< HEAD
import{B as e,Dt as t,R as n,X as r,a as i,h as a,j as o,k as s,m as c,n as l,t as u,tt as d,v as f,w as p}from"./chunks/register-dashboard-card-DwsWPKMB.js";u({tag:c,editorTag:a,card:class extends l{static editorTag=a;get cardType(){return`custom:${c}`}get sourceCommand(){return t}get subscribeCommand(){return`unifi_insights/timeline/subscribe`}get defaultTitle(){return`Event Timeline`}get headerIcon(){return d}renderHeaderBadge(){if(!this.snapshot)return s;let e=Array.isArray(this.snapshot.items)?this.snapshot.items:[];return o`<span class="chip ${e.length>0?`warning`:`ok`}">
=======
import{B as e,Ot as t,R as n,X as r,a as i,h as a,j as o,k as s,m as c,n as l,t as u,tt as d,v as f,w as p}from"./chunks/register-dashboard-card-BJGgFLBk.js";u({tag:c,editorTag:a,card:class extends l{static editorTag=a;get cardType(){return`custom:${c}`}get sourceCommand(){return t}get subscribeCommand(){return`unifi_insights/timeline/subscribe`}get defaultTitle(){return`Event Timeline`}get headerIcon(){return d}renderHeaderBadge(){if(!this.snapshot)return s;let e=Array.isArray(this.snapshot.items)?this.snapshot.items:[];return o`<span class="chip ${e.length>0?`warning`:`ok`}">
>>>>>>> bc7ab1f (feat(frontend): add a tiered layout to the topology card)
=======
import{B as e,H as t,It as n,N as r,a as i,h as a,j as o,m as s,n as c,ot as l,t as u,tt as d,v as f,w as p}from"./chunks/register-dashboard-card-mqPoi0AV.js";u({tag:s,editorTag:a,card:class extends c{static editorTag=a;get cardType(){return`custom:${s}`}get sourceCommand(){return n}get subscribeCommand(){return`unifi_insights/timeline/subscribe`}get defaultTitle(){return`Event Timeline`}get headerIcon(){return l}renderHeaderBadge(){if(!this.snapshot)return o;let e=Array.isArray(this.snapshot.items)?this.snapshot.items:[];return r`<span class="chip ${e.length>0?`warning`:`ok`}">
>>>>>>> 4e8e960 (feat(frontend): add a node action menu to the topology detail panel)
      ${e.length} Events
        </span>`}renderContent(){let n=this.snapshot;if(!n)return r`<div class="state">No events</div>`;let i=Array.isArray(n.items)?n.items:[];return i.length===0?r`
        <div class="empty-hero">
<<<<<<< HEAD
          <div class="icon-badge">${p(e)}</div>
=======
                    <div class="icon-badge">
                        ${p(t)}
                    </div>
>>>>>>> 4e8e960 (feat(frontend): add a node action menu to the topology detail panel)
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