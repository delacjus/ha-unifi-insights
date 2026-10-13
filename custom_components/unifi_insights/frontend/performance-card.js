import{G as e,It as t,N as n,a as r,b as i,c as a,j as o,l as s,n as c,t as l,w as u,x as d}from"./chunks/register-dashboard-card-mqPoi0AV.js";l({tag:a,editorTag:s,card:class extends c{static editorTag=s;get cardType(){return`custom:${a}`}get sourceCommand(){return t}get subscribeCommand(){return`unifi_insights/performance/subscribe`}get defaultTitle(){return`Device Performance`}get headerIcon(){return e}renderHeaderBadge(){let e=Array.isArray(this.snapshot?.devices)?this.snapshot.devices:[];return this.snapshot?n`<span class="chip ok">${e.length} Devices</span>`:o}renderContent(){let e=this.snapshot;if(!e)return n`<div class="state">No devices</div>`;let t=Array.isArray(e.devices)?e.devices:[],r=t.map(e=>Number(e.cpu_pct)).filter(e=>Number.isFinite(e)&&e>=0),a=t.map(e=>Number(e.memory_pct)).filter(e=>Number.isFinite(e)&&e>=0),s=r.length>0?Math.round(r.reduce((e,t)=>e+t,0)/r.length):0,c=a.length>0?Math.round(a.reduce((e,t)=>e+t,0)/a.length):0;return n`
            <div class="ring-strip">
                <div class="ring-card">
                    <div
                        class="ring-gauge"
                        style=${`--pct: ${s}; --ring-color: var(--uit-${d(s)===`ok`?`online`:d(s)===`warning`?`warning`:`offline`})`}
                    >
                        <span>${s}%</span>
                    </div>
                    <div>
                        <div class="kpi-top">Avg CPU</div>
                        <div class="kpi-sub">${t.length} Devices</div>
                    </div>
                </div>
                <div class="ring-card">
                    <div
                        class="ring-gauge"
                        style=${`--pct: ${c}; --ring-color: var(--primary-color)`}
                    >
                        <span>${c}%</span>
                    </div>
                    <div>
                        <div class="kpi-top">Avg Memory</div>
                        <div class="kpi-sub">System Load</div>
                    </div>
                </div>
            </div>

            <div class="list">
                ${t.slice(0,6).map(e=>{let t=String(e.name??`Device`),r=String(e.kind??`other`),a=Number(e.cpu_pct),s=e.cpu_pct==null||!Number.isFinite(a)?null:Math.min(100,Math.max(0,Math.round(a))),c=e.memory_pct==null?null:Math.round(Number(e.memory_pct)),l=s==null?`ok`:d(s),f=typeof e.clients==`number`?`${e.clients} clients`:void 0;return n`
                        <div class="item-card">
                            <div class="item-icon">
                                ${u(i(r))}
                            </div>
                            <div class="item-body">
                                <div class="item-top">
                                    <span class="item-name">${t}</span>
                                    <span class="item-value">
                                        ${s==null?`--`:`${s}%`}
                                    </span>
                                </div>
                                <div class="bar-track" aria-hidden="true">
                                    <div
                                        class="bar-fill ${l}"
                                        style=${`width: ${s??0}%`}
                                    ></div>
                                </div>
                                ${c!=null||f?n`<div class="item-meta">
                                          ${c==null?o:n`<span>RAM ${c}%</span>`}
                                          ${f?n`<span>· ${f}</span>`:o}
                                      </div>`:o}
                            </div>
                        </div>
                    `})}
            </div>
        `}},editor:class extends r{constructor(){super(a,t)}},name:`UniFi Device Performance`,description:`Infrastructure CPU, memory, PoE, client load, and throughput summary.`});